"""Replay engine: re-runs a recorded session against any endpoint.

Reads a JSONL recording produced by :mod:`clawperf.recorder` (or a compatible
format) and replays the request sequence against a target endpoint, collecting
fresh timing metrics (TTFT, decode tok/s, ITL).

The key feature is **live-history replay**: instead of sending each recorded
entry's messages verbatim, the player extracts only the *new* client-side
messages (user/tool/system) from the delta between consecutive entries and
appends the *actual* server response as the assistant turn. This ensures the
KV-cache prefix matches between turns even when replaying against a different
model than the recording — a subtle bug that ASB's ``--history-mode live`` fixes.

Usage::

    clawperf --mode replay --endpoint http://localhost:8000 \\
        --model Qwen/Qwen2.5-72B --recording session.jsonl

Inspired by agentic-swarm-bench's ``scenarios/player.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("clawperf")


@dataclass
class ReplayRequest:
    """One request extracted from a recording, ready to replay."""
    index: int
    messages: List[Dict[str, Any]]
    tools: Optional[List[Dict]] = None
    max_tokens: Optional[int] = None  # None → player's default_max_tokens
    model: str = ""


@dataclass
class ReplayResult:
    """Metrics for one replayed request."""
    index: int
    success: bool
    ttft_ms: Optional[float] = None
    e2e_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    itl_values: List[float] = field(default_factory=list)
    generated_text: str = ""
    error: Optional[str] = None
    status_code: Optional[int] = None


def load_recording(path: str) -> List[Dict]:
    """Load a JSONL recording into a list of entry dicts."""
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def extract_request(entry: Dict) -> ReplayRequest:
    """Build a ReplayRequest from a recorded entry.

    Supports two JSONL shapes:
    - Recorder output: {"request_body": {"messages": [...], "tools": ...}, ...}
    - Flat trace format: {"messages": [...], "tools": ..., "hash_ids": ...}
    """
    body = entry.get("request_body")
    if body is None or not isinstance(body, dict) or "messages" not in body:
        body = entry  # flat format (kvcache.ai-style traces)
    messages = body.get("messages", [])
    tools = body.get("tools")
    max_tokens = body.get("max_tokens")  # None → player default
    model = body.get("model", "")
    return ReplayRequest(
        index=entry.get("index", 0),
        messages=messages,
        tools=tools,
        max_tokens=max_tokens,
        model=model,
    )


def extract_response_text(entry: Dict) -> str:
    """Extract the assistant's response text from a recorded entry's chunks."""
    chunks = entry.get("response_chunks", [])
    parts: List[str] = []
    for chunk in chunks:
        choices = chunk.get("choices", [])
        if not choices:
            continue
        delta = choices[0].get("delta", {})
        if delta.get("content"):
            parts.append(delta["content"])
    return "".join(parts)


def extract_new_client_messages(
    prev_messages: List[Dict], curr_messages: List[Dict]
) -> List[Dict]:
    """Extract the new client-side messages added since the previous entry.

    In live-history mode, the assistant turns from the recording are replaced
    by the actual server responses during replay. This function finds the
    delta: messages that appear in curr but not in prev, excluding assistant
    turns (which will be filled by the live response).
    """
    if not prev_messages:
        # First entry — take the initial system + user message.
        return [m for m in curr_messages if m.get("role") != "assistant"]

    # Find where the previous messages end in the current list.
    prev_len = len(prev_messages)
    new_msgs: List[Dict] = []

    # The current messages should be a superset of the previous ones (plus
    # the assistant response to the last turn and any new tool/user messages).
    if len(curr_messages) > prev_len:
        for m in curr_messages[prev_len:]:
            role = m.get("role", "")
            if role == "assistant":
                # Skip — the live server response replaces this.
                continue
            new_msgs.append(m)

    return new_msgs


def build_live_history(
    entries: List[Dict], live_responses: List[str]
) -> List[ReplayRequest]:
    """Build the replay request sequence using live-history mode.

    ``live_responses`` is a list of actual server responses from previous
    replays (empty for the first pass). Each response text is inserted as
    the assistant turn, ensuring the KV-cache prefix matches what the server
    actually generated (not what the original recording had).
    """
    requests: List[ReplayRequest] = []
    accumulated: List[Dict] = []
    live_idx = 0

    for entry in entries:
        req = extract_request(entry)
        new_msgs = extract_new_client_messages(accumulated, req.messages)

        # If we have a live response, append it as the assistant turn.
        if live_idx < len(live_responses) and live_responses[live_idx]:
            accumulated.append({
                "role": "assistant",
                "content": live_responses[live_idx],
            })
            live_idx += 1

        # Append the new client messages.
        accumulated.extend(new_msgs)

        # Build the replay request with the full accumulated history.
        requests.append(ReplayRequest(
            index=req.index,
            messages=list(accumulated),  # copy
            tools=req.tools,
            max_tokens=req.max_tokens,
            model=req.model,
        ))

    return requests


class ReplayPlayer:
    """Replays recorded requests against a target endpoint, collecting metrics."""

    def __init__(self, endpoint: str, model: str, api_key: str = "",
                 timeout: int = 600, concurrency: int = 1,
                 history_mode: str = "live", active_users: int = 1,
                 default_max_tokens: int = 1024):
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.concurrency = concurrency
        self.history_mode = history_mode  # "live" or "verbatim"
        self.active_users = active_users  # session-aware concurrency
        self.default_max_tokens = default_max_tokens
        self._client = None
        self._live_responses: List[str] = []

    async def _get_client(self):
        if self._client is None:
            import httpx
            # trust_env=False so lab/private endpoints aren't routed through a
            # corporate HTTP(S)_PROXY / system proxy (which returns 502).
            self._client = httpx.AsyncClient(timeout=self.timeout, trust_env=False)
        return self._client

    async def replay(self, entries: List[Dict]) -> List[ReplayResult]:
        """Replay all entries and return results.

        Three scheduling modes:
        - ``live``: responses from earlier entries feed forward into the
          history of later entries, preserving KV-cache prefix alignment
          across model changes. Sequential by design.
        - ``verbatim`` + entries carrying ``user_id``: sessions are replayed
          in file order (turns stay contiguous within a session) and at most
          ``active_users`` sessions run concurrently.
        - ``verbatim`` without user ids: plain request-level concurrency
          (``concurrency`` in-flight requests).
        """
        if self.history_mode == "live":
            requests = build_live_history(entries, self._live_responses)
        else:
            requests = [extract_request(e) for e in entries]

        results: List[ReplayResult] = []
        sem = asyncio.Semaphore(self.concurrency)

        async def _one(req: ReplayRequest) -> ReplayResult:
            async with sem:
                return await self._send_request(req)

        if self.history_mode == "live" and self.concurrency <= 1:
            # Sequential live-history replay (history depends on prior
            # responses; concurrent live replay isn't well-defined).
            for i, req in enumerate(requests):
                result = await self._send_request(req)
                results.append(result)
                self._live_responses.append(result.generated_text if result.success else "")
                # Rebuild remaining entries in live-history with the updated
                # responses so KV-cache prefixes stay aligned turn to turn.
                new_reqs = build_live_history(entries[i + 1:], self._live_responses)
                for j, r in enumerate(requests[i + 1:]):
                    if j < len(new_reqs):
                        r.messages = new_reqs[j].messages
        elif self.history_mode == "verbatim" and any(
                isinstance(e.get("user_id"), int) for e in entries):
            # Session-aware concurrency: group per user_id, keep each
            # session's turns in file order, overlap at most active_users.
            groups: Dict[int, List[ReplayRequest]] = {}
            for e, req in zip(entries, requests):
                uid = e.get("user_id", id(e))
                groups.setdefault(uid, []).append(req)
            win = asyncio.Semaphore(max(1, self.active_users))

            async def _run_group(reqs: List[ReplayRequest]):
                async with win:
                    for req in reqs:
                        results.append(await self._send_request(req))

            await asyncio.gather(*[_run_group(g) for g in groups.values()])
        else:
            tasks = [asyncio.create_task(_one(r)) for r in requests]
            results = await asyncio.gather(*tasks)

        return results

    async def _send_request(self, req: ReplayRequest) -> ReplayResult:
        """Send one request to the endpoint, streaming the response."""
        client = await self._get_client()
        from clawperf.translators import normalize_endpoint
        url = normalize_endpoint(self.endpoint, "openai")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body: Dict[str, Any] = {
            "model": self.model,
            "messages": req.messages,
            "max_tokens": req.max_tokens or self.default_max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if req.tools:
            body["tools"] = req.tools

        t0 = time.perf_counter()
        ttft = None
        content_parts: List[str] = []
        itl_values: List[float] = []
        last_chunk_time = None
        input_tokens = None
        output_tokens = None
        status_code = None

        try:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                status_code = resp.status_code
                if resp.status_code >= 400:
                    err_body = await resp.aread()
                    return ReplayResult(
                        index=req.index, success=False,
                        error=err_body.decode("utf-8", "replace")[:500],
                        status_code=resp.status_code,
                    )
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    now = time.perf_counter()
                    if ttft is None:
                        ttft = (now - t0) * 1000
                        last_chunk_time = now
                    else:
                        itl_values.append((now - last_chunk_time) * 1000)
                        last_chunk_time = now

                    choices = chunk.get("choices", [])
                    if not choices:
                        if chunk.get("usage"):
                            input_tokens = chunk["usage"].get("prompt_tokens")
                            output_tokens = chunk["usage"].get("completion_tokens")
                        continue
                    delta = choices[0].get("delta", {})
                    if delta.get("content"):
                        content_parts.append(delta["content"])
        except Exception as e:
            return ReplayResult(
                index=req.index, success=False, error=str(e),
                status_code=status_code,
            )

        e2e = (time.perf_counter() - t0) * 1000
        return ReplayResult(
            index=req.index, success=True,
            ttft_ms=ttft, e2e_ms=e2e,
            input_tokens=input_tokens, output_tokens=output_tokens,
            itl_values=itl_values,
            generated_text="".join(content_parts),
            status_code=status_code,
        )

    async def close(self):
        if self._client:
            await self._client.aclose()


def summarize_replay(results: List[ReplayResult]) -> Dict:
    """Compute summary statistics from replay results."""
    ok = [r for r in results if r.success]
    errs = [r for r in results if not r.success]
    total_out = sum(r.output_tokens or 0 for r in ok)
    total_in = sum(r.input_tokens or 0 for r in ok)

    ttft_vals = [r.ttft_ms for r in ok if r.ttft_ms is not None]
    e2e_vals = [r.e2e_ms for r in ok if r.e2e_ms]
    all_itl = [v for r in ok for v in r.itl_values]

    def _pct(vals, q):
        if not vals:
            return None
        s = sorted(vals)
        n = len(s)
        if n == 1:
            return s[0]
        pos = q * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        return s[lo] * (1 - frac) + s[hi] * frac

    decode_time_s = sum(
        (r.e2e_ms - (r.ttft_ms or 0)) / 1000 for r in ok
        if r.e2e_ms and r.ttft_ms and r.e2e_ms > r.ttft_ms
    )
    decode_toks = total_out / decode_time_s if decode_time_s > 0 else None

    return {
        "mode": "replay",
        "total_requests": len(results),
        "success_count": len(ok),
        "error_count": len(errs),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "ttft_p50_ms": _pct(ttft_vals, 0.50),
        "ttft_p95_ms": _pct(ttft_vals, 0.95),
        "ttft_p99_ms": _pct(ttft_vals, 0.99),
        "e2e_p50_ms": _pct(e2e_vals, 0.50),
        "decode_tok_s": decode_toks,
        "itl_p50_ms": _pct(all_itl, 0.50),
        "itl_p95_ms": _pct(all_itl, 0.95),
    }
