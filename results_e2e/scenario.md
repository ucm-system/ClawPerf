# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:8123/v1` |
| Backend | vllm |
| Mode | `scenario` |
| Users | 2 |
| Max Turns | 4 |
| Context | sys=4000 + usr=1500 + in=1500 tokens |
| Setup Time | 14.67s |
| Bench Time | 35.00s |

## Verdict: ✅ GOOD

- **TTFT (P50):** 186ms — instant (GOOD)
- **Decode throughput:** 115.1 tok/s — smooth (GOOD)

## Key Findings

- Per-user decode throughput ranges 115.0–115.1 tok/s
- Concurrency efficiency: 50% (max_thru / (min_thru × N))
- P50 TTFT: 186ms — instant

## Summary

| User | In Tok | Out Tok | TTFT P50 | TPOT P50 | E2E P50 | tok/s | Comp | Succ | Fail |
|------|--------|---------|----------|----------|---------|-------|------|------|------|
| 0 | 42,213 | 4,000 | 186ms | 8.49ms | 8676ms | 115.1 | 0 | 4 | 0 |
| 1 | 43,116 | 4,000 | 228ms | 8.46ms | 8677ms | 115.0 | 0 | 4 | 0 |

## TTFT Scaling (P50)

```
   1 user(s) | ████████████████████████░░░░░░ 186ms
   2 user(s) | ██████████████████████████████ 228ms
```

## Concurrency Scaling

| Users | Total tok/s | Per-user tok/s | Efficiency |
|-------|------------|----------------|------------|
| 1 | 115.1 | 115.1 | 100% |
| 2 | 230.0 | 115.0 | 100% |

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
