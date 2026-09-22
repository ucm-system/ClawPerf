# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:9155/v1` |
| Backend | vllm |
| Mode | `scenario` |
| Users | 8 |
| Max Turns | 10 |
| Context | sys=4000 + usr=1500 + in=1500 tokens |
| Setup Time | 3.53s |
| Bench Time | 60.02s |

## Verdict: ✅ GOOD

- **TTFT (P50):** 242ms — instant (GOOD)
- **Decode throughput:** 44.7 tok/s — smooth (GOOD)

## Key Findings

- TTFT degrades 2.3× from 224ms (1 user) to 522ms (8 users) — concurrency contention
- Per-user decode throughput ranges 42.7–44.7 tok/s
- Concurrency efficiency: 13% (max_thru / (min_thru × N))
- P50 TTFT: 242ms — instant

## Summary

| User | In Tok | Out Tok | TTFT P50 | TPOT P50 | E2E P50 | tok/s | Comp | Succ | Fail |
|------|--------|---------|----------|----------|---------|-------|------|------|------|
| 0 | 149,610 | 2,560 | 242ms | 20.50ms | 5449ms | 44.7 | 0 | 10 | 0 |
| 1 | 149,610 | 2,560 | 250ms | 21.33ms | 5648ms | 43.6 | 0 | 10 | 0 |
| 2 | 149,600 | 2,560 | 224ms | 20.67ms | 5485ms | 44.3 | 0 | 10 | 0 |
| 3 | 149,610 | 2,560 | 420ms | 22.96ms | 6276ms | 42.7 | 0 | 10 | 0 |
| 4 | 145,171 | 2,560 | 292ms | 22.59ms | 6003ms | 43.0 | 0 | 10 | 0 |
| 5 | 149,601 | 2,560 | 522ms | 22.90ms | 6356ms | 42.7 | 0 | 10 | 0 |
| 6 | 149,610 | 2,560 | 500ms | 22.87ms | 6355ms | 42.7 | 0 | 10 | 0 |
| 7 | 149,610 | 2,560 | 292ms | 21.88ms | 5808ms | 43.3 | 0 | 10 | 0 |

## TTFT Scaling (P50)

```
   1 user(s) | █████████████░░░░░░░░░░░░░░░░░ 242ms
   2 user(s) | ██████████████░░░░░░░░░░░░░░░░ 250ms
   3 user(s) | ████████████░░░░░░░░░░░░░░░░░░ 224ms
   4 user(s) | ████████████████████████░░░░░░ 420ms
   5 user(s) | ████████████████░░░░░░░░░░░░░░ 292ms
   6 user(s) | ██████████████████████████████ 522ms
   7 user(s) | ████████████████████████████░░ 500ms
   8 user(s) | ████████████████░░░░░░░░░░░░░░ 292ms
```

## Concurrency Scaling

| Users | Total tok/s | Per-user tok/s | Efficiency |
|-------|------------|----------------|------------|
| 1 | 44.7 | 44.7 | 100% |
| 2 | 87.3 | 43.6 | 98% |
| 3 | 132.8 | 44.3 | 99% |
| 4 | 170.9 | 42.7 | 96% |
| 5 | 215.0 | 43.0 | 96% |
| 6 | 256.2 | 42.7 | 96% |
| 7 | 299.1 | 42.7 | 96% |
| 8 | 346.5 | 43.3 | 97% |

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
