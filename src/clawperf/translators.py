"""Bidirectional Anthropic ↔ OpenAI API translation.

Converts messages, tool schemas, and streaming SSE events between the two
API shapes so that:
- The **recorder** can capture a real Anthropic-agent session and store it
  in OpenAI chat-completions format (replayable against any endpoint).
- The **player** can replay OpenAI-format recordings against an Anthropic
  endpoint, or vice versa, by translating on the fly.

This is NOT a full API reimplementation — it covers the message/tool shapes
that coding agents actually use (text, tool_use, tool_result, thinking).

Inspired by agentic-swarm-bench's ``proxy/translators.py``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

# ── Message translation: Anthropic → OpenAI ────────────────────────────────────


def anthropic_to_openai_message(msg: Dict) -> Dict:
    """Convert one Anthropic message to OpenAI chat-completions shape.

    Anthropic message structure:
        {"role": "user"|"assistant", "content": str | [content_block, ...]}
    Content block types: {"type": "text", "text": "..."},
                         {"type": "tool_use", "id", "name", "input"},
                         {"type": "tool_result", "tool_use_id", "content"},
                         {"type": "thinking", "thinking": "..."}

    OpenAI structure:
        {"role": "user"|"assistant"|"tool",
         "content": str | None,
         "tool_calls": [{"id", "type": "function",
                         "function": {"name", "arguments": json_str}}],
         "tool_call_id": str}
    """
    role = msg.get("role", "user")
    content = msg.get("content")

    # Simple string content — direct mapping.
    if isinstance(content, str):
        return {"role": role, "content": content}

    if not isinstance(content, list):
        return {"role": role, "content": str(content) if content else ""}

    # Composite content — extract text, tool_calls, tool_results.
    text_parts: List[str] = []
    tool_calls: List[Dict] = []
    tool_results: List[Dict] = []
    thinking_parts: List[str] = []

    for block in content:
        btype = block.get("type", "text")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append({
                "id": block.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {})),
                },
            })
        elif btype == "tool_result":
            # Anthropic nests tool_result inside a user message; OpenAI uses
            # a separate "tool" role message with tool_call_id.
            result_content = block.get("content", "")
            if isinstance(result_content, list):
                result_content = " ".join(
                    b.get("text", "") for b in result_content if b.get("type") == "text"
                )
            tool_results.append({
                "role": "tool",
                "tool_call_id": block.get("tool_use_id", ""),
                "content": str(result_content),
            })
        elif btype == "thinking":
            thinking_parts.append(block.get("thinking", ""))

    result: Dict[str, Any] = {"role": role}

    # Assistant turns may carry both text and tool_calls.
    if role == "assistant":
        result["content"] = "\n".join(text_parts) if text_parts else (None if tool_calls else "")
        if tool_calls:
            result["tool_calls"] = tool_calls
    # User turns with tool_results become separate "tool" messages.
    elif tool_results:
        # If there's also text, keep it as a user message; tool results go
        # to separate messages (caller handles splitting).
        if text_parts:
            result["content"] = "\n".join(text_parts)
            result["_tool_results"] = tool_results  # caller extracts these
        else:
            # Pure tool result — return the first one; caller handles multiple.
            return tool_results[0] if len(tool_results) == 1 else {"_tool_results": tool_results}
    else:
        result["content"] = "\n".join(text_parts) if text_parts else ""

    return result


def anthropic_messages_to_openai(messages: List[Dict]) -> List[Dict]:
    """Convert a full Anthropic message list to OpenAI format."""
    out: List[Dict] = []
    for msg in messages:
        converted = anthropic_to_openai_message(msg)
        if "_tool_results" in converted:
            # Split: keep the user text message, then append tool result messages.
            tool_results = converted.pop("_tool_results")
            out.append(converted)
            out.extend(tool_results)
        elif isinstance(converted, list):
            out.extend(converted)
        else:
            out.append(converted)
    return out


# ── Message translation: OpenAI → Anthropic ──────────────────────────────────


def openai_to_anthropic_message(msg: Dict) -> Dict:
    """Convert one OpenAI message to Anthropic shape.

    OpenAI → Anthropic block mapping:
        text content         → {"type": "text", "text": "..."}
        tool_calls           → {"type": "tool_use", "id", "name", "input"}
        role="tool" message  → {"type": "tool_result", "tool_use_id", "content"}
    """
    role = msg.get("role", "user")

    if role == "tool":
        return {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": msg.get("content", ""),
            }],
        }

    if role == "assistant":
        blocks: List[Dict] = []
        if msg.get("content"):
            blocks.append({"type": "text", "text": msg["content"]})
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            try:
                inp = json.loads(fn.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                inp = {}
            blocks.append({
                "type": "tool_use",
                "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                "name": fn.get("name", ""),
                "input": inp,
            })
        return {"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]}

    # User message
    return {"role": "user", "content": msg.get("content", "")}


def openai_messages_to_anthropic(messages: List[Dict]) -> List[Dict]:
    """Convert a full OpenAI message list to Anthropic format.

    Consecutive user messages (from tool_result splits) are merged into one
    message with multiple content blocks, matching Anthropic's API contract.
    """
    raw = [openai_to_anthropic_message(m) for m in messages]
    merged: List[Dict] = []
    for msg in raw:
        if (merged and msg["role"] == "user" and merged[-1]["role"] == "user"
                and isinstance(msg["content"], list) and isinstance(merged[-1]["content"], list)):
            merged[-1]["content"].extend(msg["content"])
        else:
            merged.append(msg)
    return merged


# ── Tool schema translation ───────────────────────────────────────────────────


def anthropic_tools_to_openai(tools: List[Dict]) -> List[Dict]:
    """Convert Anthropic tool definitions to OpenAI function-calling shape.

    Anthropic: {"name", "description", "input_schema": {...}}
    OpenAI:    {"type": "function", "function": {"name", "description", "parameters": {...}}}
    """
    out = []
    for t in tools:
        out.append({
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


def openai_tools_to_anthropic(tools: List[Dict]) -> List[Dict]:
    """Convert OpenAI function tools to Anthropic tool definitions."""
    out = []
    for t in tools:
        fn = t.get("function", t)
        out.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return out


# ── Streaming SSE event translation ────────────────────────────────────────────

class StreamingToolCallAccumulator:
    """Accumulate fragmented OpenAI tool_call deltas into complete calls.

    OpenAI streams tool calls as fragments:
        delta.tool_calls[0].id = "call_abc"
        delta.tool_calls[0].function.name = "read_file"
        delta.tool_calls[0].function.arguments = "{\"pa"   (partial JSON)
        delta.tool_calls[0].function.arguments = "th\":\"x\"}"

    This accumulator reconstructs the full tool calls for re-emission as
    Anthropic ``input_json_delta`` events.
    """

    def __init__(self):
        self._slots: Dict[int, Dict[str, Any]] = {}

    def feed(self, delta_tool_calls: List[Dict]) -> None:
        for tc in delta_tool_calls:
            idx = tc.get("index", 0)
            slot = self._slots.setdefault(idx, {"id": "", "name": "", "args": ""})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function", {})
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]

    @property
    def tool_calls(self) -> List[Dict]:
        return [
            {"id": s["id"] or f"call_{i}", "name": s["name"], "arguments": s["args"]}
            for i, s in sorted(self._slots.items())
        ]


def openai_chunk_to_anthropic_events(
    chunk: Dict, msg_id: str, model: str,
    accumulator: StreamingToolCallAccumulator,
    started: bool,
) -> tuple:
    """Translate one OpenAI streaming chunk into Anthropic SSE events.

    Returns (events_list, started_flag). The caller emits these as SSE
    ``event: ...\\ndata: ...`` pairs.
    """
    events: List[Dict] = []
    new_started = started

    choices = chunk.get("choices", [])
    if not choices:
        # Usage-only chunk (end of stream).
        usage = chunk.get("usage")
        if usage:
            events.append({
                "event": "message_delta",
                "data": {
                    "type": "message_delta",
                    "usage": {
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                    },
                    "stop_reason": "end_turn",
                },
            })
            events.append({"event": "message_stop", "data": {"type": "message_stop"}})
        return events, new_started

    choice = choices[0]
    delta = choice.get("delta", {})

    if not started:
        events.append({
            "event": "message_start",
            "data": {
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
            },
        })
        new_started = True

    # Text content
    if delta.get("content"):
        events.append({
            "event": "content_block_delta",
            "data": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": delta["content"]},
            },
        })

    # Tool calls — accumulate and emit as input_json_delta
    if delta.get("tool_calls"):
        accumulator.feed(delta["tool_calls"])
        for tc in delta["tool_calls"]:
            idx = tc.get("index", 0)
            fn = tc.get("function", {})
            if fn.get("name"):
                events.append({
                    "event": "content_block_start",
                    "data": {
                        "type": "content_block_start",
                        "index": idx,
                        "content_block": {"type": "tool_use", "id": tc.get("id", ""), "name": fn["name"], "input": {}},
                    },
                })
            if fn.get("arguments"):
                events.append({
                    "event": "content_block_delta",
                    "data": {
                        "type": "content_block_delta",
                        "index": idx,
                        "delta": {"type": "input_json_delta", "partial_json": fn["arguments"]},
                    },
                })

    # Finish reason
    if choice.get("finish_reason"):
        stop_reason = "end_turn"
        if choice["finish_reason"] == "tool_calls":
            stop_reason = "tool_use"
        events.append({
            "event": "message_delta",
            "data": {"type": "message_delta", "delta": {"stop_reason": stop_reason}},
        })

    return events, new_started


def anthropic_event_to_openai_chunk(event: Dict, model: str, msg_id: str) -> Optional[Dict]:
    """Translate one Anthropic SSE event into an OpenAI streaming chunk.

    Returns None for events that don't map to OpenAI chunks (e.g. message_start).
    """
    etype = event.get("event", "")
    data = event.get("data", {})

    if etype == "message_start":
        return None  # no OpenAI equivalent; the first content chunk starts the stream

    if etype == "content_block_delta":
        delta = data.get("delta", {})
        dtype = delta.get("type", "")
        if dtype == "text_delta":
            return {
                "id": msg_id,
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": {"content": delta.get("text", "")}, "finish_reason": None}],
            }
        if dtype == "input_json_delta":
            # Partial tool call arguments — emit as tool_calls delta.
            idx = data.get("index", 0)
            return {
                "id": msg_id,
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": {
                    "tool_calls": [{"index": idx, "function": {"arguments": delta.get("partial_json", "")}}],
                }, "finish_reason": None}],
            }

    if etype == "content_block_start":
        block = data.get("content_block", {})
        if block.get("type") == "tool_use":
            idx = data.get("index", 0)
            return {
                "id": msg_id,
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": {
                    "tool_calls": [{"index": idx, "id": block.get("id", ""),
                                    "type": "function",
                                    "function": {"name": block.get("name", "")}}],
                }, "finish_reason": None}],
            }

    if etype == "message_delta":
        stop_reason = data.get("delta", {}).get("stop_reason")
        if stop_reason:
            finish = "tool_calls" if stop_reason == "tool_use" else "stop"
            return {
                "id": msg_id,
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            }

    if etype == "message_stop":
        return None  # stream ends naturally

    return None


# ── Endpoint/URL helpers ──────────────────────────────────────────────────────

def detect_api_type(endpoint: str) -> str:
    """Auto-detect whether an endpoint is OpenAI or Anthropic based on URL."""
    url = endpoint.lower()
    if "anthropic.com" in url or "/v1/messages" in url:
        return "anthropic"
    return "openai"


def normalize_endpoint(endpoint: str, api_type: str = "openai") -> str:
    """Ensure the endpoint URL has the right path suffix.

    OpenAI:    .../v1/chat/completions
    Anthropic: .../v1/messages
    """
    endpoint = endpoint.rstrip("/")
    if api_type == "anthropic":
        if not endpoint.endswith("/v1/messages"):
            if endpoint.endswith("/v1"):
                endpoint += "/messages"
            elif "/v1/messages" not in endpoint:
                endpoint += "/v1/messages"
    else:
        if not endpoint.endswith("/chat/completions"):
            if endpoint.endswith("/v1"):
                endpoint += "/chat/completions"
            elif "/chat/completions" not in endpoint:
                endpoint += "/v1/chat/completions"
    return endpoint
