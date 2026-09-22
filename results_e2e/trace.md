# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:9155/v1` |
| Backend | vllm |
| Mode | `trace` |
| Requests | 34 |
| Total Tokens | 338,995 |
| Unique Blocks | 523 |
| Policy | lru |
| Setup Time | 0.00s |
| Bench Time | 113.30s |

## Verdict: ✅ GOOD

- **Real replay TTFT (P50):** 111ms — instant (GOOD)
- **Real replay decode:** 101.3 tok/s

## Key Findings

- KV cache hit rate: 90.42%  (ceiling: 90.42%)
- Ideal prefill speedup: 10.44x  (= 1 / (1 - 90.42%))
- Real replay: TTFT P50 111ms, decode 101.3 tok/s

## Summary

| Metric | Value |
|--------|-------|
| Requests | 34 |
| Total Input Tokens | 338,995 |
| Unique Blocks | 523 |
| Hit Rate | 90.42% |
| Ceiling | 90.42% |
| Speedup | 10.44x |
| Hit Tokens | 276,346 |
| Miss Tokens | 29,281 |

### Real Replay (measured)

| Metric | Value |
|--------|-------|
| Requests | 29 ok / 34 total |
| Total Input Tokens | 261,897 |
| Total Output Tokens | 14,159 |
| TTFT P50 | 110.98 ms |
| TTFT P95 | 186.62 ms |
| TTFT P99 | 195.54 ms |
| E2E P50 | 3584.75 ms |
| Decode tok/s | 101.29 tok/s |
| ITL P50 | 9.96 ms |
| ITL P95 | 13.91 ms |

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
