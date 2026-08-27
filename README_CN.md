# ClawPerf

[![PyPI Version](https://img.shields.io/pypi/v/clawperf.svg)](https://pypi.org/project/clawperf/)
[![Python Versions](https://img.shields.io/pypi/pyversions/clawperf.svg)](https://pypi.org/project/clawperf/)
[![License](https://img.shields.io/pypi/l/clawperf.svg)](https://github.com/ucm-system/ClawPerf/blob/main/LICENSE)

面向 LLM 推理服务（vLLM / SGLang / MindIE / vllm-ascend）的性能基准测试工具，聚焦**真实 Agent 工作负载**：多轮对话、长上下文、前缀缓存密集流量。

[English](README.md)

基于 [EvalScope](https://github.com/modelscope/evalscope) 的 perf 基础设施，ClawPerf 衡量推理栈在真实编码 Agent 冲击下的表现：上下文增长、轮次间共享前缀、工具调用、并发会话。

## 特性

**7 种基准模式，统一 CLI：**

| 模式 | 作用 |
|------|------|
| `scenario`（默认） | 多轮长上下文负载：N 个用户各自维护独立增长的对话（系统前缀 + 用户前缀 + 历史 + 当前输入），带追加式压缩。核心 Agent 负载模拟器。 |
| `hitrate` | 受控前缀缓存命中率测试：构造 `[共享前缀][边界][唯一后缀]` 提示，预填充后对比**目标 vs 实测**命中率（取自服务端 Prometheus 计数器）。 |
| `slo` | SLO 驱动的容量扫描：几何爬坡 + 二分精化，找出满足 P{百分位} TTFT/TPOT 的**最大并发用户数**。 |
| `agent` | 真实编码 Agent：模型通过 OpenAI 工具调用真实读写文件、执行 shell，跨多轮增长上下文。 |
| `trace` | KV-cache 命中率分析 + 真实回放：本地模拟块级前缀缓存（LRU/FIFO 驱逐、预算扫描）；trace 含 messages 时对端点发真实请求。 |
| `record` | 录制代理：坐在真实 Agent（Claude Code 等）与 LLM 端点之间，把每个请求/响应往返录成 JSONL。 |
| `replay` | 回放录制的 JSONL 到任意端点，支持 live-history 模式（把真实响应回填历史，保证跨模型 KV-cache 前缀对齐）。 |

**3 个子命令：**

| 命令 | 用途 |
|------|------|
| `clawperf report` | 从结果 JSON 重新生成 Markdown 报告（结论 + ASCII 图表 + 自动发现）。 |
| `clawperf compare` | 两个结果 JSON 并排对比（TTFT/decode/命中率）。 |
| `clawperf trace-convert` | 把外部 Agent trace 数据集（Claude Code 会话、ShareGPT、OpenAI messages）转换为可回放 trace。 |

**其他能力：** 无需 LLM 即可跑通命令行流程的 `clawperf-mock-server`（FastAPI 模拟 LLM，带 trie 前缀缓存模拟与 vLLM 风格 `/metrics`）；用户到达调度（burst/steady/Poisson）；推理 token（thinking）检测；连续失败提前中止；CI 友好退出码（0 成功 / 1 配置错误 / 2 全部失败 / 3 中断）；分层配置 **CLI 参数 > `CLAWPERF_*` 环境变量 > YAML（`--config`）> 默认值**。

## 安装

```bash
pip install clawperf                      # 核心（scenario / hitrate / slo / trace）
pip install "clawperf[agent]"             # + 真实 Agent 模式（openai SDK）
pip install "clawperf[record]"            # + 录制代理（fastapi/uvicorn）
pip install "clawperf[mock-server]"       # + 模拟 LLM 服务
pip install "clawperf[dev]"               # + 开发工具
```

源码安装：

```bash
git clone https://github.com/ucm-system/ClawPerf.git
cd ClawPerf
pip install -e ".[dev]"
```

## 快速开始

以下示例假设已有 vLLM 风格端点（`http://localhost:8000/v1`）。

### scenario — 多用户长上下文负载

```bash
clawperf \
  --endpoint http://localhost:8000/v1 \
  --model qwen2.5-72b \
  --context-profile medium \        # 命名档位：sys=28K + usr=10K + in=5K
  --num-users 8 \
  --max-turns 20 \
  --metrics-endpoint http://localhost:8000/metrics \
  --output results.json
```

或使用预置套件（依次运行多个 users × profile 场景）：

```bash
clawperf --endpoint http://localhost:8000/v1 --model qwen2.5-72b \
  --suite standard --output results_suite.json
```

### hitrate — 受控前缀缓存命中率

```bash
clawperf --mode hitrate \
  --endpoint http://localhost:8000/v1 --model qwen2.5-72b \
  --num-requests 100 --input-len 4096 --output-len 128 \
  --hit-rate 0.5 \                  # 目标 50%（或用 --prefix-len 2048）
  --prefix-num 10 \
  --metrics-endpoint http://localhost:8000/metrics --backend vllm \
  --reset-cache
```

摘要输出**目标 vs 实测**命中率（实测来自 `vllm:prefix_cache_hits_total`/`queries_total` 差值）及按引擎分解。

### slo — SLO 约束下最大并发

```bash
clawperf --mode slo \
  --endpoint http://localhost:8000/v1 --model qwen2.5-72b \
  --slo-ttft-ms 500 --slo-tpot-ms 30 \   # P99 必须 ≤ 这些值
  --slo-min-users 1 --slo-max-users 200 \
  --slo-step-strategy geometric \
  --output results_slo.json
```

输出：容量曲线（用户数 vs P99 TTFT/TPOT/错误率/SLO 是否满足）与最大可支撑用户数。

### agent — 真实编码 Agent

要求后端支持工具调用（如 `vllm serve ... --enable-auto-tool-choice --tool-call-parser qwen3_xml`）。

```bash
clawperf --mode agent \
  --endpoint http://localhost:8000/v1 --model qwen3 \
  --agent-tasks 10 \
  --agent-max-steps 12 --agent-max-tokens 512 \
  --metrics-endpoint http://localhost:8000/metrics --backend vllm
```

自定义任务用 `--agent-task-file`（每行一个 `{"prompt", "workspace": {"path":"content"}, "max_steps"}`）。

### trace — KV-cache 分析 + 真实回放

```bash
# 仅本地模拟（无需端点）：给定预算下的命中率，以及找拐点的预算扫描。
clawperf --mode trace --trace-file trace.jsonl --budget-sweep

# trace 带 messages → 同时对端点发真实请求回放。
clawperf --mode trace \
  --trace-file trace.jsonl \
  --endpoint http://localhost:8000/v1 --model qwen3 \
  --trace-users 3                    # 会话级并发
```

### record & replay — 录制真实 Agent 会话再回放

```bash
# 终端 1：启动录制代理（Agent 把 base URL 指向这里）
clawperf --mode record --upstream-endpoint http://localhost:8000 \
  --proxy-port 9090 --recording session.jsonl

# 把 Claude Code 指向代理，工作一会儿，Ctrl+C。
# 终端 2：用 live 历史模式回放到任意端点。
clawperf --mode replay \
  --recording session.jsonl \
  --endpoint http://localhost:8000/v1 --model qwen3 \
  --history-mode live
```

### report & compare

```bash
clawperf report results.json                       # → results.md
clawperf compare run_a.json run_b.json --label-a vLLM --label-b SGLang
```

## Trace 数据集支持

ClawPerf 支持 Agent 生态的主流 trace 格式：

| 格式 | 结构 | 代表数据集 |
|------|------|-----------|
| **kvcache.ai**（原生） | `{hash_ids, input_length, block_size?, user_id?}` | kvcache.ai 命中率模拟器 |
| **Claude Code 会话** | 每行一条消息（Anthropic content blocks） | Fable-5-traces、kimi-k2.6-claude-code-traces |
| **ShareGPT / Hermes** | `{conversations: [{from: human\|gpt\|system, value}]}` | vLLM 与 LMCache 基准、carnice、CodexBench |
| **OpenAI messages** | `{messages: [{role, content, tool_calls}]}` | 通用 API 导出 |

外部数据集先转换再回放：

```bash
clawperf trace-convert session.jsonl sharegpt.jsonl \
  --output trace.jsonl --max-turns 4
```

ModelScope 上可直接体验的数据集：`Glint-Research/Fable-5-traces`、`armand0e/kimi-k2.6-claude-code-traces`、`kai-os/carnice-glm5-hermes-traces`、`Inferact/codex_swebenchpro_traces` 等（Claude Code 与 ShareGPT 格式均已实测验证）。

## 配置

优先级：**CLI 参数（显式传入）> `CLAWPERF_*` 环境变量 > YAML（`--config`）> dataclass 默认值。**

```bash
export CLAWPERF_ENDPOINT=http://localhost:8000/v1
export CLAWPERF_MODEL=qwen3
export CLAWPERF_MAX_TURNS=20
clawperf --config config.yaml
```

示例 `config.yaml`：

```yaml
mode: scenario
context_profile: medium
num_users: 8
max_turns: 20
metrics_endpoint: http://localhost:8000/metrics
backend: vllm
```

### 上下文档位与套件

| Profile | sys+usr+in（tokens） |  | Suite | users × profiles |
|---------|----------------------|--|-------|------------------|
| `fresh` | 7K |  | `quick` | [1,4,8] × fresh |
| `short` | 22K |  | `standard` | [1,8,16,32] × medium+long |
| `medium` | 43K |  | `full` | [1,4,8,16,32,64] × fresh→full |
| `long` | 75K |  | `hitrate` | [1] × fresh→full |
| `full` | 105K |  |  |  |
| `xl` | 205K |  |  |  |
| `xxl` | 392K |  |  |  |

`--model-context-length` 会跳过基础上下文超出模型窗口的档位。

### 各模式关键参数

| 模式 | 核心参数 |
|------|----------|
| 全部 | `--endpoint --model --api-key --request-timeout --output --verbose --config` |
| scenario | `--num-users --user-arrival --context-profile` 或原生 `--system-prefix-tokens/--user-prefix-tokens/--input-tokens-per-turn`，`--max-turns --max-context-tokens --compaction-prefix-increment --suite --max-consecutive-failures` |
| hitrate | `--num-requests --input-len --output-len --hit-rate` 或 `--prefix-len`，`--prefix-num --prefill/--no-prefill --seed` |
| slo | `--slo-ttft-ms/--slo-tpot-ms --slo-percentile --slo-error-rate --slo-min-users --slo-max-users --slo-step-*` |
| agent | `--agent-tasks --agent-task-file --agent-max-steps --agent-max-tokens --agent-shell-timeout --agent-workdir` |
| record | `--upstream-endpoint --proxy-port --recording --upstream-api` |
| replay | `--recording --history-mode live\|verbatim` |
| trace | `--trace-file --cache-budget-tokens/--cache-budget-gb --eviction-policy --trace-block-size --budget-sweep --trace-users --kv-bytes-per-token` |
| 共享并发 | `--concurrency`（请求级：hitrate/replay/trace）；`--trace-users`（会话级：trace） |
| 指标 | `--metrics-endpoint --metrics-interval --metrics-samples --reset-cache --backend` |

## 输出

每次运行生成：
- **JSON**（`--output`，默认 `results_<timestamp>.json`）— 配置、摘要、按用户/按轮明细（模式相关）、系统指标、时间线。
- **Markdown 报告**（`<output>.md`）— 结论 ✅/⚠️/❌、自动关键发现、各模式汇总表、ASCII TTFT 缩放图；trace 模式含预算扫描与真实回放小节。

示例结论：

```markdown
## Verdict: ✅ GOOD

- **TTFT (P50):** 180ms — instant (GOOD)
- **Decode throughput:** 114.8 tok/s — smooth (GOOD)
```

### 结果历史

每次运行向 `clawperf_history.jsonl` 追加一行紧凑记录（配置 + 摘要 + 按用户聚合，不含逐轮大数组），可用 `jq` 查询：

```bash
tail -n1 clawperf_history.jsonl | jq '.summary.prefix_cache_token_hit_rate'
```

## 架构

| 模块 | 职责 |
|------|------|
| `cli.py` | argparse 入口；模式分发；子命令（report/compare/trace-convert）；退出码 |
| `config.py` | `BenchmarkConfig`；分层配置（CLI > env > YAML）；校验 |
| `context_profiles.py` | 命名上下文档位与套件 |
| `runner.py` | `BenchmarkRunner`：scenario/hitrate/slo/agent 编排、结果落盘 |
| `context.py` | `UserContext`：上下文组装 + 带死循环防护的压缩 |
| `scheduler.py` | burst/steady/Poisson 用户到达生成器 |
| `player.py` | `ReplayPlayer`：流式回放引擎（live/verbatim、会话级并发） |
| `trace_simulator.py` | 前缀缓存模拟（LRU/FIFO、预算扫描）+ trace 真实回放（复用 player） |
| `trace_converter.py` | 外部 trace 转换（Claude Code / ShareGPT / OpenAI） |
| `recorder.py` | 录制代理（FastAPI，Anthropic↔OpenAI 在线翻译） |
| `translators.py` | Anthropic↔OpenAI 消息/工具/SSE 翻译、端点归一化 |
| `agent.py` | 真实编码 Agent 循环（工具调用 + 推理 token 检测） |
| `agent_tasks.py` | 预置 Agent 任务库与工作区物化 |
| `system_metrics.py` | Prometheus 轮询、前缀缓存差值计算（HBM+外部、按引擎） |
| `mock_server.py` | 独立模拟 LLM 服务（trie 前缀缓存、`/metrics`） |
| `report.py` | Markdown 报告、结论、对比 |

## 测试哲学

ClawPerf 模拟**真实 Agent 系统的工作负载**——不是单次 API 调用，而是持续多轮对话挤压推理后端：

- **前缀缓存有效性**——跨轮 token 级复用（单请求基准无法测量）。
- **压缩压力**——上下文到达窗口上限时系统如何恢复。
- **延迟退化**——上下文从 7K 增长到 100K+ 时 TTFT/TPOT 的变化。
- **并发压力**——独立用户会话产生的混合前缀状态。
- **真实 trace**——回放真实 Agent 会话（Claude Code、ShareGPT、Codex），让堆栈承受 Agent 产生的确切访问模式。

## 端到端测试报告

完整端到端测试（vLLM-Ascend 端点，覆盖全部 7 种模式 + 3 个子命令，含真实 ModelScope trace 回放）见 [docs/E2E_TEST_REPORT.md](docs/E2E_TEST_REPORT.md)。各模式原始结果在 `results_e2e/`。

## 开发

```bash
pip install -e ".[dev]"
pytest
ruff check src/
```

## License

Apache License 2.0