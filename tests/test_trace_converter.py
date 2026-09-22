"""Tests for the external trace converter (trace_converter.py)."""

from __future__ import annotations

import json

import pytest


def _write_jsonl(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


# ── Claude Code format ────────────────────────────────────────────────────────

class TestClaudeConverter:
    def _make_session(self, n_turns=3):
        lines = [
            {"type": "last-prompt", "leafUuid": "x1", "sessionId": "s1"},
            {"type": "mode", "mode": "normal", "sessionId": "s1"},
            {"type": "user", "message": {"role": "user", "content": "Fix the bug in parser.py"}},
        ]
        for i in range(n_turns):
            lines.append({"type": "assistant", "message": {
                "role": "assistant", "content": [
                    {"type": "text", "text": f"Looking at the code (step {i})..."},
                    {"type": "tool_use", "id": f"t{i}", "name": "read_file",
                     "input": {"path": "parser.py"}},
                ]}})
            lines.append({"type": "user", "message": {
                "role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"t{i}",
                     "content": f"content of parser.py line {i}"},
                ]}})
        return lines

    def test_convert_claude_file(self, tmp_path):
        from clawperf.trace_converter import convert_file
        path = tmp_path / "session.jsonl"
        _write_jsonl(path, self._make_session())
        lines = convert_file(str(path), session_id=0)
        assert len(lines) == 3  # one request per assistant turn
        assert all(line["user_id"] == 0 for line in lines)
        # Growing cumulative prefix: later turns have more hash_ids.
        assert len(lines[0]["hash_ids"]) < len(lines[-1]["hash_ids"])
        # Messages carry the tool-use assistant turn.
        assert lines[0]["messages"][1]["role"] == "assistant"
        assert "tool_calls" in lines[0]["messages"][1]

    def test_growing_input_length(self, tmp_path):
        from clawperf.trace_converter import convert_file
        path = tmp_path / "session.jsonl"
        _write_jsonl(path, self._make_session())
        lines = convert_file(str(path))
        lens = [line["input_length"] for line in lines]
        assert lens == sorted(lens)  # later turns have longer context

    def test_multi_session(self, tmp_path):
        from clawperf.trace_converter import convert_many
        p1 = tmp_path / "a.jsonl"
        p2 = tmp_path / "b.jsonl"
        _write_jsonl(p1, self._make_session(2))
        _write_jsonl(p2, self._make_session(1))
        lines = convert_many([str(p1), str(p2)])
        assert len(lines) == 3
        assert {line["user_id"] for line in lines} == {0, 1}

    def test_max_requests_cap(self, tmp_path):
        from clawperf.trace_converter import convert_file
        path = tmp_path / "session.jsonl"
        _write_jsonl(path, self._make_session(5))
        lines = convert_file(str(path), max_requests=2)
        assert len(lines) == 2  # last 2 requests kept

    def test_meta_lines_skipped(self, tmp_path):
        from clawperf.trace_converter import convert_file
        lines = [
            {"type": "queue-operation", "queue": "plan"},
            {"type": "permission-mode", "permissionMode": "bypassPermissions"},
            {"type": "user", "message": {"role": "user", "content": "hi"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "hello"}},
        ]
        path = tmp_path / "s.jsonl"
        _write_jsonl(path, lines)
        out = convert_file(str(path))
        assert len(out) == 1  # only the assistant turn


# ── Carnice (ShareGPT) format ─────────────────────────────────────────────────

class TestCarniceConverter:
    def test_convert_sharegpt(self, tmp_path):
        from clawperf.trace_converter import convert_file, detect_format
        line = {
            "prompt_index": 0,
            "conversations": [
                {"from": "system", "value": "You are a coding agent."},
                {"from": "human", "value": "Write a test for calc.py"},
                {"from": "gpt", "value": "Here's the test.\n\n```python\n...\n```"},
            ],
            "metadata": {},
        }
        path = tmp_path / "sharegpt.jsonl"
        _write_jsonl(path, [line])
        assert detect_format(str(path)) == "sharegpt"
        out = convert_file(str(path))
        assert len(out) == 1
        msgs = out[0]["messages"]
        assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
        assert out[0]["input_length"] > 0

    def test_sharegpt_speaker_aliases(self, tmp_path):
        """vLLM/LMCache canonical aliases: human/user→user, gpt/chatgpt/bing/bard→assistant."""
        from clawperf.trace_converter import convert_file
        line = {"conversations": [
            {"from": "user", "value": "hi"},
            {"from": "chatgpt", "value": "hello!"},
            {"from": "human", "value": "again"},
            {"from": "bing", "value": "sure"},
        ]}
        path = tmp_path / "aliases.jsonl"
        _write_jsonl(path, [line])
        out = convert_file(str(path), max_requests=0)  # single request
        assert [m["role"] for m in out[0]["messages"]] == ["user", "assistant", "user", "assistant"]

    def test_sharegpt_prefix_growth(self, tmp_path):
        """max_turns > 0 → one growing request per assistant turn."""
        from clawperf.trace_converter import convert_file
        line = {"conversations": [
            {"from": "human", "value": "q1"},
            {"from": "gpt", "value": "a1"},
            {"from": "human", "value": "q2"},
            {"from": "gpt", "value": "a2"},
            {"from": "human", "value": "q3"},
            {"from": "gpt", "value": "a3"},
        ]}
        path = tmp_path / "growth.jsonl"
        _write_jsonl(path, [line])
        out = convert_file(str(path), max_requests=3)
        assert len(out) == 3
        assert len(out[0]["messages"]) == 2
        assert len(out[2]["messages"]) == 6
        # Cumulative prefix grows monotonically.
        assert len(out[0]["hash_ids"]) < len(out[2]["hash_ids"])

    def test_unknown_role_skipped(self, tmp_path):
        from clawperf.trace_converter import convert_file
        # Unknown speaker is dropped; conversation without any assistant
        # reply is skipped entirely (nothing to replay).
        line = {"conversations": [
            {"from": "human", "value": "hello"},
            {"from": "bogus", "value": "ignored"},
            {"from": "gpt", "value": "ok"},
        ]}
        path = tmp_path / "c.jl"
        _write_jsonl(path, [line])
        out = convert_file(str(path))
        assert [m["role"] for m in out[0]["messages"]] == ["user", "assistant"]

        line2 = {"conversations": [
            {"from": "human", "value": "no reply"},
            {"from": "bogus", "value": "ignored"},
        ]}
        path2 = tmp_path / "noanswer.jl"
        _write_jsonl(path2, [line2])
        assert convert_file(str(path2)) == []


# ── OpenAI flat format ────────────────────────────────────────────────────────

class TestOpenAIConverter:
    def test_convert_openai(self, tmp_path):
        from clawperf.trace_converter import convert_file, detect_format
        line = {"messages": [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "hello"},
        ]}
        path = tmp_path / "o.jsonl"
        _write_jsonl(path, [line])
        assert detect_format(str(path)) == "openai"
        out = convert_file(str(path))
        assert len(out) == 1
        assert out[0]["messages"][1]["role"] == "user"

    def test_unknown_format(self, tmp_path):
        from clawperf.trace_converter import convert_file
        path = tmp_path / "x.jsonl"
        _write_jsonl(path, [{"foo": "bar", "count": 1}])
        with pytest.raises(ValueError, match="Unsupported trace format"):
            convert_file(str(path))


# ── Hash helpers ──────────────────────────────────────────────────────────────

class TestHashes:
    def test_block_hashes_deterministic(self):
        from clawperf.trace_converter import block_hashes
        h1 = block_hashes("same text" * 100)
        h2 = block_hashes("same text" * 100)
        assert h1 == h2
        assert len(h1) >= 1

    def test_block_hashes_differs(self):
        from clawperf.trace_converter import block_hashes
        assert block_hashes("aaaa") != block_hashes("bbbb")

    def test_text_len(self):
        from clawperf.trace_converter import text_len
        assert text_len("abcd") == 1
        assert text_len("") == 1  # never zero
