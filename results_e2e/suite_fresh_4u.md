# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:9155/v1` |
| Backend | vllm |
| Mode | `scenario` |
| Users | 4 |
| Max Turns | 10 |
| Context | sys=4000 + usr=1500 + in=1500 tokens |
| Setup Time | 3.20s |
| Bench Time | 36.05s |

## Verdict: ✅ GOOD

- **TTFT (P50):** 214ms — instant (GOOD)
- **Decode throughput:** 72.9 tok/s — smooth (GOOD)

## Key Findings

- Per-user decode throughput ranges 71.1–72.9 tok/s
- Concurrency efficiency: 26% (max_thru / (min_thru × N))
- P50 TTFT: 214ms — instant

## Summary

| User | In Tok | Out Tok | TTFT P50 | TPOT P50 | E2E P50 | tok/s | Comp | Succ | Fail |
|------|--------|---------|----------|----------|---------|-------|------|------|------|
| 0 | 149,610 | 2,560 | 214ms | 12.55ms | 3404ms | 72.9 | 0 | 10 | 0 |
| 1 | 149,610 | 2,560 | 299ms | 12.57ms | 3517ms | 71.1 | 0 | 10 | 0 |
| 2 | 149,610 | 2,560 | 359ms | 12.51ms | 3519ms | 71.1 | 0 | 10 | 0 |
| 3 | 149,602 | 2,560 | 251ms | 12.80ms | 3493ms | 71.8 | 0 | 10 | 0 |

## TTFT Scaling (P50)

```
   1 user(s) | █████████████████░░░░░░░░░░░░░ 214ms
   2 user(s) | █████████████████████████░░░░░ 299ms
   3 user(s) | ██████████████████████████████ 359ms
   4 user(s) | ████████████████████░░░░░░░░░░ 251ms
```

## Concurrency Scaling

| Users | Total tok/s | Per-user tok/s | Efficiency |
|-------|------------|----------------|------------|
| 1 | 72.9 | 72.9 | 100% |
| 2 | 142.3 | 71.1 | 98% |
| 3 | 213.3 | 71.1 | 97% |
| 4 | 287.3 | 71.8 | 98% |

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
