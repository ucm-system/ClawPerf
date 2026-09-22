# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:9150/v1` |
| Backend | vllm |
| Mode | `scenario` |
| Users | 2 |
| Max Turns | 4 |
| Context | sys=4000 + usr=1500 + in=1500 tokens |
| Setup Time | 13.86s |
| Bench Time | 38.06s |

## Verdict: ✅ GOOD

- **TTFT (P50):** 224ms — instant (GOOD)
- **Decode throughput:** 112.4 tok/s — smooth (GOOD)

## Key Findings

- Per-user decode throughput ranges 105.5–112.4 tok/s
- Concurrency efficiency: 53% (max_thru / (min_thru × N))
- P50 TTFT: 224ms — instant

## Summary

| User | In Tok | Out Tok | TTFT P50 | TPOT P50 | E2E P50 | tok/s | Comp | Succ | Fail |
|------|--------|---------|----------|----------|---------|-------|------|------|------|
| 0 | 40,287 | 4,000 | 224ms | 8.71ms | 8897ms | 112.4 | 0 | 4 | 0 |
| 1 | 41,427 | 4,000 | 231ms | 8.66ms | 8865ms | 105.5 | 0 | 4 | 0 |

## TTFT Scaling (P50)

```
   1 user(s) | █████████████████████████████░ 224ms
   2 user(s) | ██████████████████████████████ 231ms
```

## Concurrency Scaling

| Users | Total tok/s | Per-user tok/s | Efficiency |
|-------|------------|----------------|------------|
| 1 | 112.4 | 112.4 | 100% |
| 2 | 211.0 | 105.5 | 94% |

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
