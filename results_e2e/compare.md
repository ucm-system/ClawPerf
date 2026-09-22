# ClawPerf Comparison Report

**vLLM-hitrate** vs **trace-replay**

| Metric | vLLM-hitrate | trace-replay | Delta |
|--------|-------|-------|-------|
| P50 TTFT (ms) | 214.4 | 100.5 | -113.9 (-53.1%) |
| Decode tok/s | N/A | 102.8 | — |
| Hit Rate | 49.9% | N/A | — |
| Verdict | ✅ GOOD | ✅ GOOD | — |
| Bench Time (s) | 5.19 | 97.91 | +92.72 (+1787.5%) |
| Total Output Tok | 1,280 | 12,534 | +11,254 (+879.2%) |

## TTFT Comparison
```
  vLLM-hitrate | █████████████████████████ 214ms
  trace-replay | ███████████░░░░░░░░░░░░░░ 100ms
```
