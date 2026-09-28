---
description: ClawPerf 全部参数，由 clawperf --help 自动生成。
---

# 全部参数，由代码自动生成

本页由 `clawperf --help` 与上下文档位定义自动生成，不会与工具脱节。共 **73 个参数 / 77 个 flag。**

## SLO 约束语法

约束写法是 `<指标>.<统计量><分隔符><毫秒>` —— 重复 `--slo` 可「与」多个约束。

| 写法 | 含义 | 说明 |
|---|---|---|
| `ttft.p99:1500` | `ttft.p99 <= 1500ms` | 免引号 |
| `tpot.avg=30` | `tpot.avg <= 30ms` | 免引号 |
| `'ttft.p99<=1500'` | `ttft.p99 <= 1500ms` | 在 bash/zsh 中必须加引号 |
| `ttft.p99\:ge:1500` | `ttft.p99 >= 1500ms` | 唯一免引号的 `>=` 写法 |
| `'a<=1,b<=2'` | 两条约束 | 一个引号参数写多条约束 |

!!! warning

    在 shell 中要么给 `<=` 加引号，要么改用不含 `<` / `>` 的分隔符，因为它们是重定向符号。

**指标** —— `ttft`（首 token 时延）、`tpot`（每输出 token 时延）、`e2e`（端到端时延）。

**统计量** —— `avg`、`min`、`max`，以及任意分位 `p25 p50 p75 p90 p95 p99 p99.9`。多条约束为「与」关系；一旦某一级打破了任意一条，扫描即在此停止。

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

## 全部参数 {#params}

每个参数、默认值与可选值。各模式专属参数列在通用参数之后。

### Mode

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--mode <MODE>` | `scenario` | 基准模式（见上文各模式介绍）：scenario（默认，多轮长上下文负载）、hitrate（受控前缀缓存命中率）、slo（扫描并发找 SLO 临界点）、agent（真实工具调用 Agent）、record（录制代理）、replay（回放录制）、trace（基于 trace 的 KV 缓存模拟）。<br>**可选值:** `scenario`, `hitrate`, `slo`, `agent`, `record`, `replay`, `trace` |

### Context Profiles & Suites

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--context-profile <NAME>` | `—` | 命名的上下文档位（大小写不敏感），会覆盖下面的原始 token 数：fresh、short、medium、long、full、xl、xxl（基础上下文约 6K→400K，具体拆分见档位表）。 |
| `--suite <NAME>` | `—` | 预置套件：quick、standard、full、hitrate。按序运行多个（并发用户 × 档位）场景。 |
| `--model-context-length <TOKENS>` | `0` | 模型的最大上下文窗口。超出该窗口的套件档位会被跳过；trace 回放时会据此裁剪 max_tokens，保证请求能放进窗口（0 = 不限制）。 |

### User Configuration

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--num-users <NUM_USERS>` | `1` | 并发用户总数。 |
| `--user-arrival <USER_ARRIVAL>` | `burst` | 'burst'（一次性全部加入）、'steady:<秒>'（每 N 秒加入一个）、'poisson:<λ>'（泊松到达，λ 为到达率）。 |

### Context Configuration

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--system-prefix-tokens <SYSTEM_PREFIX_TOKENS>` | `15000` | 所有用户共享的系统提示词长度（上下文的主要部分），会被 --context-profile/--suite 覆盖。 |
| `--system-prefix-source <SYSTEM_PREFIX_SOURCE>` | `random` | 'random' 表示合成填充内容；也可传文件路径，用文件内容作为系统前缀。 |
| `--user-prefix-tokens <USER_PREFIX_TOKENS>` | `5000` | 每个用户各自独有的前缀长度（各不相同，避免前缀缓存被轻易命中）。 |
| `--input-tokens-per-turn <INPUT_TOKENS_PER_TURN>` | `5000` | 每轮追加的新用户内容长度。 |
| `--output-tokens-per-turn <OUTPUT_TOKENS_PER_TURN>` | `1000` | 每轮最大生成 token 数（配合 --ignore-eos 时即为实际测得的解码长度）。 |
| `--max-context-tokens <MAX_CONTEXT_TOKENS>` | `128000` | 触发追加式压缩的窗口阈值（必须与模型真实上下文窗口一致）。 |
| `--compaction-prefix-increment <COMPACTION_PREFIX_INCREMENT>` | `5000` | 每次压缩后向压缩前缀追加的 token 数。 |

### Run Configuration

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--request-rate <RPS>` | `0.0` | 开环请求发送速率（req/s，泊松到达，语义同 benchmark_serving）。0（默认）为闭环：由 --concurrency（hitrate/replay/trace）或连续轮次（scenario/slo/agent）驱动节奏。大于 0 时，hitrate/replay/trace 会忽略 --concurrency —— 请求按计划发送，与是否完成无关。注意：--user-arrival 控制的是用户（会话）何时加入，--request-rate 控制的是单个请求的发送节奏。 |
| `--concurrency <CONCURRENCY>` | `1` | 请求级并发：hitrate 测量阶段、replay、以及无用户标识的 trace 真实回放的在途请求数。trace 会话请用 --trace-users。 |
| `--max-turns <MAX_TURNS>` | `100` | scenario 模式下每个用户的轮数（往返次数）；--suite 会覆盖该值。 |
| `--max-consecutive-failures <MAX_CONSECUTIVE_FAILURES>` | `0` | 连续失败达到该次数后中止基准（0 = 不启用）。 |

### API Configuration

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--endpoint <ENDPOINT>` | `—` | LLM API 端点地址（环境变量：CLAWPERF_ENDPOINT）。 |
| `--model <MODEL>` | `—` | 模型名称（环境变量：CLAWPERF_MODEL）。 |
| `--api-key <API_KEY>` | `—` | API Key（环境变量：CLAWPERF_API_KEY）。 |
| `--tokenizer <TOKENIZER>` | `—` | tokenizer 路径或模型 id（默认为 --model）。本地目录会严格离线加载（不查 hub）；可用 CLAWPERF_TOKENIZER_BACKEND=transformers\|modelscope 强制指定后端。 |
| `--ignore-eos`<br>`--no-ignore-eos` | `on` | 要求服务端忽略 EOS，让每个请求都解码满输出长度（默认开启 —— 这是比较吞吐的公平做法）。 / 允许模型在 EOS 处自然停止（更贴近真实对话时延）。 |
| `--request-timeout <REQUEST_TIMEOUT>` | `600` | 单个请求的超时时间（秒）。 |
| `--no-preflight` | `on` | 跳过预检探针（正式跑之前发出的那个极小请求，用于尽早发现 endpoint/模型写错）。当服务端会重置该探针但实际能正常服务时使用。 |
| `--preflight-retries <PREFLIGHT_RETRIES>` | `3` | 预检探针的最大尝试次数（默认 3 次；传输类错误会带退避重试）。 |

### System Metrics

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--metrics-endpoint <URL>` | `—` | Prometheus 指标端点。可重复指定（或用逗号分隔），用于多实例 / PD 分离服务 —— 每个 prefill/decode 实例各暴露一个 /metrics，计数器求和成全局视图，并给出逐实例的引擎明细。可用 '名称=url' 指定标签（默认标签为 host:port）。 |
| `--metrics-interval <METRICS_INTERVAL>` | `5` | 周期性抓取 /metrics 的间隔秒数（仅在 --metrics-samples 时生效）。 |
| `--metrics-samples` | `off` | 在运行过程中周期性抓取 /metrics，而不只是开始/结束各一次（会带来少量额外请求）。 |
| `--reset-cache` | `off` | 运行前清空服务端前缀缓存，使测得的命中率只反映本次基准的流量。 |
| `--backend <BACKEND>` | `vllm` | 服务端后端类型，决定读取哪些 Prometheus 指标名。<br>**可选值:** `vllm`, `sglang`, `mindie` |

### Output

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--output <OUTPUT>` | `—` | 输出 JSON 文件路径（默认带时间戳的 results_<ts>.json）。环境变量：CLAWPERF_OUTPUT。 |
| `--history <HISTORY>` | `—` | 每次运行向该 JSONL 文件追加一行记录。环境变量：CLAWPERF_HISTORY。传 '' 可关闭。 |
| `-v`<br>`--verbose` | `off` | 逐请求打印日志而不是显示进度条（适合 CI 日志）。 |

### Configuration Files

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--config <CONFIG>` | `—` | YAML 配置文件。优先级低于命令行参数与环境变量。 |

#### Hit-Rate Mode (only with --mode hitrate) {#opt-hitrate}

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--num-requests <NUM_REQUESTS>` | `100` | 测量阶段的请求总数。 |
| `--input-len <INPUT_LEN>` | `1024` | 每个请求的提示词总长度 = 共享前缀 + 边界 token + 各自独有的后缀。 |
| `--output-len <OUTPUT_LEN>` | `128` | 每个请求生成的 token 数（预热/预填充阶段只用 1）。 |
| `--prefix-len <PREFIX_LEN>` | `0` | 共享前缀的 token 长度（0 = 由 --hit-rate 反推）。 |
| `--hit-rate <HIT_RATE>` | `—` | 目标共享比例 0..1，用于反推 --prefix-len；与 --prefix-len 互斥。 |
| `--prefix-num <PREFIX_NUM>` | `1` | 不同前缀的个数；每个前缀分到的请求数 = N // prefix-num。 |
| `--prefill`<br>`--no-prefill` | `on` | 测量前先把每个不同前缀注入 KV 缓存。 / 跳过预填充阶段（测冷缓存表现）。 |
| `--seed <SEED>` | `0` | 提示词构造的随机种子，用于复现。 |

#### SLO Mode (only with --mode slo) {#opt-slo}

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--slo <SPEC>` | `—` | 灵活的 SLO 约束，可重复指定：<指标>.<统计量><分隔符><毫秒>，例如 ttft.p99<=1500、tpot.avg<=30、e2e.max<=30000。指标：ttft\|tpot\|e2e；统计量：avg\|min\|max\|p25\|p50\|p75\|p90\|p95\|p99…；运算符：<=\|<\|>=\|>。多条约束之间为「与」关系。shell 安全：'<' 与 '>' 是重定向符号，所以要么加引号（--slo 'ttft.p99<=1500'），要么用免引号分隔符写法 --slo ttft.p99:1500（':' 或 '=' 表示 '<='，--slo ttft.p99\:ge:1500 表示 '>='）。一个引号参数内可用逗号写多条：--slo 'ttft.p99<=1500,tpot.avg<=30'。给出后即替代旧式 --slo-ttft-ms/--slo-tpot-ms。 |
| `--slo-ttft-ms <SLO_TTFT_MS>` | `—` | 旧式写法：在 --slo-percentile 分位上的 TTFT 阈值（推荐改用 --slo ttft.p99<=X）。 |
| `--slo-tpot-ms <SLO_TPOT_MS>` | `—` | 旧式写法：在 --slo-percentile 分位上的 TPOT 阈值（推荐改用 --slo tpot.p99<=X）。 |
| `--slo-percentile <SLO_PERCENTILE>` | `0.99` | 旧式 --slo-ttft-ms/--slo-tpot-ms 所使用的分位（给出 --slo 约束时忽略）。 |
| `--slo-error-rate <FRACTION>` | `—` | 额外的达标条件：该步的错误率必须不高于此比例（0..1），例如 0.01 表示 1%。 |
| `--slo-min-users <SLO_MIN_USERS>` | `1` | 扫描的起始并发用户数。 |
| `--slo-max-users <SLO_MAX_USERS>` | `100` | 扫描可达到的最大并发用户数。 |
| `--slo-step-strategy <SLO_STEP_STRATEGY>` | `geometric` | 扫描下一档的方式：geometric 成倍增长（1→2→4→8，适合大范围快速定位），linear 逐级递增。<br>**可选值:** `geometric`, `linear` |
| `--slo-step-turns <SLO_STEP_TURNS>` | `5` | 每一档每个用户参与测量的轮数。 |
| `--slo-step-warmup-turns <SLO_STEP_WARMUP_TURNS>` | `1` | 每档测量前，每个用户不计入统计的预热轮数。 |
| `--slo-step-timeout-s <SLO_STEP_TIMEOUT_S>` | `300` | 单档的墙钟预算；超时的档会被记为 TIMEOUT 并判定 SLO 不达标。 |
| `--slo-step-reset-cache`<br>`--no-slo-step-reset-cache` | `on` | 每档开始前清空服务端前缀缓存，让每一档都从冷缓存起步（默认开启）。 / 跨档保留缓存（测稳态复用）。 |

#### Agent Mode (only with --mode agent) {#opt-agent}

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--agent-tasks <AGENT_TASKS>` | `4` | 并发运行的编码任务数。 |
| `--agent-task-file <AGENT_TASK_FILE>` | `—` | 自定义任务的 JSON/YAML 文件（默认使用内置任务集）。 |
| `--agent-max-steps <AGENT_MAX_STEPS>` | `12` | 单个任务在被截断前的最大工具调用步数。 |
| `--agent-max-tokens <AGENT_MAX_TOKENS>` | `512` | 任务内每次模型调用的最大生成 token 数。 |
| `--agent-shell-timeout <AGENT_SHELL_TIMEOUT>` | `30` | Agent 执行的单条 shell 命令允许的最长秒数。 |
| `--agent-workdir <AGENT_WORKDIR>` | `—` | 每个任务工作区的根目录（默认使用临时目录）。 |

#### Record Mode (only with --mode record) {#opt-record}

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--upstream-endpoint <UPSTREAM_ENDPOINT>` | `—` | 需要转发到的真实 LLM 端点（环境变量：CLAWPERF_UPSTREAM_ENDPOINT）。 |
| `--proxy-port <PROXY_PORT>` | `9090` | 录制代理监听的端口。 |
| `--recording <RECORDING>` | `session.jsonl` | 录制内容写入的 JSONL 文件。 |
| `--upstream-api <UPSTREAM_API>` | `auto` | 上游端点的 API 类型（auto 表示自动识别）。<br>**可选值:** `openai`, `anthropic`, `auto` |

#### Replay Mode (only with --mode replay) {#opt-replay}

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--history-mode <HISTORY_MODE>` | `live` | live（推荐）：把服务端真实返回作为下一轮历史，保证 KV 缓存前缀对齐；verbatim：原样发送每条录制记录的 messages。<br>**可选值:** `live`, `verbatim` |

#### Trace Mode (only with --mode trace) {#opt-trace}

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--trace-file <TRACE_FILE>` | `—` | kvcache.ai 格式的 JSONL trace 文件，每行 {hash_ids, input_length, block_size?}；支持 .gz 压缩，用 '-' 表示从标准输入读取。 |
| `--cache-budget-tokens <CACHE_BUDGET_TOKENS>` | `0` | KV 缓存容量上限（token 数，0 = 不限）。要做预算扫描请改用 --budget-sweep。 |
| `--cache-budget-gb <CACHE_BUDGET_GB>` | `0.0` | 另一种写法：用 GB 指定缓存预算，会覆盖 --cache-budget-tokens，并按 --kv-bytes-per-token 换算。 |
| `--eviction-policy <EVICTION_POLICY>` | `lru` | 缓存超出预算时的块驱逐策略。<br>**可选值:** `lru`, `fifo` |
| `--trace-block-size <TRACE_BLOCK_SIZE>` | `64` | 默认块大小（token 数）；trace 行内自带 block_size 时以行内为准。 |
| `--trace-users <TRACE_USERS>` | `1` | 真实回放的会话级并发：当 trace 带 user_id/session_id 时，同时跑多少个用户/会话组；同一会话内的轮次保持有序。若 trace 没有用户标识，请改用 --concurrency 做请求级并发。 |
| `--budget-sweep` | `off` | 在多个预算档位下重复模拟，找出收益拐点（边际递减），输出「命中率-预算」曲线。 |
| `--kv-bytes-per-token <KV_BYTES_PER_TOKEN>` | `2.0` | 每个 KV 缓存 token 占用的字节数，用于 GB↔token 换算。不同模型差异很大（如 DeepSeek MLA 约 0.5，Qwen2.5 72B 约 4.0）。 |

## 产物与退出码

| 退出码 | 含义 |
|---|---|
| `0` | 基准跑完并写出结果 |
| `1` | 配置或预检错误（未开始跑基准） |
| `2` | 基准跑了但**全部**请求失败（CI 门禁） |
| `3` | 被中断（Ctrl+C）；退出前会写出部分结果 |

每次运行都会写一份 JSON 结果与旁边的 Markdown 报告。`clawperf report results.json` 可从任意结果重新生成报告，`clawperf compare a.json b.json` 可对比两次运行。

## 故障排查 {#trouble}

| 现象 | 解决 |
|---|---|
| `bash: =10000: No such file or directory` | shell 吃掉了 `--slo ttft.p99<=10000` 中的 `<`。改用 `--slo ttft.p99:10000`，或给参数加引号。 |
| `Tokenizer path '...' does not exist` | 容器内看不到该路径 —— 报错会列出父目录内容；用 `-v /mnt/model:/mnt/model:ro` 挂载。 |
| `Pre-flight: ... Connection reset by peer` | 服务端重置了这个极小探针（常见于仍在加载权重）。传输类错误会自动退避重试 3 次；加 `--no-preflight` 可完全跳过探针。 |
| `UnicodeEncodeError` on Windows | CLI 已强制 UTF-8 stdio；若第三方工具仍报错，设置 `PYTHONIOENCODING=utf-8`。 |

更多细节（含 tokenizer 后端选择）见 [README](https://github.com/ucm-system/ClawPerf#troubleshooting) 与 [端到端测试报告](E2E_TEST_REPORT.md)。
