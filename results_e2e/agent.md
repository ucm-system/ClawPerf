# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:8123/v1` |
| Backend | vllm |
| Mode | `agent` |
| Tasks | 2 |
| Max Steps | 8 |
| Setup Time | 0.09s |
| Bench Time | 3.72s |

## Verdict: ✅ GOOD

- **TTFT (P50):** 404ms — instant (GOOD)
- **Task completion:** 100%

## Key Findings

- Task completion rate: 100% (2/2)
- P50 TTFT: 404ms — instant

## Summary

| Task | Steps | Finished | Wall(s) | In Tok | Out Tok |
|------|-------|----------|---------|--------|---------|
| 0 | 1 | yes | 3.59 | 449 | 256 |
| 1 | 1 | yes | 2.34 | 449 | 256 |

## Methodology

<details>
<summary>Click to expand</summary>

- **TTFT** (Time to First Token): wall time from request send to first content chunk on the wire.
- **TPOT** (Time Per Output Token): decode time / output tokens, excluding prefill.
- **ITL** (Inter-Token Latency): gap between consecutive output chunks.
- **Prefix cache hit rate**: token-level, read from the backend's Prometheus counters (start/end delta). Not request-level.
- **Verdict thresholds**: TTFT GOOD ≤3s / OK ≤10s; throughput GOOD ≥30 tok/s / OK ≥15 tok/s.
- **Compaction**: when context exceeds ``max_context_tokens``, history is cleared and the user prefix is incremented.
- **Decode throughput** isolates generation speed from prefill (excludes TTFT).
- **Wall-clock per-user throughput** uses real start/end timestamps, not summed per-request latencies.

</details>
