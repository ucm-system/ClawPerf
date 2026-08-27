# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:8123/v1` |
| Backend | vllm |
| Mode | `scenario` |
| Users | 8 |
| Max Turns | 10 |
| Context | sys=4000 + usr=1500 + in=1500 tokens |
| Setup Time | 3.95s |
| Bench Time | 58.47s |

## Verdict: ✅ GOOD

- **TTFT (P50):** 278ms — instant (GOOD)
- **Decode throughput:** 45.5 tok/s — smooth (GOOD)

## Key Findings

- Per-user decode throughput ranges 43.8–45.5 tok/s
- Concurrency efficiency: 13% (max_thru / (min_thru × N))
- P50 TTFT: 278ms — instant

## Summary

| User | In Tok | Out Tok | TTFT P50 | TPOT P50 | E2E P50 | tok/s | Comp | Succ | Fail |
|------|--------|---------|----------|----------|---------|-------|------|------|------|
| 0 | 148,425 | 2,560 | 278ms | 20.91ms | 5589ms | 45.5 | 0 | 10 | 0 |
| 1 | 149,246 | 2,560 | 321ms | 21.25ms | 5740ms | 44.5 | 0 | 10 | 0 |
| 2 | 149,023 | 2,560 | 542ms | 21.02ms | 5730ms | 43.8 | 0 | 10 | 0 |
| 3 | 145,151 | 2,560 | 541ms | 20.89ms | 5689ms | 43.8 | 0 | 10 | 0 |
| 4 | 145,497 | 2,560 | 447ms | 21.16ms | 5756ms | 43.9 | 0 | 10 | 0 |
| 5 | 148,606 | 2,560 | 327ms | 21.37ms | 5834ms | 44.4 | 0 | 10 | 0 |
| 6 | 149,529 | 2,560 | 411ms | 21.20ms | 5745ms | 44.1 | 0 | 10 | 0 |
| 7 | 145,414 | 2,560 | 284ms | 21.37ms | 5691ms | 44.6 | 0 | 10 | 0 |

## TTFT Scaling (P50)

```
   1 user(s) | ███████████████░░░░░░░░░░░░░░░ 278ms
   2 user(s) | █████████████████░░░░░░░░░░░░░ 321ms
   3 user(s) | ██████████████████████████████ 542ms
   4 user(s) | █████████████████████████████░ 541ms
   5 user(s) | ████████████████████████░░░░░░ 447ms
   6 user(s) | ██████████████████░░░░░░░░░░░░ 327ms
   7 user(s) | ██████████████████████░░░░░░░░ 411ms
   8 user(s) | ███████████████░░░░░░░░░░░░░░░ 284ms
```

## Concurrency Scaling

| Users | Total tok/s | Per-user tok/s | Efficiency |
|-------|------------|----------------|------------|
| 1 | 45.5 | 45.5 | 100% |
| 2 | 89.0 | 44.5 | 98% |
| 3 | 131.4 | 43.8 | 96% |
| 4 | 175.3 | 43.8 | 96% |
| 5 | 219.4 | 43.9 | 96% |
| 6 | 266.5 | 44.4 | 98% |
| 7 | 309.0 | 44.1 | 97% |
| 8 | 356.8 | 44.6 | 98% |

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
