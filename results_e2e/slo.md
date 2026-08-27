# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:8123/v1` |
| Backend | vllm |
| Mode | `slo` |
| SLO | TTFT P99<=1500.0ms |
| Max Users | 8 |
| Setup Time | 14.83s |
| Bench Time | 245.34s |

## Verdict: ✅ GOOD

- **Max sustained users:** 8

## Key Findings

- Max sustained users meeting SLO: 8
- SLO criteria: TTFT P99<=1500.0ms

## Summary

| Users | P99 TTFT | P99 TPOT | Error | SLO |
|-------|----------|----------|-------|-----|
| 1 | 207ms | 8.21ms | 0.0% | ✅ |
| 2 | 318ms | 9.17ms | 0.0% | ✅ |
| 4 | 515ms | 15.22ms | 0.0% | ✅ |
| 8 | 743ms | 26.64ms | 0.0% | ✅ |

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
