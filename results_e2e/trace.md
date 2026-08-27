# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:8123/v1` |
| Backend | vllm |
| Mode | `trace` |
| Requests | 34 |
| Total Tokens | 20,861 |
| Unique Blocks | 46 |
| Policy | lru |
| Setup Time | 0.00s |
| Bench Time | 133.52s |

## Verdict: ✅ GOOD

- **Real replay TTFT (P50):** 110ms — instant (GOOD)
- **Real replay decode:** 115.1 tok/s

## Key Findings

- KV cache hit rate: 82.79%  (ceiling: 82.79%)
- Ideal prefill speedup: 5.81x  (= 1 / (1 - 82.79%))
- Real replay: TTFT P50 110ms, decode 115.1 tok/s

## Summary

| Metric | Value |
|--------|-------|
| Requests | 34 |
| Total Input Tokens | 20,861 |
| Unique Blocks | 46 |
| Hit Rate | 82.79% |
| Ceiling | 82.79% |
| Speedup | 5.81x |
| Hit Tokens | 1,737 |
| Miss Tokens | 361 |

### Real Replay (measured)

| Metric | Value |
|--------|-------|
| Requests | 34 ok / 34 total |
| Total Input Tokens | 458,832 |
| Total Output Tokens | 18,018 |
| TTFT P50 | 109.71 ms |
| TTFT P95 | 279.72 ms |
| TTFT P99 | 280.97 ms |
| E2E P50 | 3521.93 ms |
| Decode tok/s | 115.12 tok/s |
| ITL P50 | 8.61 ms |
| ITL P95 | 16.31 ms |

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
