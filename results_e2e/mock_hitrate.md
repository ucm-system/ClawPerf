# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `mock` |
| Endpoint | `http://127.0.0.1:9100/v1` |
| Backend | vllm |
| Mode | `hitrate` |
| Input Len | 2048 |
| Prefix Len | 1024 |
| Concurrency | 3 |
| Setup Time | 8.58s |
| Bench Time | 5.55s |

## Verdict: ✅ GOOD

- **TTFT (P50):** 501ms — instant (GOOD)
- **Measured hit rate:** 49.21% (target: 50.00%)

## Key Findings

- Target hit rate: 50.0%  |  Measured: 49.2%
- P50 TTFT: 501ms — instant

## Summary

| Metric | Value |
|--------|-------|
| Requests | 30 |
| Success | 30 |
| Errors | 0 |
| Target Hit Rate | 50.0% |
| Measured Hit Rate | 49.21%
| ttft P50 | 501ms |
| e2e_latency P50 | 503ms |
| tpot P50 | 0ms |

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
