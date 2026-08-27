# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:8123/v1` |
| Backend | vllm |
| Mode | `scenario` |
| Users | 4 |
| Max Turns | 10 |
| Context | sys=4000 + usr=1500 + in=1500 tokens |
| Setup Time | 3.50s |
| Bench Time | 36.77s |

## Verdict: ✅ GOOD

- **TTFT (P50):** 291ms — instant (GOOD)
- **Decode throughput:** 71.9 tok/s — smooth (GOOD)

## Key Findings

- Per-user decode throughput ranges 69.7–71.9 tok/s
- Concurrency efficiency: 26% (max_thru / (min_thru × N))
- P50 TTFT: 291ms — instant

## Summary

| User | In Tok | Out Tok | TTFT P50 | TPOT P50 | E2E P50 | tok/s | Comp | Succ | Fail |
|------|--------|---------|----------|----------|---------|-------|------|------|------|
| 0 | 145,686 | 2,560 | 291ms | 12.67ms | 3556ms | 71.9 | 0 | 10 | 0 |
| 1 | 148,411 | 2,560 | 313ms | 12.98ms | 3763ms | 70.2 | 0 | 10 | 0 |
| 2 | 149,370 | 2,560 | 335ms | 12.84ms | 3730ms | 69.8 | 0 | 10 | 0 |
| 3 | 149,456 | 2,560 | 375ms | 12.58ms | 3717ms | 69.7 | 0 | 10 | 0 |

## TTFT Scaling (P50)

```
   1 user(s) | ███████████████████████░░░░░░░ 291ms
   2 user(s) | █████████████████████████░░░░░ 313ms
   3 user(s) | ██████████████████████████░░░░ 335ms
   4 user(s) | ██████████████████████████████ 375ms
```

## Concurrency Scaling

| Users | Total tok/s | Per-user tok/s | Efficiency |
|-------|------------|----------------|------------|
| 1 | 71.9 | 71.9 | 100% |
| 2 | 140.5 | 70.2 | 98% |
| 3 | 209.3 | 69.8 | 97% |
| 4 | 278.9 | 69.7 | 97% |

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
