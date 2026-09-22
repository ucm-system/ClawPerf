# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `mock` |
| Endpoint | `http://127.0.0.1:9100/v1` |
| Backend | vllm |
| Mode | `scenario` |
| Users | 2 |
| Max Turns | 3 |
| Context | sys=2000 + usr=500 + in=300 tokens |
| Setup Time | 5.09s |
| Bench Time | 1.59s |

## Verdict: ✅ GOOD

- **TTFT (P50):** 504ms — instant (GOOD)
- **Decode throughput:** 380.2 tok/s — smooth (GOOD)

## Key Findings

- Per-user decode throughput ranges 380.2–384.1 tok/s
- Concurrency efficiency: 51% (max_thru / (min_thru × N))
- P50 TTFT: 504ms — instant

## Summary

| User | In Tok | Out Tok | TTFT P50 | TPOT P50 | E2E P50 | tok/s | Comp | Succ | Fail |
|------|--------|---------|----------|----------|---------|-------|------|------|------|
| 0 | 11,844 | 600 | 504ms | 0.04ms | 512ms | 380.2 | 0 | 3 | 0 |
| 1 | 11,949 | 600 | 505ms | 0.04ms | 513ms | 384.1 | 0 | 3 | 0 |

## TTFT Scaling (P50)

```
   1 user(s) | █████████████████████████████░ 504ms
   2 user(s) | ██████████████████████████████ 505ms
```

## Concurrency Scaling

| Users | Total tok/s | Per-user tok/s | Efficiency |
|-------|------------|----------------|------------|
| 1 | 380.2 | 380.2 | 100% |
| 2 | 768.2 | 384.1 | 101% |

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
