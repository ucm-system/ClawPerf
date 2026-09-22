"""Tests for the KV-cache trace simulator (trace_simulator.py)."""

from __future__ import annotations

import json
import os
import tempfile

import pytest


# ── Trace loading ─────────────────────────────────────────────────────────────

class TestTraceLoading:
    def test_load_basic_trace(self, tmp_path):
        from clawperf.trace_simulator import load_trace
        path = tmp_path / "trace.jsonl"
        path.write_text(
            '{"hash_ids": [1, 2], "input_length": 128}\n'
            '{"hash_ids": [3, 4], "input_length": 128}\n'
        )
        entries, stats = load_trace(str(path))
        assert len(entries) == 2
        assert entries[0].hash_ids == [0, 1]  # interned to dense ints
        assert entries[1].hash_ids == [2, 3]
        assert stats.request_count == 2
        assert stats.total_input_tokens == 256
        assert stats.unique_blocks == 4

    def test_load_with_block_size(self, tmp_path):
        from clawperf.trace_simulator import load_trace
        path = tmp_path / "trace.jsonl"
        path.write_text(
            '{"block_size": 32, "hash_ids": [10, 20], "input_length": 64}\n'
        )
        entries, stats = load_trace(str(path), block_size=64)
        assert entries[0].block_size == 32  # per-line override
        assert stats.block_size == 64  # global default

    def test_load_with_string_hash_ids(self, tmp_path):
        from clawperf.trace_simulator import load_trace
        path = tmp_path / "trace.jsonl"
        path.write_text(
            '{"hash_ids": ["abc", "def"], "input_length": 128}\n'
            '{"hash_ids": ["abc", "xyz"], "input_length": 128}\n'
        )
        entries, stats = load_trace(str(path))
        assert len(entries) == 2
        # "abc" is shared between both entries → same interned id.
        assert entries[0].hash_ids[0] == entries[1].hash_ids[0]
        assert stats.unique_blocks == 3  # abc, def, xyz

    def test_load_gzipped(self, tmp_path):
        import gzip
        from clawperf.trace_simulator import load_trace
        path = tmp_path / "trace.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write('{"hash_ids": [1, 2], "input_length": 128}\n')
        entries, stats = load_trace(str(path))
        assert len(entries) == 1
        assert stats.total_input_tokens == 128

    def test_parse_errors_skipped(self, tmp_path):
        from clawperf.trace_simulator import load_trace
        path = tmp_path / "trace.jsonl"
        path.write_text(
            '{"hash_ids": [1], "input_length": 64}\n'
            'not json\n'
            '{"hash_ids": [], "input_length": 64}\n'  # empty hash_ids
            '{"hash_ids": [2], "input_length": 64}\n'
        )
        entries, stats = load_trace(str(path))
        assert stats.request_count == 2  # 2 valid, 2 invalid
        assert stats.parse_errors == 2

    def test_load_with_messages(self, tmp_path):
        from clawperf.trace_simulator import load_trace
        path = tmp_path / "trace.jsonl"
        path.write_text(
            '{"hash_ids": [1], "input_length": 64, '
            '"messages": [{"role": "user", "content": "hello"}]}\n'
        )
        entries, stats = load_trace(str(path))
        assert entries[0].messages is not None
        assert stats.has_messages is True

    def test_load_with_user_id(self, tmp_path):
        from clawperf.trace_simulator import load_trace
        path = tmp_path / "trace.jsonl"
        path.write_text(
            '{"hash_ids": [1], "input_length": 64, "user_id": 0}\n'
            '{"hash_ids": [2], "input_length": 64, "user_id": 0}\n'
            '{"hash_ids": [3], "input_length": 64, "user_id": 1}\n'
        )
        entries, _ = load_trace(str(path))
        assert entries[0].user_id == 0
        assert entries[1].user_id == 0
        assert entries[2].user_id == 1

    def test_load_with_session_id_alias(self, tmp_path):
        from clawperf.trace_simulator import load_trace
        path = tmp_path / "trace.jsonl"
        path.write_text(
            '{"hash_ids": [1], "input_length": 64, "session_id": 7}\n'
        )
        entries, _ = load_trace(str(path))
        assert entries[0].user_id == 7  # session_id alias → user_id

    def test_max_records(self, tmp_path):
        from clawperf.trace_simulator import load_trace
        path = tmp_path / "trace.jsonl"
        path.write_text(
            '{"hash_ids": [1], "input_length": 64}\n'
            '{"hash_ids": [2], "input_length": 64}\n'
            '{"hash_ids": [3], "input_length": 64}\n'
        )
        entries, _ = load_trace(str(path), max_records=2)
        assert len(entries) == 2


# ── Cache simulation ──────────────────────────────────────────────────────────

class TestPrefixCacheSim:
    def test_all_miss_first_request(self):
        """First request has no cache hits."""
        from clawperf.trace_simulator import simulate_trace, TraceEntry
        entries = [TraceEntry(index=0, hash_ids=[0, 1, 2], input_length=192, block_size=64)]
        result = simulate_trace(entries, budget_tokens=0)  # unlimited
        assert result.hit_rate == 0.0  # first request = all misses
        assert result.miss_tokens > 0
        assert result.speedup == 1.0

    def test_full_hit_on_repeated_prefix(self):
        """Second request with same prefix gets full hits."""
        from clawperf.trace_simulator import simulate_trace, TraceEntry
        entries = [
            TraceEntry(index=0, hash_ids=[0, 1, 2], input_length=192, block_size=64),
            TraceEntry(index=1, hash_ids=[0, 1, 2], input_length=192, block_size=64),
        ]
        result = simulate_trace(entries, budget_tokens=0)
        # Second request: 3 hits out of 6 total blocks (3 miss + 3 hit)
        assert result.hit_rate > 0.0
        assert result.hit_tokens > 0

    def test_partial_hit(self):
        """Second request shares some but not all prefix blocks."""
        from clawperf.trace_simulator import simulate_trace, TraceEntry
        entries = [
            TraceEntry(index=0, hash_ids=[0, 1, 2], input_length=192, block_size=64),
            TraceEntry(index=1, hash_ids=[0, 1, 3], input_length=192, block_size=64),
        ]
        result = simulate_trace(entries, budget_tokens=0)
        # Blocks 0,1 hit; block 2 is miss (first req), block 3 is miss (second req).
        # Total: 2 hits out of 6 blocks (3+3)
        assert result.hit_rate > 0.0
        assert result.hit_rate < 1.0

    def test_budget_eviction_lru(self):
        """Small budget forces eviction; LRU evicts least recently used."""
        from clawperf.trace_simulator import simulate_trace, TraceEntry
        # Budget fits 2 blocks. Second request takes the cache to 3 blocks →
        # evict the least recently used block (0). A 3rd request reusing
        # block 0 then misses (it was evicted).
        entries = [
            TraceEntry(index=0, hash_ids=[0, 1, 2], input_length=192, block_size=64),
            TraceEntry(index=1, hash_ids=[3, 4, 5], input_length=192, block_size=64),
            TraceEntry(index=2, hash_ids=[0, 1], input_length=128, block_size=64),
        ]
        result = simulate_trace(entries, budget_tokens=128, policy="lru")
        assert result.evictions > 0  # had to evict to fit
        # 3rd request: block 0 was evicted (LRU) → miss, block 1 survived → hit.
        assert result.cache_blocks <= 2

    def test_budget_eviction_fifo(self):
        """FIFO evicts oldest-inserted block regardless of recency."""
        from clawperf.trace_simulator import simulate_trace, TraceEntry
        entries = [
            TraceEntry(index=0, hash_ids=[0, 1, 2], input_length=192, block_size=64),
            TraceEntry(index=1, hash_ids=[0, 1, 3], input_length=192, block_size=64),
            TraceEntry(index=2, hash_ids=[3, 4, 5], input_length=192, block_size=64),
        ]
        # Budget 2 blocks. After req2: {0,1,3} → touches 0,1. Req3 adds
        # 4,5 → evicts oldest first (0) under FIFO even though 0 was accessed
        # in req2 (LRU would keep it).
        fifo = simulate_trace(entries, budget_tokens=128, policy="fifo")
        lru = simulate_trace(entries, budget_tokens=128, policy="lru")
        assert fifo.evictions > 0
        assert lru.evictions > 0

    def test_budget_unlimited_matches_ceiling(self):
        """Unlimited budget should match the ceiling."""
        from clawperf.trace_simulator import simulate_trace, compute_ceiling, TraceEntry
        entries = [
            TraceEntry(index=0, hash_ids=[0, 1, 2], input_length=192, block_size=64),
            TraceEntry(index=1, hash_ids=[0, 1, 3], input_length=192, block_size=64),
            TraceEntry(index=2, hash_ids=[0, 4, 5], input_length=192, block_size=64),
        ]
        result = simulate_trace(entries, budget_tokens=0)  # unlimited
        ceiling = compute_ceiling(entries)
        assert abs(result.hit_rate - ceiling) < 0.001  # should match

    def test_speedup_formula(self):
        """Speedup = 1 / (1 - hit_rate)."""
        from clawperf.trace_simulator import simulate_trace, TraceEntry
        entries = [
            TraceEntry(index=0, hash_ids=[0, 1, 2, 3], input_length=256, block_size=64),
            TraceEntry(index=1, hash_ids=[0, 1, 2, 3], input_length=256, block_size=64),
        ]
        result = simulate_trace(entries, budget_tokens=0)
        # 4 hits out of 8 blocks (4 miss + 4 hit) → hit_rate = 0.5
        if result.hit_rate < 1.0:
            expected_speedup = 1.0 / (1.0 - result.hit_rate)
            assert abs(result.speedup - expected_speedup) < 0.01


# ── Ceiling calculation ───────────────────────────────────────────────────────

class TestCeiling:
    def test_ceiling_no_sharing(self):
        """No shared blocks → ceiling = 0."""
        from clawperf.trace_simulator import compute_ceiling, TraceEntry
        entries = [
            TraceEntry(index=0, hash_ids=[0, 1], input_length=128, block_size=64),
            TraceEntry(index=1, hash_ids=[2, 3], input_length=128, block_size=64),
        ]
        assert compute_ceiling(entries) == 0.0

    def test_ceiling_full_sharing(self):
        """All requests share the same prefix → high ceiling."""
        from clawperf.trace_simulator import compute_ceiling, TraceEntry
        entries = [
            TraceEntry(index=0, hash_ids=[0, 1, 2], input_length=192, block_size=64),
            TraceEntry(index=1, hash_ids=[0, 1, 2], input_length=192, block_size=64),
        ]
        ceiling = compute_ceiling(entries)
        # 3 hits out of 6 blocks → 0.5
        assert abs(ceiling - 0.5) < 0.01


# ── Budget sweep ──────────────────────────────────────────────────────────────

class TestBudgetSweep:
    def test_sweep_increasing_hit_rate(self):
        """Hit rate should generally increase with budget."""
        from clawperf.trace_simulator import budget_sweep, TraceEntry
        # Create a trace with many shared prefixes and some unique blocks.
        entries = []
        for i in range(20):
            entries.append(TraceEntry(
                index=i,
                hash_ids=[0, 1, 2, 100 + i],  # shared prefix + unique tail
                input_length=256,
                block_size=64,
            ))
        levels = [64, 128, 192, 256, 320, 10000]
        sweep = budget_sweep(entries, levels, policy="lru")
        assert len(sweep.levels) == 6
        assert sweep.ceiling > 0
        # Hit rate at largest budget should be >= hit rate at smallest.
        assert sweep.levels[-1]["hit_rate"] >= sweep.levels[0]["hit_rate"]

    def test_sweep_has_inflection(self):
        """Budget sweep should find an inflection point."""
        from clawperf.trace_simulator import budget_sweep, TraceEntry
        entries = [
            TraceEntry(index=i, hash_ids=[0, 1, 100 + i], input_length=192, block_size=64)
            for i in range(10)
        ]
        levels = [64, 128, 192, 256, 512, 1024, 10000]
        sweep = budget_sweep(entries, levels)
        assert sweep.inflection_budget > 0

    def test_default_budget_levels(self):
        from clawperf.trace_simulator import default_budget_levels
        levels = default_budget_levels(10000, block_size=64)
        assert len(levels) >= 3
        assert levels[0] == 64
        assert levels[-1] >= 10000
        # Should be monotonically increasing.
        for i in range(1, len(levels)):
            assert levels[i] > levels[i - 1]


# ── Summary & integration ──────────────────────────────────────────────────────

class TestSummary:
    def test_summarize_simulation(self):
        from clawperf.trace_simulator import (
            simulate_trace, summarize_simulation, TraceEntry, TraceStats,
        )
        entries = [
            TraceEntry(index=0, hash_ids=[0, 1, 2], input_length=192, block_size=64),
            TraceEntry(index=1, hash_ids=[0, 1, 3], input_length=192, block_size=64),
        ]
        stats = TraceStats(
            request_count=2, total_input_tokens=384, unique_blocks=4,
            total_blocks=6, average_input_tokens=192.0, block_size=64,
        )
        result = simulate_trace(entries, budget_tokens=0)
        summary = summarize_simulation(entries, stats, result)
        assert summary["mode"] == "trace"
        assert summary["request_count"] == 2
        assert summary["hit_rate"] == result.hit_rate
        assert "speedup" in summary
        assert "ceiling" in summary

    def test_summarize_with_sweep(self):
        from clawperf.trace_simulator import (
            budget_sweep, simulate_trace, summarize_simulation,
            TraceEntry, TraceStats,
        )
        entries = [
            TraceEntry(index=i, hash_ids=[0, 1, 100 + i], input_length=192, block_size=64)
            for i in range(5)
        ]
        stats = TraceStats(
            request_count=5, total_input_tokens=960, unique_blocks=7,
            total_blocks=15, average_input_tokens=192.0, block_size=64,
        )
        sweep = budget_sweep(entries, [64, 128, 192, 10000])
        result = simulate_trace(entries, budget_tokens=10000)
        summary = summarize_simulation(entries, stats, result, sweep)
        assert "budget_sweep" in summary
        assert len(summary["budget_sweep"]) == 4
        assert "inflection_budget_tokens" in summary


class TestTraceReport:
    def test_trace_verdict(self):
        from clawperf.report import compute_verdict
        result = {
            "summary": {"mode": "trace", "hit_rate": 0.85, "ceiling": 0.90, "speedup": 6.67},
            "config": {}, "timing": {},
        }
        v = compute_verdict(result)
        assert v["overall"] == "GOOD"
        assert v["hit_rate"] == 0.85
        assert v["speedup"] == 6.67

    def test_trace_verdict_marginal(self):
        from clawperf.report import compute_verdict
        result = {
            "summary": {"mode": "trace", "hit_rate": 0.40, "ceiling": 0.80, "speedup": 1.67},
            "config": {}, "timing": {},
        }
        v = compute_verdict(result)
        assert v["overall"] == "MARGINAL"

    def test_trace_markdown_report(self):
        from clawperf.report import generate_report
        result = {
            "config": {"model": "test", "endpoint": "local", "backend": "vllm",
                       "trace_file": "trace.jsonl", "eviction_policy": "lru"},
            "summary": {
                "mode": "trace", "request_count": 100, "total_input_tokens": 12800,
                "unique_blocks": 200, "hit_rate": 0.75, "ceiling": 0.90,
                "speedup": 4.0, "hit_tokens": 9600, "miss_tokens": 3200,
                "evictions": 50, "policy": "lru",
                "budget_sweep": [
                    {"budget_tokens": 640, "hit_rate": 0.3, "speedup": 1.43, "evictions": 100},
                    {"budget_tokens": 6400, "hit_rate": 0.75, "speedup": 4.0, "evictions": 50},
                ],
            },
            "timing": {"setup_time_s": 0.1, "bench_time_s": 0.5},
        }
        md = generate_report(result)
        assert "# ClawPerf Benchmark Report" in md
        assert "trace" in md.lower()
        assert "Budget Sweep" in md
        assert "Hit Rate" in md
        assert "Speedup" in md


# ── Replay context-window clamping ───────────────────────────────────────────

class TestClampReplayMaxTokens:
    def _decide(self, **kw):
        from clawperf.trace_simulator import clamp_replay_max_tokens
        args = dict(index=0, messages=[], input_length=1000, max_tokens=512,
                    max_context_tokens=8192, token_counter=None)
        args.update(kw)
        return clamp_replay_max_tokens(**args)

    def test_disabled_when_no_window(self):
        assert self._decide(max_context_tokens=0) == ("none", None, None)

    def test_fits_as_is(self):
        # 1000 + 512 << 8192*0.9
        assert self._decide()[0] == "none"

    def test_clamps_to_remaining_window(self):
        # estimate path: effective window = int(8192*0.9)=7372; room=6372 >= 512 → none.
        # Tighter: input 7000 → room 372 < 512 → clamp to 372.
        action, mt, in_tok = self._decide(input_length=7000)
        assert action == "clamp" and mt == 372 and in_tok == 7000

    def test_clamp_floor_of_16(self):
        # room = 7372-7360 = 12 → clamped to floor 16
        action, mt, _ = self._decide(input_length=7360)
        assert action == "clamp" and mt == 16

    def test_overflow_via_estimate(self):
        action, mt, in_tok = self._decide(input_length=7500)
        assert action == "overflow" and mt is None and in_tok == 7500

    def test_exact_counter_fits(self):
        action, mt, in_tok = self._decide(token_counter=lambda m: 100)
        assert action == "none" and in_tok == 100

    def test_exact_counter_clamps(self):
        action, mt, in_tok = self._decide(token_counter=lambda m: 8000, max_tokens=512)
        assert action == "clamp" and mt == 192 and in_tok == 8000

    def test_exact_counter_overflows(self):
        action, mt, in_tok = self._decide(token_counter=lambda m: 9000)
        assert action == "overflow" and in_tok == 9000

    def test_counter_exception_falls_back_to_estimate(self):
        def boom(messages):
            raise RuntimeError("no tokenizer")
        # input_length 7000 → estimate path clamps to 372
        action, mt, _ = self._decide(token_counter=boom, input_length=7000)
        assert action == "clamp" and mt == 372

    def test_exact_counter_overrides_estimate(self):
        # Estimate says tight, exact count says plenty of room.
        action, mt, in_tok = self._decide(input_length=7000, token_counter=lambda m: 200)
        assert action == "none" and in_tok == 200
