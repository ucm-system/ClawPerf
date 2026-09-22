"""Convert external agent-trace datasets into ClawPerf replayable traces.

Supported input formats (auto-detected by extension/structure):
- **Claude Code session JSONL** (Fable-5-traces, kimi-k2.6-claude-code-traces,
  and any ``claude/projects/**/*.jsonl`` export):
  lines with ``type: "user"|"assistant"`` carrying Anthropic-style
  ``message`` objects (content blocks: text / tool_use / tool_result).
- **OpenAI-style message JSONL** (flat ``{"messages": [...]}`` per line).

Output: one ClawPerf flat trace (kvcache.ai-compatible) per CLI invocation —
each assistant turn becomes one request whose messages carry the full
conversation history, so later turns extend the shared prefix (realistic
growing-context KV behavior). Multi-file input maps to distinct ``user_id``
sessions.

Usage as a library::

    from clawperf.trace_converter import convert_claude_code_file
    entries = convert_claude_code_file("session.jsonl", session_id=0)

Or via CLI::

    clawperf trace-convert --input a.jsonl --input b.jsonl \
        --output trace.jsonl --block-size 64
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger("clawperf")


# ── Hash helpers (same scheme as the trace simulator) ─────────────────────────

def block_hashes(text: str, block_size: int = 64) -> List[int]:
    """Map text to block-level hash ids (64-token ≈ 256-char blocks)."""
    chars = list(text)
    step = max(1, block_size * 4)
    blocks = [chars[i:i + step] for i in range(0, len(chars), step)]
    out = []
    for b in blocks:
        digest = hashlib.sha256("".join(b).encode("utf-8")).hexdigest()
        out.append(int(digest[:12], 16))
    return out


def text_len(text: str) -> int:
    """Rough token estimate (chars/4), matching the rest of ClawPerf."""
    return max(1, len(text) // 4)


def _message_wire_text(m: Dict) -> str:
    """Everything of one message that goes over the wire: content (text,
    tool_use/tool_result blocks) plus tool_calls."""
    parts: List[str] = []
    c = m.get("content")
    if isinstance(c, str):
        parts.append(c)
    elif c is not None:
        parts.append(json.dumps(c, ensure_ascii=False))
    for tc in m.get("tool_calls") or []:
        if isinstance(tc, dict):
            parts.append(json.dumps(tc, ensure_ascii=False))
    return " ".join(parts)


def estimate_messages_tokens(msgs: List[Dict], per_message_overhead: int = 4) -> int:
    """Rough token estimate for a message list (chars/4 + template overhead).

    Counts tool_use / tool_result blocks and tool_calls — the dominant payload
    in agent sessions — not just visible text, so ``input_length`` reflects
    what the server actually tokenizes (chat-template markers add a few tokens
    per message).
    """
    total = sum(text_len(_message_wire_text(m)) + per_message_overhead for m in msgs)
    return max(1, total)


# ── Claude Code session → turns ───────────────────────────────────────────────

def extract_claude_turns(lines: Iterable[Dict]) -> List[Dict]:
    """Extract (role, content) turns from a Claude Code session JSONL.

    Returns Anthropic-style message dicts (``{"role", "content"}``) for the
    conversation transcript — tool_use / tool_result content blocks preserved.
    """
    turns: List[Dict] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        ltype = line.get("type")
        if ltype not in ("user", "assistant"):
            continue
        msg = line.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in ("user", "assistant"):
            continue
        if isinstance(content, str):
            if content:
                turns.append({"role": role, "content": content})
            continue
        if isinstance(content, list):
            # Keep text + tool_use + tool_result blocks; drop "thought"/"fallback".
            kept = []
            for block in content:
                btype = block.get("type", "")
                if btype == "text":
                    kept.append(block)
                elif btype == "tool_use":
                    kept.append(block)
                elif btype == "tool_result":
                    kept.append(block)
                elif btype == "thinking":
                    kept.append(block)
                # fallback/thought blocks carry model routing info — skip
            if kept:
                turns.append({"role": role, "content": kept})
    return turns


def claude_turns_to_requests(turns: List[Dict], max_requests: int = 0) -> List[Dict]:
    """Turn a conversation transcript into a sequence of replay requests.

    Each assistant turn becomes one request whose messages are the full
    history up to and including that turn (grown context ⇒ shared prefix).
    Optionally capped at ``max_requests`` (last N requests kept).
    """
    from clawperf.translators import anthropic_to_openai_message

    requests: List[Dict] = []
    history: List[Dict] = []

    for turn in turns:
        if turn["role"] == "user":
            converted = anthropic_to_openai_message(turn)
            if isinstance(converted, list):
                history.extend(converted)
            elif converted:
                history.append(converted)
            continue
        # assistant turn: emit a request with history + this turn
        converted = anthropic_to_openai_message(turn)
        if converted is None:
            continue
        if isinstance(converted, list):
            assistant_msgs = converted
        else:
            assistant_msgs = [converted]
        history.append(assistant_msgs[0])  # the assistant message itself
        # Tool results (from the following user turn) join history naturally.
        request_messages = [dict(m) for m in history]
        requests.append({"messages": request_messages})

    if max_requests > 0 and len(requests) > max_requests:
        requests = requests[-max_requests:]
    return requests


def convert_claude_code_file(
    path: str,
    session_id: int = 0,
    block_size: int = 64,
    max_requests: int = 0,
) -> List[Dict]:
    """Convert one Claude Code session JSONL into ClawPerf trace lines."""
    lines = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    turns = extract_claude_turns(lines)
    requests = claude_turns_to_requests(turns, max_requests=max_requests)

    trace_lines: List[Dict] = []
    cumulative: List[int] = []
    for request in requests:
        msgs = request["messages"]
        # Token estimate over the full wire payload (tool blocks included).
        total_tokens = estimate_messages_tokens(msgs)
        # Unique cumulative prefix hashes (grows across turns).
        for m in msgs:
            for h in block_hashes(_message_wire_text(m), block_size):
                if h not in cumulative:
                    cumulative.append(h)
        trace_lines.append({
            "block_size": block_size,
            "hash_ids": list(cumulative),
            "input_length": max(1, total_tokens),
            "user_id": session_id,
            "messages": msgs,
        })
    return trace_lines


# ShareGPT speaker aliases (the format used by vLLM / LMCache benchmarks,
# carnice traces, CodexBench traces, OpenHands exports, ShareGPT_Vicuna, ...).
_SHAREGPT_ROLES = {
    "human": "user", "user": "user", "student": "user", "user1": "user",
    "gpt": "assistant", "chatgpt": "assistant", "bing": "assistant",
    "bard": "assistant", "assistant": "assistant", "model": "assistant",
    "system": "system",
}


def load_sharegpt_jsonl(path: str, session_id: int = 0,
                        block_size: int = 64, max_turns: int = 0) -> List[Dict]:
    """Load a ShareGPT/Hermes-style file (``conversations`` field).

    Handles the canonical ShareGPT shape used across the ecosystem::

        {"conversations": [{"from": "human"|"gpt"|"system"|..., "value": str}]}

    Speaker aliases follow vLLM's benchmark_serving mapping (human/user →
    user; gpt/chatgpt/bing/bard → assistant). When ``max_turns`` > 0 each
    conversation is also exported as *multiple* growing requests (turn 1,
    turns 1-2, ...) to reproduce prefix growth; otherwise the whole
    conversation is a single request.
    """
    out: List[Dict] = []
    role_map = _SHAREGPT_ROLES

    def _emit(msgs: List[Dict]):
        line = _sharegpt_line(msgs, block_size, session_id)
        if line is not None:
            out.append(line)

    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            convos = obj.get("conversations")
            if not isinstance(convos, list) or not convos:
                continue
            msgs: List[Dict] = []
            for turn in convos:
                role = role_map.get(turn.get("from", ""))
                if not role:
                    continue
                msgs.append({"role": role, "content": turn.get("value", "")})
            if not msgs or not any(m["role"] == "assistant" for m in msgs):
                continue  # no answer to replay
            if max_turns > 0:
                # Prefix-growth mode: one request per assistant turn, history
                # accumulated up to that turn (mirrors Claude Code conversion).
                for i, m in enumerate(msgs[: max_turns * 2]):
                    if m["role"] == "assistant":
                        _emit(msgs[: i + 1])
            else:
                _emit(msgs)
    return out


def _sharegpt_line(msgs: List[Dict], block_size: int, session_id: int) -> Optional[Dict]:
    cumulative: List[int] = []
    total_tokens = estimate_messages_tokens(msgs)
    for m in msgs:
        for h in block_hashes(_message_wire_text(m), block_size):
            if h not in cumulative:
                cumulative.append(h)
    return {
        "block_size": block_size,
        "hash_ids": list(cumulative),
        "input_length": max(1, total_tokens),
        "user_id": session_id,
        "messages": msgs,
    }


def load_openai_style_jsonl(path: str, session_id: int = 0,
                            block_size: int = 64) -> List[Dict]:
    """Load a flat OpenAI-style trace (each line has ``messages``)."""
    out: List[Dict] = []
    for line in open(path, encoding="utf-8-sig"):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        msgs = obj.get("messages")
        if not msgs:
            continue
        cumulative: List[int] = []
        total_tokens = estimate_messages_tokens(msgs)
        for m in msgs:
            for h in block_hashes(_message_wire_text(m), block_size):
                if h not in cumulative:
                    cumulative.append(h)
        out.append({
            "block_size": block_size,
            "hash_ids": list(cumulative),
            "input_length": max(1, total_tokens),
            "user_id": session_id,
            "messages": msgs,
        })
    return out


def detect_format(path: str) -> str:
    """Return 'claude' | 'openai' | 'unknown' for a trace file."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            first = None
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    first = json.loads(line)
                except json.JSONDecodeError:
                    return "unknown"
                break
    except OSError:
        return "unknown"
    if not isinstance(first, dict):
        return "unknown"
    if "messages" in first:
        return "openai"
    if "conversations" in first:
        return "sharegpt"
    # Claude Code sessions: any leading line with a string "type" field
    # (user/assistant/last-prompt/queue-operation/...). Conversion filters
    # to user/assistant turns.
    if isinstance(first.get("type"), str) and first["type"]:
        return "claude"
    return "unknown"


def convert_file(path: str, session_id: int = 0, block_size: int = 64,
                 max_requests: int = 0) -> List[Dict]:
    """Convert any supported trace file to ClawPerf flat trace lines."""
    fmt = detect_format(path)
    if fmt == "claude":
        return convert_claude_code_file(path, session_id=session_id,
                                        block_size=block_size, max_requests=max_requests)
    if fmt == "openai":
        return load_openai_style_jsonl(path, session_id=session_id, block_size=block_size)
    if fmt == "sharegpt":
        return load_sharegpt_jsonl(path, session_id=session_id, block_size=block_size,
                                   max_turns=max_requests)
    raise ValueError(f"Unsupported trace format for {path!r} (detected: {fmt!r})")


def convert_many(paths: List[str], block_size: int = 64,
                 max_requests: int = 0) -> List[Dict]:
    """Convert multiple files into one multi-session trace (per-file user_id)."""
    out: List[Dict] = []
    for i, p in enumerate(paths):
        out.extend(convert_file(p, session_id=i, block_size=block_size,
                                max_requests=max_requests))
    return out


def write_trace(trace_lines: List[Dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for line in trace_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    logger.info("Wrote %d trace lines to %s", len(trace_lines), path)
