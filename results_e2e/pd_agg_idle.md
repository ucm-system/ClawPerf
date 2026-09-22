# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:9155/v1` |
| Backend | vllm |
| Mode | `hitrate` |
| Input Len | 4096 |
| Prefix Len | 2048 |
| Concurrency | 4 |
| Setup Time | 9.94s |
| Bench Time | 4.97s |

## Verdict: ✅ GOOD

- **TTFT (P50):** 201ms — instant (GOOD)
- **Measured hit rate:** 49.90% (target: 50.00%)

## Key Findings

- Target hit rate: 50.0%  |  Measured: 49.9%
- P50 TTFT: 201ms — instant

## Summary

| Metric | Value |
|--------|-------|
| Requests | 40 |
| Success | 40 |
| Errors | 0 |
| Target Hit Rate | 50.0% |
| Measured Hit Rate | 49.90%
| ttft P50 | 201ms |
| e2e_latency P50 | 459ms |
| tpot P50 | 8ms |

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
