---
description: 安装 ClawPerf、跑起默认的 scenario 模式，并读懂输出。
---

# 一条命令跑起第一个基准

默认模式是 `scenario`：N 个用户各自进行不断增长的多轮会话。只需要一个正在运行的 OpenAI 兼容端点和一个 tokenizer 目录。

## 安装

=== "pip"

    ```bash
    pip install "clawperf[agent,record,replay,mock-server]"
    ```

=== "container image"

    ```bash
    docker pull ghcr.io/ucm-system/clawperf:latest
    ```

## 首次运行

```bash title="bash"
clawperf --mode scenario \
  --endpoint http://localhost:8000/v1 \
  --model Qwen3-0.6B \
  --tokenizer /mnt/model/Qwen3-0.6B \
  --context-profile medium \
  --num-users 8 --max-turns 20 \
  --metrics-endpoint http://localhost:8000/metrics \
  --output results.json
```

!!! note "把 --tokenizer 指向本地目录"

    **把 `--tokenizer` 指向本地目录。**它会严格离线加载（不查 hub、不下载），并负责精确分词、上下文裁剪与内容生成。指向服务端加载模型的同一个目录即可 —— 也可以先用镜像内置的 `/app/tokenizers/qwen3-0.6b` 验证环境。

## 怎么读输出

以下是在内置 mock server 上的实跑（无需 GPU）—— 横幅以下走的是与真实端点完全相同的代码路径。

```console title="clawperf --mode scenario --endpoint http://127.0.0.1:18095/v1/chat/completions --model \
    qwen3-0.6b --tokenizer tokenizers/qwen3-0.6b --context-profile fresh --num-users 4 \
    --max-turns 4 --output-tokens-per-turn 48 --metrics-endpoint \
    http://127.0.0.1:18095/metrics --reset-cache --output results.json"
======================================================================
ClawPerf - LLM Serving Performance Benchmark
  (Powered by EvalScope perf infrastructure)
======================================================================
  Model:        qwen3-0.6b
  Endpoint:     http://127.0.0.1:18095/v1/chat/completions
  Backend:      vllm
  Users:        4 (arrival: burst)
  Max Turns:    4
  Context:      sys=4000, usr=1500, in=1500, out=48
  Max Context:  128000 tokens
  Ignore EOS:   True
  Tokenizer:    D:\Project\ClawPerf\tokenizers\qwen3-0.6b
  Metrics:      http://127.0.0.1:18095/metrics
  History:      clawperf_history.jsonl (append)
======================================================================
INFO:clawperf:Loaded local tokenizer from D:\Project\ClawPerf\tokenizers\qwen3-0.6b [local dir (transformers)] —
  vocab=151669, chat_template=yes
INFO:clawperf:Pre-flight check: probing http://127.0.0.1:18095/v1/chat/completions ...
INFO:clawperf:Pre-flight check OK (attempt 1/3).
INFO:clawperf:Generating system prefix (4000 tokens)...
INFO:clawperf:Generating user prefix content (1500 tokens/user)...
INFO:clawperf:Generating per-turn input (1500 tokens)...
INFO:clawperf:Metrics start snapshot: query=1 hit=0 ext_query=1 ext_hit=0 engines=['0'] ext_engines=['0']
WARNING:clawperf:Prefix cache reset endpoint http://127.0.0.1:18095/reset_prefix_cache not found (404) — this backend
  doesn't expose cache reset. Continuing without a clean baseline; measured hit rate may include residual prefixes.
INFO:clawperf:Setup complete in 3.67s — starting benchmark
INFO:clawperf:Starting benchmark: 4 users, arrival=burst
Benchmark: 100%|██████████| 16/16 [00:00<00:00, 36.50turn/s]
INFO:clawperf:Metrics end snapshot: query=184,829 hit=141,438 ext_query=8,643 ext_hit=0 engines=['0']
  ext_engines=['0']
INFO:clawperf:History appended to: clawperf_history.jsonl
INFO:clawperf:Markdown report saved to: C:\Users\keriko\AppData\Local\Temp\sample_scenario.md
======================================================================
ClawPerf - Benchmark Complete
======================================================================
  Common Metrics
+--------------------------------------+-----------------+
| Metric                               |           Value |
+--------------------------------------+-----------------+
| Setup Time                           |          3.67 s |
| Duration                             |          0.44 s |
| Total Requests                       |              16 |
| Success Requests                     |              16 |
| Failed Requests                      |               0 |
| Total Input Tokens                   |         184,828 |
| Prefill Token Throughput             | 421981.74 tok/s |
| Total Output Tokens                  |             768 |
| Request Throughput                   |   36.5297 req/s |
| Output Token Throughput              |   1753.42 tok/s |
| Decode Throughput (excl prefill)     |   3301.14 tok/s |
| Total Token Throughput               | 423735.16 tok/s |
| Total Compactions                    |               0 |
| HBM Prefix Cache Token Hit Rate      |          76.52% |
| HBM Prefix Cache Hit Tokens          |         141,438 |
| HBM Prefix Cache Query Tokens        |         184,828 |
| External Prefix Cache Token Hit Rate |           0.00% |
| External Prefix Cache Hit Tokens     |               0 |
| External Prefix Cache Query Tokens   |           8,642 |
+--------------------------------------+-----------------+
```

<div class="grid cards" markdown>

-   :material-numeric:{ .lg .middle } **四个关键数字**

    ---

    **TTFT** —— 首 token 时延。**TPOT** —— 每输出 token。**E2E** —— 请求端到端时延。**命中率** —— 直接读服务端 Prometheus 计数器，从不推断。

-   :material-file-document-outline:{ .lg .middle } **每次运行两个产物**

    ---

    `results.json`（配置 + 按用户/按轮明细 + 指标）与 `results.md`（结论、发现、ASCII 图表）。可用 `clawperf report results.json` 重新生成报告。

</div>

## 手边没有 GPU？

用内置 mock server 替代：它带真实的字典树前缀缓存与 vLLM 风格 `/metrics`，所有模式都能跑通。

```bash title="bash"
clawperf-mock-server --port 8000

# the same command, now pointed at the mock
clawperf --mode scenario --endpoint http://localhost:8000/v1 \
  --model qwen3-0.6b --tokenizer tokenizers/qwen3-0.6b \
  --context-profile fresh --num-users 4 --max-turns 4 \
  --metrics-endpoint http://localhost:8000/metrics --reset-cache
```

## 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 基准跑完并写出结果 |
| `1` | 配置或预检错误（未开始跑基准） |
| `2` | 基准跑了但**全部**请求失败（CI 门禁） |
| `3` | 被中断（Ctrl+C）；退出前会写出部分结果 |

完整的故障排查表（tokenizer 路径、SLO 引号陷阱、预检探针）在[完整参考](reference.zh.md#trouble)里。

shell 引号陷阱，以及裸指标名传到 ClawPerf 时的诊断。

```console title="clawperf --mode slo ... --slo ttft.p99"
$ clawperf --mode slo --endpoint http://141.111.32.62:8000/v1 \
    --model /mnt/model/Qwen3.5-0.8B --tokenizer /mnt/model/Qwen3.5-0.8B \
    --slo ttft.p99<=10000 --slo tpot.avg<=50 --slo e2e.max<=30000
bash: =10000: No such file or directory
        ^ bash treated '<' as a redirection, so ClawPerf never started

$ # the same constraints, written so the shell cannot eat them:
$ clawperf --mode slo ... --slo ttft.p99:10000 --slo tpot.avg:50 --slo e2e.max:30000

$ # and if a bare metric name does reach ClawPerf:
[ClawPerf] configuration error: invalid SLO constraint 'ttft.p99': no operator or threshold found after the metric.
  If you wrote --slo ttft.p99<=1500 without quotes, your shell consumed '<' as a redirection and ClawPerf only
  received 'ttft.p99' — quote it (--slo 'ttft.p99<=1500') or use the shell-safe form --slo ttft.p99:1500. expected
  '<metric>.<agg><op><value_ms>', e.g. ttft.p99<=1500, tpot.avg<=30, e2e.max<=30000 (metrics: ttft|tpot|e2e; aggs:
  avg|min|max|p25|p50|p75|p90|p95|p99|p99.9; ops: <=|<|>=|>). In a shell, '<' and '>' are redirection operators —
  quote the spec (--slo 'ttft.p99<=1500') or use the shell-safe separator form --slo ttft.p99:1500 (':' or '=' means
  '<=', and 'ttft.p99:le:1500' / 'ttft.p99:ge:1500' spell out the operator).
```

[下一步：模式详解 :material-arrow-right:](modes/scenario.zh.md){ .md-button .md-button--primary }
