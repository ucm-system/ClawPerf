"""Recording proxy: captures real agent sessions as JSONL for replay.

A FastAPI app that sits between the agent (Claude Code, OpenClaw, etc.) and
the upstream LLM endpoint. Every HTTP round-trip (request body, streaming
response chunks, timing, token usage) is recorded to a JSONL file so the
session can be replayed later with ``clawperf --mode replay``.

The proxy is OpenAI-compatible (``/v1/chat/completions``) and also accepts
Anthropic-format requests (``/v1/messages``), translating them on the fly
via :mod:`clawperf.translators`.

Usage::

    # Start the recording proxy (upstream = the real LLM endpoint)
    clawperf --mode record --upstream-endpoint http://localhost:8000 \\
        --proxy-port 9090 --recording session.jsonl

    # Point the agent at the proxy
    export ANTHROPIC_BASE_URL=http://localhost:9090
    export OPENAI_BASE_URL=http://localhost:9090/v1
    claude --print "Fix the bug in main.py"

Inspired by agentic-swarm-bench's ``proxy/server.py`` + ``scenarios/recorder.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# FastAPI is an optional extra ([record]). Import at module level so the
# ``Request`` name lives in this module's globals — with PEP 563 deferred
# annotations (from __future__ import annotations), a function-local import
# breaks FastAPI's ForwardRef resolution and it mis-parses ``request: Request``
# as a query parameter (422 "missing query request").
try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, StreamingResponse
except ImportError:  # pragma: no cover — only when [record] extra is missing
    FastAPI = None
    Request = None
    JSONResponse = None
    StreamingResponse = None

logger = logging.getLogger("clawperf")


@dataclass
class RecordedEntry:
    """One recorded HTTP round-trip (request → streaming response)."""
    index: int
    request_body: Dict[str, Any]
    response_chunks: List[Dict[str, Any]] = field(default_factory=list)
    ttft_ms: Optional[float] = None
    e2e_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    status_code: int = 200
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "request_body": self.request_body,
            "response_chunks": self.response_chunks,
            "ttft_ms": self.ttft_ms,
            "e2e_ms": round(self.e2e_ms, 3),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "status_code": self.status_code,
            "error": self.error,
        }


class RecordingProxy:
    """In-process recording proxy logic (transport-agnostic).

    Wraps an ``httpx.AsyncClient`` that forwards to the upstream endpoint.
    Each call to :meth:`forward_streaming` returns the full response while
    also appending a ``RecordedEntry`` to the JSONL file.
    """

    def __init__(self, upstream_endpoint: str, recording_path: str,
                 upstream_api: str = "openai", api_key: str = ""):
        self.upstream = upstream_endpoint
        self.recording_path = recording_path
        self.upstream_api = upstream_api
        self.api_key = api_key
        self._client = None
        self._index = 0
        self._lock = asyncio.Lock()
        self._entries: List[RecordedEntry] = []
        # Open the recording file in append mode (sessions can be resumed),
        # but tell the user when they're appending so sessions don't silently mix.
        import os
        out_dir = os.path.dirname(recording_path)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        prior_entries = 0
        if os.path.exists(recording_path) and os.path.getsize(recording_path) > 0:
            try:
                with open(recording_path, encoding="utf-8-sig") as f:
                    prior_entries = sum(1 for line in f if line.strip())
            except OSError:
                prior_entries = 0
        if prior_entries:
            print(f"[ClawPerf] Appending to existing recording {recording_path!r} "
                  f"({prior_entries} prior entries will be kept). "
                  "Delete the file first to start a fresh recording.",
                  flush=True)
        self._file = open(recording_path, "a", encoding="utf-8")

    async def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(timeout=600.0)
        return self._client

    async def forward_streaming(self, request_body: Dict[str, Any],
                               path: str = "/v1/chat/completions") -> tuple:
        """Forward a streaming request upstream, record the round-trip.

        Returns (status_code, list_of_chunks, entry) where chunks are the
        parsed SSE data dicts the upstream sent.
        """
        async with self._lock:
            entry = RecordedEntry(index=self._index, request_body=request_body)
            self._index += 1

        client = await self._get_client()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Avoid double path: the upstream may already carry the full
        # /v1/chat/completions suffix (e.g. from run_proxy's normalize_endpoint).
        if self.upstream.rstrip("/").endswith(path):
            url = self.upstream.rstrip("/")
        else:
            url = self.upstream.rstrip("/") + path
        t0 = time.perf_counter()
        chunks: List[Dict] = []
        ttft = None

        try:
            async with client.stream("POST", url, json=request_body, headers=headers) as resp:
                entry.status_code = resp.status_code
                if resp.status_code >= 400:
                    body = await resp.aread()
                    entry.error = body.decode("utf-8", "replace")
                    self._record_entry(entry)
                    return resp.status_code, chunks, entry

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        chunks.append(chunk)
                        if ttft is None:
                            ttft = (time.perf_counter() - t0) * 1000
                        # Extract usage from the last chunk.
                        if chunk.get("usage"):
                            u = chunk["usage"]
                            entry.input_tokens = u.get("prompt_tokens")
                            entry.output_tokens = u.get("completion_tokens")
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            entry.error = str(e)
            entry.status_code = 502

        entry.ttft_ms = ttft
        entry.e2e_ms = (time.perf_counter() - t0) * 1000
        entry.response_chunks = chunks
        self._record_entry(entry)
        return entry.status_code, chunks, entry

    def _record_entry(self, entry: RecordedEntry):
        """Append the entry to the JSONL file and keep it in memory."""
        self._entries.append(entry)
        line = json.dumps(entry.to_dict(), ensure_ascii=False)
        self._file.write(line + "\n")
        self._file.flush()

    def get_summary(self) -> Dict:
        total_in = sum(e.input_tokens or 0 for e in self._entries)
        total_out = sum(e.output_tokens or 0 for e in self._entries)
        errors = sum(1 for e in self._entries if e.error)
        ttfts = [e.ttft_ms for e in self._entries if e.ttft_ms is not None]
        return {
            "entries": len(self._entries),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "errors": errors,
            "ttft_avg_ms": sum(ttfts) / len(ttfts) if ttfts else 0,
        }

    async def close(self):
        if self._client:
            await self._client.aclose()
        self._file.close()


def create_app(proxy: RecordingProxy):
    """Create the FastAPI app for the recording proxy.

    Returns a FastAPI app instance. FastAPI is imported lazily so the
    ``[record]`` extra is only needed when this function is called.
    """
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, StreamingResponse

    app = FastAPI(title="ClawPerf Recording Proxy")

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        body = await request.json()
        status, chunks, entry = await proxy.forward_streaming(
            body, path="/v1/chat/completions"
        )
        if entry.error and not chunks:
            return JSONResponse(
                {"error": entry.error, "detail": entry.error},
                status_code=status,
            )
        # Re-stream the recorded chunks as SSE.
        async def gen():
            for chunk in chunks:
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/v1/messages")
    async def anthropic_messages(request: Request):
        """Accept Anthropic-format requests, translate to OpenAI, forward."""
        from clawperf.translators import (
            StreamingToolCallAccumulator,
            anthropic_messages_to_openai,
            anthropic_tools_to_openai,
            openai_chunk_to_anthropic_events,
        )
        body = await request.json()
        messages = anthropic_messages_to_openai(body.get("messages", []))
        tools = anthropic_tools_to_openai(body.get("tools", [])) if body.get("tools") else None

        openai_body = {
            "model": body.get("model", ""),
            "messages": messages,
            "max_tokens": body.get("max_tokens", 1024),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            openai_body["tools"] = tools

        status, chunks, entry = await proxy.forward_streaming(
            openai_body, path="/v1/chat/completions"
        )
        if entry.error and not chunks:
            return JSONResponse(
                {"error": entry.error}, status_code=status,
            )
        # Translate OpenAI chunks back to Anthropic SSE events.
        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        model = body.get("model", "")
        accumulator = StreamingToolCallAccumulator()
        started = False

        async def gen():
            nonlocal started
            start_event = {
                "type": "message_start",
                "message": {
                    "id": msg_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                    "stop_reason": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            }
            yield f"event: message_start\ndata: {json.dumps(start_event)}\n\n"
            for chunk in chunks:
                events, started = openai_chunk_to_anthropic_events(
                    chunk, msg_id, model, accumulator, started
                )
                for evt in events:
                    yield f"event: {evt['event']}\ndata: {json.dumps(evt['data'])}\n\n"
            yield "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/benchmark/summary")
    async def summary():
        return proxy.get_summary()

    @app.get("/v1/models")
    async def list_models():
        """Minimal stub so agents that probe /v1/models don't fail."""
        return {"object": "list", "data": [{"id": "recorded", "object": "model"}]}

    return app


async def run_proxy(upstream_endpoint: str, recording_path: str,
                    proxy_port: int = 9090, upstream_api: str = "openai",
                    api_key: str = ""):
    """Start the recording proxy server (blocking)."""
    import uvicorn

    from clawperf.translators import detect_api_type, normalize_endpoint

    if upstream_api == "auto":
        upstream_api = detect_api_type(upstream_endpoint)
    # Normalize the upstream endpoint so the proxy forwards to the right path.
    upstream = normalize_endpoint(upstream_endpoint, "openai")
    proxy = RecordingProxy(
        upstream_endpoint=upstream,
        recording_path=recording_path,
        upstream_api=upstream_api,
        api_key=api_key,
    )
    app = create_app(proxy)
    config = uvicorn.Config(app, host="0.0.0.0", port=proxy_port, log_level="info")
    server = uvicorn.Server(config)

    print(f"\n{'=' * 70}")
    print("ClawPerf Recording Proxy")
    print(f"  Listening on:   http://0.0.0.0:{proxy_port}")
    print(f"  Upstream:       {upstream_endpoint} ({upstream_api})")
    print(f"  Recording to:   {recording_path}")
    print("  Endpoints:")
    print("    POST /v1/chat/completions  (OpenAI-compatible)")
    print("    POST /v1/messages           (Anthropic-compatible)")
    print("    GET  /benchmark/summary")
    print(f"{'=' * 70}\n")

    try:
        await server.serve()
    finally:
        await proxy.close()
