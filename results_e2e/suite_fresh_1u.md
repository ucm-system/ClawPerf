# ClawPerf Benchmark Report

| Field | Value |
|-------|-------|
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:8123/v1` |
| Backend | vllm |
| Mode | `scenario` |
| Users | 1 |
| Max Turns | 10 |
| Context | sys=4000 + usr=1500 + in=1500 tokens |
| Setup Time | 8.02s |
| Bench Time | 22.88s |

## Verdict: ✅ GOOD

- **TTFT (P50):** 195ms — instant (GOOD)
- **Decode throughput:** 112.1 tok/s — smooth (GOOD)

## Key Findings

- P50 TTFT: 195ms — instant

## Summary

| User | In Tok | Out Tok | TTFT P50 | TPOT P50 | E2E P50 | tok/s | Comp | Succ | Fail |
|------|--------|---------|----------|----------|---------|-------|------|------|------|
| 0 | 144,243 | 2,560 | 195ms | 8.08ms | 2271ms | 112.1 | 0 | 10 | 0 |

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
