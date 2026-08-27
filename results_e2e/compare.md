# ClawPerf Comparison Report

**hitrate** vs **trace**

| Metric | hitrate | trace | Delta |
|--------|-------|-------|-------|
| P50 TTFT (ms) | 157.8 | 109.7 | -48.1 (-30.5%) |
| Decode tok/s | N/A | 115.1 | — |
| Hit Rate | 49.9% | N/A | — |
| Verdict | ✅ GOOD | ✅ GOOD | — |
| Bench Time (s) | 4.88 | 133.52 | +128.64 (+2638.8%) |
| Total Output Tok | 1,280 | 18,018 | +16,738 (+1307.7%) |

## TTFT Comparison
```
  hitrate  | █████████████████████████ 158ms
  trace    | █████████████████░░░░░░░░ 110ms
```
