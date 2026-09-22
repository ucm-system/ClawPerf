"""Tests for new features: context profiles, report, translators, config layering."""

from __future__ import annotations

import json
import os

import pytest

# ── Context profiles ─────────────────────────────────────────────────────────

class TestContextProfiles:
    def test_get_profile(self):
        from clawperf.context_profiles import get_profile
        p = get_profile("medium")
        assert p["system_prefix_tokens"] == 28000
        assert p["user_prefix_tokens"] == 10000
        assert p["input_tokens_per_turn"] == 5000

    def test_get_profile_case_insensitive(self):
        from clawperf.context_profiles import get_profile
        assert get_profile("FRESH")["system_prefix_tokens"] == 4000
        assert get_profile("Long")["system_prefix_tokens"] == 50000

    def test_get_profile_unknown(self):
        from clawperf.context_profiles import get_profile
        with pytest.raises(ValueError, match="Unknown context profile"):
            get_profile("nonexistent")

    def test_get_profile_returns_copy(self):
        from clawperf.context_profiles import get_profile
        p1 = get_profile("short")
        p1["system_prefix_tokens"] = 999
        p2 = get_profile("short")
        assert p2["system_prefix_tokens"] == 14000

    def test_resolve_suite_quick(self):
        from clawperf.context_profiles import resolve_suite
        scenarios = resolve_suite("quick")
        assert len(scenarios) == 3  # users [1,4,8] × 1 profile
        for num_users, profile_name, tokens in scenarios:
            assert profile_name == "fresh"
            assert num_users in (1, 4, 8)

    def test_resolve_suite_full_filtered(self):
        from clawperf.context_profiles import resolve_suite
        # With a 50K window, long/full/xl/xxl should be skipped.
        scenarios = resolve_suite("full", model_context_length=50000)
        for _, name, tokens in scenarios:
            total = tokens["system_prefix_tokens"] + tokens["user_prefix_tokens"] + tokens["input_tokens_per_turn"]
            assert total < 50000

    def test_list_profiles_ordered(self):
        from clawperf.context_profiles import PROFILE_ORDER, list_profiles
        assert list_profiles() == PROFILE_ORDER

    def test_list_suites(self):
        from clawperf.context_profiles import SUITES, list_suites
        assert set(list_suites()) == set(SUITES.keys())


# ── Config: profiles, env vars, YAML ──────────────────────────────────────────

class TestConfigProfiles:
    def test_profile_overrides_tokens(self):
        from clawperf.config import BenchmarkConfig
        c = BenchmarkConfig(mode="scenario", context_profile="long",
                            endpoint="http://x", model="m")
        assert c.system_prefix_tokens == 50000
        assert c.user_prefix_tokens == 18000
        assert c.input_tokens_per_turn == 7000

    def test_no_profile_uses_defaults(self):
        from clawperf.config import BenchmarkConfig
        c = BenchmarkConfig(mode="scenario", endpoint="http://x", model="m")
        assert c.system_prefix_tokens == 15000  # default


class TestEnvConfig:
    def test_env_var_loading(self, monkeypatch):
        monkeypatch.setenv("CLAWPERF_ENDPOINT", "http://from-env")
        monkeypatch.setenv("CLAWPERF_MAX_TURNS", "42")
        monkeypatch.setenv("CLAWPERF_VERBOSE", "true")
        from clawperf.config import load_env_config
        env = load_env_config()
        assert env.get("endpoint") == "http://from-env"
        assert env.get("max_turns") == 42
        assert env.get("verbose") is True

    def test_build_config_env_override(self, monkeypatch):
        monkeypatch.setenv("CLAWPERF_ENDPOINT", "http://env-endpoint")
        from clawperf.config import build_config
        c = build_config({"mode": "scenario"})
        assert c.endpoint == "http://env-endpoint"

    def test_build_config_cli_overrides_env(self, monkeypatch):
        monkeypatch.setenv("CLAWPERF_ENDPOINT", "http://env-endpoint")
        from clawperf.config import build_config
        c = build_config({"mode": "scenario", "endpoint": "http://cli-endpoint"})
        assert c.endpoint == "http://cli-endpoint"

    def test_build_config_yaml(self, tmp_path):
        yaml_content = "mode: scenario\nendpoint: http://yaml-endpoint\nmax_turns: 99\n"
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(yaml_content)
        from clawperf.config import build_config
        c = build_config({}, yaml_path=str(yaml_path))
        assert c.endpoint == "http://yaml-endpoint"
        assert c.max_turns == 99

    def test_build_config_cli_overrides_yaml(self, tmp_path):
        yaml_content = "endpoint: http://yaml-endpoint\nmax_turns: 99\n"
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(yaml_content)
        from clawperf.config import build_config
        c = build_config({"endpoint": "http://cli-endpoint"}, yaml_path=str(yaml_path))
        assert c.endpoint == "http://cli-endpoint"
        assert c.max_turns == 99  # from YAML, not overridden by CLI


# ── Translators ──────────────────────────────────────────────────────────────

class TestTranslators:
    def test_anthropic_text_to_openai(self):
        from clawperf.translators import anthropic_to_openai_message
        msg = {"role": "user", "content": [{"type": "text", "text": "hello"}]}
        oai = anthropic_to_openai_message(msg)
        assert oai["role"] == "user"
        assert oai["content"] == "hello"

    def test_anthropic_string_to_openai(self):
        from clawperf.translators import anthropic_to_openai_message
        msg = {"role": "user", "content": "hello world"}
        oai = anthropic_to_openai_message(msg)
        assert oai["content"] == "hello world"

    def test_anthropic_tool_use_to_openai(self):
        from clawperf.translators import anthropic_to_openai_message
        msg = {"role": "assistant", "content": [
            {"type": "text", "text": "Let me read that file."},
            {"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"path": "main.py"}},
        ]}
        oai = anthropic_to_openai_message(msg)
        assert oai["role"] == "assistant"
        assert "tool_calls" in oai
        assert oai["tool_calls"][0]["function"]["name"] == "read_file"
        assert json.loads(oai["tool_calls"][0]["function"]["arguments"]) == {"path": "main.py"}

    def test_anthropic_tool_result_to_openai(self):
        from clawperf.translators import anthropic_to_openai_message
        msg = {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "file contents here"},
        ]}
        oai = anthropic_to_openai_message(msg)
        assert oai["role"] == "tool"
        assert oai["tool_call_id"] == "call_1"
        assert oai["content"] == "file contents here"

    def test_openai_to_anthropic_text(self):
        from clawperf.translators import openai_to_anthropic_message
        msg = {"role": "user", "content": "hello"}
        ant = openai_to_anthropic_message(msg)
        assert ant["role"] == "user"
        assert ant["content"] == "hello"

    def test_openai_tool_call_to_anthropic(self):
        from clawperf.translators import openai_to_anthropic_message
        msg = {"role": "assistant", "content": "thinking...", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "x"}'}},
        ]}
        ant = openai_to_anthropic_message(msg)
        assert ant["role"] == "assistant"
        blocks = ant["content"]
        assert any(b["type"] == "text" for b in blocks)
        assert any(b["type"] == "tool_use" for b in blocks)
        tu = next(b for b in blocks if b["type"] == "tool_use")
        assert tu["name"] == "read_file"
        assert tu["input"] == {"path": "x"}

    def test_detect_api_type(self):
        from clawperf.translators import detect_api_type
        assert detect_api_type("https://api.anthropic.com/v1/messages") == "anthropic"
        assert detect_api_type("http://localhost:8000/v1/chat/completions") == "openai"
        assert detect_api_type("https://api.openai.com/v1") == "openai"

    def test_normalize_endpoint_openai(self):
        from clawperf.translators import normalize_endpoint
        assert normalize_endpoint("http://localhost:8000", "openai") == "http://localhost:8000/v1/chat/completions"
        assert normalize_endpoint("http://localhost:8000/v1", "openai") == "http://localhost:8000/v1/chat/completions"
        assert normalize_endpoint("http://localhost:8000/v1/chat/completions", "openai") == "http://localhost:8000/v1/chat/completions"

    def test_normalize_endpoint_anthropic(self):
        from clawperf.translators import normalize_endpoint
        assert normalize_endpoint("https://api.anthropic.com", "anthropic") == "https://api.anthropic.com/v1/messages"
        assert normalize_endpoint("https://api.anthropic.com/v1/messages", "anthropic") == "https://api.anthropic.com/v1/messages"

    def test_tool_schema_translation(self):
        from clawperf.translators import anthropic_tools_to_openai, openai_tools_to_anthropic
        anthropic_tools = [{"name": "read_file", "description": "Read a file",
                             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}}]
        oai_tools = anthropic_tools_to_openai(anthropic_tools)
        assert oai_tools[0]["type"] == "function"
        assert oai_tools[0]["function"]["name"] == "read_file"
        # Round-trip
        ant_tools = openai_tools_to_anthropic(oai_tools)
        assert ant_tools[0]["name"] == "read_file"
        assert ant_tools[0]["input_schema"]["properties"]["path"]["type"] == "string"

    def test_streaming_accumulator(self):
        from clawperf.translators import StreamingToolCallAccumulator
        acc = StreamingToolCallAccumulator()
        acc.feed([{"index": 0, "id": "call_1", "function": {"name": "read_file"}}])
        acc.feed([{"index": 0, "function": {"arguments": '{"path":'}}])
        acc.feed([{"index": 0, "function": {"arguments": '"main.py"}'}}])
        tc = acc.tool_calls
        assert len(tc) == 1
        assert tc[0]["id"] == "call_1"
        assert tc[0]["name"] == "read_file"
        assert json.loads(tc[0]["arguments"]) == {"path": "main.py"}

    def test_anthropic_messages_to_openai_list(self):
        from clawperf.translators import anthropic_messages_to_openai
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "hi"},
                {"type": "tool_use", "id": "c1", "name": "ls", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": "file1.py\nfile2.py"},
            ]},
        ]
        oai = anthropic_messages_to_openai(messages)
        assert len(oai) == 3
        assert oai[0]["role"] == "user"
        assert oai[1]["role"] == "assistant"
        assert "tool_calls" in oai[1]
        assert oai[2]["role"] == "tool"
        assert oai[2]["tool_call_id"] == "c1"


# ── Report generator ──────────────────────────────────────────────────────────

def _make_scenario_result(num_users=2, ttft_p50=300.0, thru=45.0):
    return {
        "config": {"model": "test", "endpoint": "http://x", "backend": "vllm",
                   "num_users": num_users, "max_turns": 10,
                   "system_prefix_tokens": 1000, "user_prefix_tokens": 500,
                   "input_tokens_per_turn": 500},
        "summary": {"mode": "scenario", "total_compactions": 0},
        "users": [
            {"user_id": i, "aggregate": {
                "ttft": {
                    "P50": ttft_p50 + i * 100, "avg": ttft_p50 + 50,
                    "min": ttft_p50, "max": ttft_p50 + 200, "N": 10,
                },
                "tpot": {"P50": 15.0},
                "e2e_latency": {"P50": 1500.0},
                "throughput_tok_s": thru - i * 5,
                "total_input_tokens": 10000, "total_output_tokens": 5000,
                "success_count": 10, "error_count": 0, "compaction_count": 0,
                "duration_s": 15.0,
            }}
            for i in range(num_users)
        ],
        "timing": {"setup_time_s": 2.0, "bench_time_s": 20.0},
    }


class TestReport:
    def test_verdict_good(self):
        from clawperf.report import compute_verdict
        r = _make_scenario_result(ttft_p50=500.0, thru=45.0)
        v = compute_verdict(r)
        assert v["overall"] == "GOOD"
        assert v["ttft_grade"] == "GOOD"
        assert v["toks_grade"] == "GOOD"

    def test_verdict_marginal(self):
        from clawperf.report import compute_verdict
        r = _make_scenario_result(ttft_p50=5000.0, thru=20.0)
        v = compute_verdict(r)
        assert v["overall"] == "MARGINAL"

    def test_verdict_poor(self):
        from clawperf.report import compute_verdict
        r = _make_scenario_result(ttft_p50=25000.0, thru=3.0)
        v = compute_verdict(r)
        assert v["overall"] == "POOR"

    def test_generate_report_markdown(self):
        from clawperf.report import generate_report
        r = _make_scenario_result()
        md = generate_report(r)
        assert "# ClawPerf Benchmark Report" in md
        assert "Verdict" in md
        assert "## Summary" in md
        assert "## Methodology" in md

    def test_generate_report_to_file(self, tmp_path):
        from clawperf.report import generate_report
        r = _make_scenario_result()
        path = str(tmp_path / "report.md")
        generate_report(r, output_path=path)
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            md = f.read()
        assert "# ClawPerf Benchmark Report" in md

    def test_generate_comparison(self):
        from clawperf.report import generate_comparison
        r_a = _make_scenario_result(ttft_p50=300.0, thru=45.0)
        r_b = _make_scenario_result(ttft_p50=800.0, thru=25.0)
        md = generate_comparison(r_a, r_b, "Before", "After")
        assert "# ClawPerf Comparison Report" in md
        assert "Before" in md
        assert "After" in md
        assert "Delta" in md

    def test_hitrate_verdict(self):
        from clawperf.report import compute_verdict
        # measured 0.70 vs target 0.80: 0.70 >= 0.64 (=0.80*0.80) but < 0.76 (=0.80*0.95) → MARGINAL
        r = {
            "summary": {"mode": "hitrate", "target_hit_rate": 0.8, "measured_hit_rate": 0.70,
                        "ttft": {"P50": 500.0}},
            "config": {}, "timing": {},
        }
        v = compute_verdict(r)
        assert v["overall"] == "MARGINAL"
        assert v["measured_hit_rate"] == 0.70

    def test_slo_verdict(self):
        from clawperf.report import compute_verdict
        r = {
            "summary": {"mode": "slo", "max_sustained_users": 16, "slo": "TTFT P99<=1000",
                        "steps_tested": 4},
            "capacity_curve": [{"n_users": 16, "slo_met": True}],
            "config": {}, "timing": {},
        }
        v = compute_verdict(r)
        assert v["overall"] == "GOOD"
        assert v["max_sustained_users"] == 16

    def test_agent_verdict(self):
        from clawperf.report import compute_verdict
        r = {
            "summary": {"mode": "agent", "tasks_run": 4, "tasks_finished": 3,
                        "ttft": {"P50": 400.0}},
            "tasks": [], "config": {}, "timing": {},
        }
        v = compute_verdict(r)
        assert v["overall"] == "GOOD"
        assert v["finish_rate"] == 0.75

    def test_load_result(self, tmp_path):
        from clawperf.report import load_result
        r = _make_scenario_result()
        path = str(tmp_path / "result.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(r, f)
        loaded = load_result(path)
        assert loaded["summary"]["mode"] == "scenario"


# ── Config validation for record/replay ──────────────────────────────────────

class TestConfigValidation:
    def test_record_requires_upstream(self):
        from clawperf.config import BenchmarkConfig
        c = BenchmarkConfig(mode="record")
        problems = c.validate()
        assert any("upstream-endpoint" in p for p in problems)

    def test_replay_requires_recording(self):
        from clawperf.config import BenchmarkConfig
        c = BenchmarkConfig(mode="replay", recording="")
        problems = c.validate()
        assert any("recording" in p for p in problems)

    def test_replay_valid(self):
        from clawperf.config import BenchmarkConfig
        c = BenchmarkConfig(mode="replay", recording="test.jsonl",
                            endpoint="http://x", model="m")
        assert c.validate() == []

    def test_replay_invalid_history_mode(self):
        from clawperf.config import BenchmarkConfig
        c = BenchmarkConfig(mode="replay", recording="test.jsonl",
                            endpoint="http://x", model="m", history_mode="invalid")
        problems = c.validate()
        assert any("history_mode" in p for p in problems)

    def test_max_consecutive_failures_negative(self):
        from clawperf.config import BenchmarkConfig
        c = BenchmarkConfig(mode="scenario", endpoint="http://x", model="m",
                            max_consecutive_failures=-1)
        problems = c.validate()
        assert any("max_consecutive_failures" in p for p in problems)


# ── Early abort tracking ──────────────────────────────────────────────────────

class TestEarlyAbort:
    def test_consecutive_failures_reset_on_success(self):
        from clawperf.config import BenchmarkConfig
        from clawperf.runner import BenchmarkRunner
        c = BenchmarkConfig(mode="scenario", endpoint="http://x", model="m",
                            max_consecutive_failures=3)
        runner = BenchmarkRunner(c)
        assert runner._consecutive_failures == 0
        # Simulate failures
        runner._advance_progress({"success": False})
        assert runner._consecutive_failures == 1
        runner._advance_progress({"success": False})
        assert runner._consecutive_failures == 2
        # Success resets
        runner._advance_progress({"success": True})
        assert runner._consecutive_failures == 0

    def test_abort_triggers_at_threshold(self):
        from clawperf.config import BenchmarkConfig
        from clawperf.runner import BenchmarkRunner
        c = BenchmarkConfig(mode="scenario", endpoint="http://x", model="m",
                            max_consecutive_failures=3)
        runner = BenchmarkRunner(c)
        runner._advance_progress({"success": False})
        runner._advance_progress({"success": False})
        assert not runner._shutdown
        runner._advance_progress({"success": False})
        assert runner._shutdown
        assert runner._abort_event.is_set()

    def test_abort_disabled_by_default(self):
        from clawperf.config import BenchmarkConfig
        from clawperf.runner import BenchmarkRunner
        c = BenchmarkConfig(mode="scenario", endpoint="http://x", model="m")
        runner = BenchmarkRunner(c)
        for _ in range(100):
            runner._advance_progress({"success": False})
        assert not runner._shutdown  # no abort without threshold


# ── Has all failures (CI exit code) ───────────────────────────────────────────

class TestHasAllFailures:
    def test_all_failures_true(self):
        from clawperf.config import BenchmarkConfig
        from clawperf.runner import BenchmarkRunner
        c = BenchmarkConfig(mode="scenario", endpoint="http://x", model="m")
        runner = BenchmarkRunner(c)
        runner._turn_records = [{"success": False}, {"success": False}]
        assert runner._has_all_failures()

    def test_mixed_failures_false(self):
        from clawperf.config import BenchmarkConfig
        from clawperf.runner import BenchmarkRunner
        c = BenchmarkConfig(mode="scenario", endpoint="http://x", model="m")
        runner = BenchmarkRunner(c)
        runner._turn_records = [{"success": True}, {"success": False}]
        assert not runner._has_all_failures()

    def test_empty_records_true(self):
        from clawperf.config import BenchmarkConfig
        from clawperf.runner import BenchmarkRunner
        c = BenchmarkConfig(mode="scenario", endpoint="http://x", model="m")
        runner = BenchmarkRunner(c)
        assert runner._has_all_failures()


# ── Reasoning token fields in agent ───────────────────────────────────────────

class TestReasoningTokens:
    def test_turn_result_has_reasoning_fields(self):
        from clawperf.agent import TurnResult
        tr = TurnResult(
            ttft_ms=500.0, e2e_ms=2000.0, input_tokens=1000, output_tokens=500,
            content="hello", tool_calls=[], finish_reason="stop",
        )
        assert tr.ttft_thinking_ms is None
        assert tr.ttft_visible_ms is None
        assert tr.thinking_tokens == 0
        assert tr.thinking_overhead_ms == 0.0

    def test_agent_turn_record_has_reasoning_fields(self):
        from clawperf.agent import AgentTurnRecord
        r = AgentTurnRecord(
            turn=1, ttft_ms=500.0, e2e_ms=2000.0, input_tokens=1000,
            output_tokens=500, tool_calls=1, tool_time_ms=100.0,
            finish_reason="stop",
        )
        assert r.ttft_thinking_ms is None
        assert r.thinking_tokens == 0

    def test_agent_result_to_dict_includes_reasoning(self):
        from clawperf.agent import AgentRunResult, AgentTurnRecord
        from clawperf.runner import BenchmarkRunner
        r = AgentRunResult(
            task_id=0, steps=1, finished=True, total_wall_s=2.0,
            total_input_tokens=100, total_output_tokens=50,
            turns=[AgentTurnRecord(
                turn=1, ttft_ms=500.0, e2e_ms=2000.0, input_tokens=100,
                output_tokens=50, tool_calls=0, tool_time_ms=0.0,
                finish_reason="stop",
                ttft_thinking_ms=300.0, ttft_visible_ms=500.0,
                thinking_tokens=42, thinking_overhead_ms=200.0,
            )],
        )
        d = BenchmarkRunner._agent_result_to_dict(r)
        turn = d["turns"][0]
        assert turn["ttft_thinking_ms"] == 300.0
        assert turn["ttft_visible_ms"] == 500.0
        assert turn["thinking_tokens"] == 42
        assert turn["thinking_overhead_ms"] == 200.0
