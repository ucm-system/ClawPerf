---
description: 用你自己的流量当负载 — ClawPerf trace mode.
---

# trace: 用你自己的流量当负载

## 为什么做这个模式

任何模拟负载都是对你流量的猜测，而生产 trace 不是。这个模式把真实 trace 的 block hash 送进模拟缓存，测出可达复用率与「命中率-预算」曲线（不需要端点）；随后还能把 trace 里的真实请求发到你的端点，测出这份负载的真实代价。

![同一份 trace 上的两条路径：纯 KV 缓存模拟（不需要端点），以及可选的、把 trace 请求真实回放到你的服务端。](../assets/trace.svg)

## 怎么用

```bash title="bash"
# simulation only — no endpoint needed
clawperf --mode trace --trace-file trace.jsonl.gz \
  --budget-sweep --eviction-policy lru

# simulation + real replay, clamped to the model window
clawperf --mode trace --trace-file trace.jsonl.gz \
  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \
  --tokenizer /mnt/model/Qwen3-0.6B \
  --cache-budget-gb 40 --kv-bytes-per-token 2.0 \
  --model-context-length 32768 --trace-users 4 \
  --output results_trace.json
```

## 关键参数

| 参数 | 作用 |
|---|---|
| `--trace-file` | kvcache.ai 格式 JSONL（`hash_ids`、`input_length`、可选 `block_size`），可 gzip，或用 `-` 从标准输入读。 |
| `--budget-sweep` | 扫描多个缓存容量档位，找出收益拐点。 |
| `--cache-budget-tokens` | 按 token 指定固定预算。 |
| `--cache-budget-gb` | 按 GB 指定固定预算，配合 `--kv-bytes-per-token` 换算。 |
| `--eviction-policy` | `lru` 或 `fifo`。 |
| `--trace-users` | trace 带用户/会话标识时的会话级并发。 |
| `--model-context-length` | 裁剪回放的输出长度；放不下的请求会带原因跳过。 |

完整参数列表（含默认值）见[完整参考](../reference.zh.md#params)。

## 真实输出

真实 trace 上的 KV 缓存预算扫描。

```console title="clawperf report results_e2e/trace.json --print"
Report saved to: results_e2e/trace.md
# ClawPerf Benchmark Report
| Field | Value |
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:9155/v1` |
| Backend | vllm |
| Mode | `trace` |
| Requests | 34 |
| Total Tokens | 338,995 |
| Unique Blocks | 523 |
| Policy | lru |
| Setup Time | 0.00s |
| Bench Time | 113.30s |
## Verdict: ✅ GOOD
- **Real replay TTFT (P50):** 111ms — instant (GOOD)
- **Real replay decode:** 101.3 tok/s
## Key Findings
- KV cache hit rate: 90.42%  (ceiling: 90.42%)
- Ideal prefill speedup: 10.44x  (= 1 / (1 - 90.42%))
- Real replay: TTFT P50 111ms, decode 101.3 tok/s
## Summary
| Metric | Value |
| Requests | 34 |
| Total Input Tokens | 338,995 |
| Unique Blocks | 523 |
| Hit Rate | 90.42% |
| Ceiling | 90.42% |
| Speedup | 10.44x |
| Hit Tokens | 276,346 |
| Miss Tokens | 29,281 |
### Real Replay (measured)
| Metric | Value |
| Requests | 29 ok / 34 total |
| Total Input Tokens | 261,897 |
| Total Output Tokens | 14,159 |
| TTFT P50 | 110.98 ms |
| TTFT P95 | 186.62 ms |
| TTFT P99 | 195.54 ms |
| E2E P50 | 3584.75 ms |
| Decode tok/s | 101.29 tok/s |
| ITL P50 | 9.96 ms |
| ITL P95 | 13.91 ms |
## Methodology
<details>
<summary>Click to expand</summary>
- **TTFT** (Time to First Token): wall time from request send to first content chunk on the wire.
- **TPOT** (Time Per Output Token): decode time / output tokens, excluding prefill.
- **ITL** (Inter-Token Latency): gap between consecutive output chunks.
- **Prefix cache hit rate**: token-level, read from the backend's Prometheus counters (start/end delta). Not
  request-level.
- **Verdict thresholds**: TTFT GOOD ≤3s / OK ≤10s; throughput GOOD ≥30 tok/s / OK ≥15 tok/s.
- **Compaction**: when context exceeds ``max_context_tokens``, history is cleared and the user prefix is incremented.
- **Decode throughput** isolates generation speed from prefill (excludes TTFT).
- **Wall-clock per-user throughput** uses real start/end timestamps, not summed per-request latencies.
</details>
```

## 怎么读结果

- **命中率-预算曲线**就是定容答案：选曲线刚好变平之前的那个预算。
- **驱逐次数**说明缓存是在颠簸，而不只是容量不够。
- 真实回放中 **context overflow** 是主动跳过的 —— 那是物理上放不下，不是服务端故障。

---

**其他模式:** [scenario](scenario.zh.md) · [hitrate](hitrate.zh.md) · [slo](slo.zh.md) · [agent](agent.zh.md) · [record & replay](record-replay.zh.md)
