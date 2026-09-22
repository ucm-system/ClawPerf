"""Regression tests for Markdown report table/row content.

Catches the P1/P2 bugs where summary table rows were truncated by ternary
operator precedence and TTFT rows leaked across modes.
"""

from __future__ import annotations


def _scenario_result(num_users=2, ttft_p50=300.0, thru=45.0):
    return {
        "config": {"model": "test", "endpoint": "http://x", "backend": "vllm",
                   "num_users": num_users, "max_turns": 10,
                   "system_prefix_tokens": 1000, "user_prefix_tokens": 500,
                   "input_tokens_per_turn": 500, "output_tokens_per_turn": 100},
        "summary": {"mode": "scenario", "total_compactions": 0},
        "users": [
            {"user_id": i, "aggregate": {
                "ttft": {"P50": ttft_p50 + i * 100},
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


def _slo_result():
    return {
        "config": {"model": "t", "endpoint": "http://x", "backend": "vllm"},
        "summary": {"mode": "slo", "max_sustained_users": 3,
                    "slo": "TTFT P99<=1500"},
        "capacity_curve": [
            {"n_users": 1, "p_ttft_ms": 262.5, "p_tpot_ms": 8.22,
             "error_rate": 0.0, "slo_met": True},
            {"n_users": 2, "p_ttft_ms": 241.2, "p_tpot_ms": 8.69,
             "error_rate": 0.0, "slo_met": True},
            {"n_users": 4, "p_ttft_ms": 2224.8, "p_tpot_ms": 16.42,
             "error_rate": 0.0, "slo_met": False},
        ],
        "timing": {"setup_time_s": 1.0, "bench_time_s": 30.0},
    }


def _hitrate_result():
    return {
        "config": {"model": "t", "endpoint": "http://x", "backend": "vllm"},
        "summary": {"mode": "hitrate", "num_requests": 40,
                    "success_count": 40, "error_count": 0,
                    "target_hit_rate": 0.50, "measured_hit_rate": 0.499,
                    "ttft": {"P50": 149.0}, "e2e_latency": {"P50": 450.0},
                    "tpot": {"P50": 2.0}},
        "timing": {"setup_time_s": 1.0, "bench_time_s": 5.0},
    }


class TestReportRows:
    def test_scenario_rows_complete(self):
        """Every scenario summary row keeps its trailing columns."""
        from clawperf.report import generate_report
        md = generate_report(_scenario_result())
        # Only the Summary table's user rows (exclude the concurrency-scaling
        # table which also has "| 1 |" rows).
        summary_section = md.split("## Summary")[1].split("## TTFT Scaling")[0]
        data_rows = [line for line in summary_section.splitlines()
                     if line.startswith("| 0 ") or line.startswith("| 1 ")]
        assert data_rows, "user rows missing"
        for row in data_rows:
            cells = [c.strip() for c in row.strip("|").split("|")]
            assert len(cells) == 10, f"row truncated: {row!r}"
            # E2E, tok/s, comp, succ, fail must all be present.
            assert "1500" in cells[5], f"E2E column missing: {row!r}"
            assert cells[6] == "45.0" or cells[6] == "40.0", f"tok/s missing: {row!r}"

    def test_scenario_ttft_not_labeled_replay(self):
        """Scenario reports must NOT contain 'Real replay TTFT' rows."""
        from clawperf.report import generate_report
        md = generate_report(_scenario_result())
        assert "Real replay TTFT" not in md
        assert "real replay" not in md.lower()

    def test_verdict_single_ttft_row(self):
        """Exactly one TTFT row in the verdict section."""
        from clawperf.report import generate_report
        md = generate_report(_scenario_result())
        verdict_section = md.split("## Key Findings")[0]
        ttft_rows = [line for line in verdict_section.splitlines() if "TTFT" in line]
        assert len(ttft_rows) == 1, f"expected 1 TTFT row, got {ttft_rows}"

    def test_slo_rows_complete(self):
        """SLO capacity rows keep Error/SLO columns."""
        from clawperf.report import generate_report
        md = generate_report(_slo_result())
        rows = [line for line in md.splitlines()
                if line.startswith("| 1 ") or line.startswith("| 2 ") or line.startswith("| 4 ")]
        assert rows, "capacity rows missing"
        for row in rows:
            cells = [c.strip() for c in row.strip("|").split("|")]
            assert len(cells) == 5, f"row truncated: {row!r}"
            assert "0.0%" in cells[3], f"error column missing: {row!r}"

    def test_hitrate_real_numbers(self):
        """Hitrate report shows the measured rate and percentiles."""
        from clawperf.report import generate_report
        md = generate_report(_hitrate_result())
        assert "49.9%" in md  # measured hit rate
        assert "149ms" in md  # TTFT P50

    def test_trace_report_replay_row_labeled(self):
        """Trace reports DO label replay TTFT and don't duplicate it."""
        from clawperf.report import generate_report
        result = {
            "config": {"model": "t", "endpoint": "http://x", "backend": "vllm"},
            "summary": {
                "mode": "trace", "hit_rate": 0.63, "ceiling": 0.63, "speedup": 2.7,
                "request_count": 10, "total_input_tokens": 1000,
                "unique_blocks": 20, "policy": "lru",
                "replay": {"success_count": 9, "error_count": 1,
                           "total_input_tokens": 800, "total_output_tokens": 900,
                           "ttft_p50_ms": 73.5, "ttft_p95_ms": 137.0,
                           "decode_tok_s": 113.7, "itl_p50_ms": 8.8},
            },
            "timing": {"setup_time_s": 0.1, "bench_time_s": 21.0},
        }
        md = generate_report(result)
        assert md.count("Real replay TTFT (P50)") == 1
        assert "74ms" in md  # _fmt_ms(73.5) rounds to 74ms

    def test_findings_no_ttft_duplication_trace(self):
        """Trace Key Findings must not duplicate the TTFT line."""
        from clawperf.report import generate_report
        result = {
            "config": {"model": "t", "endpoint": "http://x", "backend": "vllm"},
            "summary": {"mode": "trace", "hit_rate": 0.5, "ceiling": 0.6,
                        "speedup": 2.0, "request_count": 5,
                        "replay": {"ttft_p50_ms": 80.0, "decode_tok_s": 100.0}},
            "timing": {"setup_time_s": 0.1, "bench_time_s": 5.0},
        }
        md = generate_report(result)
        findings = md.split("## Key Findings")[1].split("## Summary")[0]
        ttft_lines = [line for line in findings.splitlines() if "TTFT" in line]
        assert len(ttft_lines) == 1, f"duplicate TTFT findings: {ttft_lines}"

    def test_ascii_chart_1based_label(self):
        """TTFT scaling chart uses 1-based user counts."""
        from clawperf.report import generate_report
        md = generate_report(_scenario_result())
        assert "1 user(s)" in md
        assert "2 user(s)" in md
        assert "0 users" not in md


class TestCompareRows:
    def test_compare_hit_rate_row_wellformed(self):
        """Comparison Hit Rate row is always a well-formed 4-cell row."""
        from clawperf.report import generate_comparison
        md = generate_comparison(_hitrate_result(), _scenario_result(), "A", "B")
        for line in md.splitlines():
            if line.startswith("| Hit Rate"):
                assert line.endswith("|")
                cells = [c.strip() for c in line.strip("|").split("|")]
                assert len(cells) == 4, f"malformed row: {line!r}"

    def test_compare_decode_fallback(self):
        """Trace replay decode falls back to decode_toks for comparison."""
        from clawperf.report import generate_comparison
        trace_res = {
            "config": {"model": "t", "endpoint": "http://x", "backend": "vllm"},
            "summary": {"mode": "trace", "hit_rate": 0.5, "ceiling": 0.6,
                        "speedup": 2.0, "request_count": 5,
                        "replay": {"ttft_p50_ms": 80.0, "decode_tok_s": 100.0}},
            "timing": {"setup_time_s": 0.1, "bench_time_s": 5.0},
        }
        md = generate_comparison(_scenario_result(), trace_res, "scen", "trace")
        assert "100.0" in md  # trace replay decode surfaced


class TestConfigLayering:
    def test_env_overrides_non_none_defaults(self, monkeypatch):
        monkeypatch.setenv("CLAWPERF_MODE", "hitrate")
        monkeypatch.setenv("CLAWPERF_MAX_TURNS", "42")
        from clawperf.config import build_config
        c = build_config({})
        assert c.mode == "hitrate"
        assert c.max_turns == 42

    def test_cli_explicit_beats_env(self, monkeypatch):
        monkeypatch.setenv("CLAWPERF_MODE", "hitrate")
        from clawperf.config import build_config
        c = build_config({"mode": "scenario"})
        assert c.mode == "scenario"

    def test_yaml_hyphen_keys_normalized(self, tmp_path):
        y = tmp_path / "c.yaml"
        y.write_text("max-turns: 77\ncontext-profile: long\n")
        from clawperf.config import build_config
        c = build_config({}, yaml_path=str(y))
        assert c.max_turns == 77
        assert c.context_profile == "long"

    def test_yaml_unknown_key_warns(self, tmp_path):
        y = tmp_path / "c.yaml"
        y.write_text("num_requsts: 9\nmode: scenario\n")
        from clawperf.config import build_config
        c = build_config({}, yaml_path=str(y))
        assert c.num_requests == 100  # unknown key ignored, defaults intact

    def test_env_optional_float_coercion(self, monkeypatch):
        monkeypatch.setenv("CLAWPERF_SLO_TTFT_MS", "200")
        from clawperf.config import build_config
        c = build_config({})
        assert c.slo_ttft_ms == 200.0
        assert isinstance(c.slo_ttft_ms, float)
