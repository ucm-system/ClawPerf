# ClawPerf

[![CI](https://github.com/ucm-system/ClawPerf/actions/workflows/ci.yml/badge.svg)](https://github.com/ucm-system/ClawPerf/actions/workflows/ci.yml)
[![Release](https://github.com/ucm-system/ClawPerf/actions/workflows/release.yml/badge.svg)](https://github.com/ucm-system/ClawPerf/actions/workflows/release.yml)
[![Site](https://img.shields.io/badge/site-ucm--system.github.io-blue)](https://ucm-system.github.io/ClawPerf/)
[![PyPI Version](https://img.shields.io/pypi/v/clawperf.svg)](https://pypi.org/project/clawperf/)
[![Python Versions](https://img.shields.io/pypi/pyversions/clawperf.svg)](https://pypi.org/project/clawperf/)
[![License](https://img.shields.io/pypi/l/clawperf.svg)](https://github.com/ucm-system/ClawPerf/blob/main/LICENSE)

面向 LLM 推理服务（vLLM / SGLang / MindIE / vllm-ascend）的性能基准测试工具，聚焦**真实 Agent 工作负载**：多轮对话、长上下文、前缀缓存密集流量。

📖 **[项目主页](https://ucm-system.github.io/ClawPerf/)**（中英双语，含工作负载与流水线示意图） · [English](README.md)

基于 [EvalScope](https://github.com/modelscope/evalscope) 的 perf 基础设施，ClawPerf 衡量推理栈在真实编码 Agent 冲击下的表现：上下文增长、轮次间共享前缀、工具调用、并发会话。

## 特性

**7 种基准模式，统一 CLI：**

| 模式 | 作用 |
|------|------|
| `scenario`（默认） | 多轮长上下文负载：N 个用户各自维护独立增长的对话（系统前缀 + 用户前缀 + 历史 + 当前输入），带追加式压缩。核心 Agent 负载模拟器。 |
| `hitrate` | 受控前缀缓存命中率测试：构造 `[共享前缀][边界][唯一后缀]` 提示，预填充后对比**目标 vs 实测**命中率（取自服务端 Prometheus 计数器）。 |
| `slo` | SLO 驱动的容量扫描：几何爬坡 + 二分精化，找出满足目标约束的**最大并发用户数** —— `ttft`/`tpot`/`e2e` × `avg`/`P50`/`P90`/`P99`/`max` 任意组合。 |
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

说明：
- **Windows**：开箱即用 —— ClawPerf 强制 UTF-8 控制台输出，帮助文本与报告（✓/✅/█）在 GBK 代码页下不再崩溃；JSONL 读取兼容带 BOM 的文件。
- **无 GPU / CI**：`clawperf-mock-server` 提供完整假端点（字典树前缀缓存 + `/metrics`）—— 除 `agent`/`trace` 真实回放外的所有模式都能跑，命中率目标可端到端验证（见 E2E 报告）。

### 容器镜像

每次发版都会发布多架构镜像（`linux/amd64` + `linux/arm64`，含 Ascend/aarch64 主机），预装全部可选依赖：

```bash
docker pull ghcr.io/ucm-system/clawperf:latest
docker pull ghcr.io/ucm-system/clawperf:0.6.0        # 固定版本

# 压测宿主机上的服务（host 网络让 127.0.0.1 可用）
docker run --rm --net=host -v "$PWD/results:/app/results" \
  ghcr.io/ucm-system/clawperf:0.6.0 \
  --mode scenario --endpoint http://127.0.0.1:8000/v1 --model qwen3 \
  --output /app/results/run.json
```

以非 root 用户运行，内置 `examples/` 示例 trace 与本地 tokenizer，运行历史写入 `/app/results` 卷。

**离线/内网安装** —— 每次发版还会附上按架构打包的镜像包：

```bash
gunzip -c clawperf-0.6.0-linux-amd64.tar.gz | docker load   # 或 -linux-arm64.tar.gz
docker images | grep clawperf
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

约束可自由组合：任意时延指标（`ttft` / `tpot` / `e2e`）× 任意统计量（`avg`、`min`、`max`、`p25`、`p50`、`p75`、`p90`、`p95`、`p99`、`p99.9` …）× 任意比较符（`<=`、`<`、`>=`、`>`），单位毫秒。`--slo` 可重复指定，多个约束之间为**与**关系：

```bash
clawperf --mode slo \
  --endpoint http://localhost:8000/v1 --model qwen2.5-72b \
  --slo ttft.p99<=500 --slo tpot.avg<=30 --slo e2e.max<=30000 \
  --slo-min-users 1 --slo-max-users 200 \
  --slo-step-strategy geometric \
  --output results_slo.json
```

旧写法依然支持（内部自动转换为 `ttft.p99<=X` 形式）：

```bash
clawperf --mode slo ... --slo-ttft-ms 500 --slo-tpot-ms 30 --slo-percentile 0.99
```

输出：容量曲线（每个约束一列：用户数 × 各约束值 × SLO 判定）与最大可支撑用户数。真实 vLLM-Ascend 端点上的示例：

```
| Users | ttft.p99 | tpot.avg |   e2e.max | Error | SLO |
|     1 |  228.2ms |    8.6ms |  8887.7ms |  0.0% |  ✓  |
|     4 |  624.2ms |   14.7ms | 15471.1ms |  0.0% |  ✓  |
|     6 |  945.1ms |   20.9ms | 22360.6ms |  0.0% |  ✗  |
SLO: ttft.p99<=1500ms, tpot.avg<=30ms, e2e.max<=20000ms
Max sustained users: 5
```

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
# --model-context-length 会把每个请求的 max_tokens 裁剪到剩余窗口
# （给了 --tokenizer 时精确分词），仅输入就超窗的请求会被明确跳过。
clawperf --mode trace \
  --trace-file trace.jsonl \
  --endpoint http://localhost:8000/v1 --model qwen3 \
  --model-context-length 32768 \
  --trace-users 3                    # 会话级并发
```

### record & replay — 录制真实 Agent 会话再回放

```bash
# 终端 1：启动录制代理（Agent 把 base URL 指向这里）。
# 同时接受 OpenAI（/v1/chat/completions）与 Anthropic（/v1/messages）客户端，
# Anthropic→OpenAI 实时互译。录制文件跨重启追加（会提示保留了已有条数）。
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
| slo | `--slo <指标>.<统计量><运算符><毫秒>`（可重复；ttft/tpot/e2e × avg/min/max/p25…p99.9），或旧式 `--slo-ttft-ms/--slo-tpot-ms --slo-percentile`；`--slo-error-rate --slo-min-users --slo-max-users --slo-step-*` |
| agent | `--agent-tasks --agent-task-file --agent-max-steps --agent-max-tokens --agent-shell-timeout --agent-workdir` |
| record | `--upstream-endpoint --proxy-port --recording --upstream-api` |
| replay | `--recording --history-mode live\|verbatim` |
| trace | `--trace-file --cache-budget-tokens/--cache-budget-gb --eviction-policy --trace-block-size --budget-sweep --trace-users --kv-bytes-per-token --model-context-length` |
| 共享并发 | `--concurrency`（请求级：hitrate/replay/trace）；`--trace-users`（会话级：trace） |
| 指标 | `--metrics-endpoint`（可重复 / 逗号分隔；支持 `名称=url` 标签）`--metrics-interval --metrics-samples --reset-cache --backend` |
| 节奏控制 | `--user-arrival`（会话**加入**时机）与 `--request-rate`（请求/秒，开环） |

### 请求频率：开环 vs 闭环

三个容易混淆的旋钮：

| 旋钮 | 控制什么 | 语义 |
|------|----------|------|
| `--user-arrival burst\|steady:<秒>\|poisson:<λ>` | 每个**会话/用户何时加入**压测 | 加入后该用户各轮请求背靠背发送 |
| `--concurrency N` | **闭环**在途请求上限（hitrate / replay / trace） | 一个请求完成才发下一个 —— 服务端自身限速 |
| `--request-rate R` | **开环**请求发出速率（req/s） | 按泊松过程以 R req/s 发请求，**与是否完成无关**（等同 `benchmark_serving --request-rate` 语义） |

闭环回答"服务端在 N 并发下能跑多快"；开环回答"当流量以 R req/s 到达时会发生什么"——两者不可互换，因为闭环永远不会压垮服务端，开环会。

```bash
# 40 个请求以 2 req/s（泊松）到达 —— 不限制在途数量
clawperf --mode hitrate --endpoint http://localhost:8000/v1 --model qwen3 \
  --num-requests 40 --input-len 4096 --hit-rate 0.5 \
  --request-rate 2
```

设置 `--request-rate` 后 `--concurrency` 会被忽略（真开环），摘要会给出目标 vs 实测速率与发送偏差，例如 `Release Skew avg/max 1.2 / 8.4 ms`。适用于 `hitrate`、`replay` 与 `trace` 真实回放；`scenario`/`slo`/`agent` 保持闭环多轮语义（那正是 Agent 负载模型 —— Agent 在上一个请求返回后立刻发下一个）。

### 多实例 / PD 分离服务的指标采集

PD 分离（以及普通多副本）服务会**每个实例暴露一个 `/metrics` 端口**。把它们全部传入——ClawPerf 并发轮询所有端点并聚合成一个全局视图：计数器求和、比率类指标取均值、per-engine 明细按实例分行（引擎号带端点命名空间）：

```bash
clawperf --mode scenario \
  --endpoint http://lb:9000/v1 --model qwen3 \
  --metrics-endpoint prefill=http://10.0.0.1:9101/metrics \
  --metrics-endpoint decode=http://10.0.0.2:9102/metrics
```

```
|            Engine | Query Tokens | Hit Tokens | Hit Rate |
| engine prefill:0  |       41,427 |     27,520 |   66.43% |
| engine decode:0   |       40,287 |     26,752 |   66.40% |
|            TOTAL  |       81,714 |     54,272 |   66.42% |
```

`--metrics-endpoint` 可重复指定，也接受逗号分隔列表和 `标签=url`（默认标签为 host:port）。`--reset-cache`（含 SLO 每步重置）会对每个实例的 reset 端口逐一重置。PD 部署中前缀缓存命中通常发生在 prefill 实例——这张表能直接看出复用发生在哪里。

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
ruff check src/ tests/
```

### CI

| 工作流 | 触发条件 | 作用 |
|--------|----------|------|
| [`ci.yml`](.github/workflows/ci.yml) | push 到 `main`、PR | `ruff check`；Linux（3.10–3.13）+ Windows/macOS 全量测试；打包烟测（构建 → `twine check` → 干净 venv 安装 wheel → 跑两个入口命令）；amd64 与 arm64 **原生**镜像构建 + 镜像内功能自检 |
| [`release.yml`](.github/workflows/release.yml) | 打 `v*` tag（或手动触发） | 测试门禁 → sdist + wheel → **PyPI** → 原生构建 `linux/amd64` 与 `linux/arm64` 镜像并推送 ghcr.io → 多架构 manifest → 创建 GitHub Release 并附上全部制品 |
| [`pages.yml`](.github/workflows/pages.yml) | push 到 `main` 且改动 `docs/` | 校验站点（资源路径、标签闭合、SVG XML）并部署到 GitHub Pages |

### 项目主页

主页源码在 `docs/`，由 `pages.yml` 部署到 **https://ucm-system.github.io/ClawPerf/**。

```bash
python3 scripts/check_site.py docs     # 推送前校验（资源、标签闭合、SVG XML）
python3 -m http.server -d docs 8000    # 本地预览 http://localhost:8000
```

它是单个自包含的 `index.html`（无构建步骤、无 CDN、无外部字体），示意图为 `docs/assets/` 下的内联 SVG，支持中英切换与明暗主题。新增示意图只需把 SVG 放进 `docs/assets/` 并引用 —— 校验脚本会保证每个引用都能解析。

一次性配置：**Settings → Pages → Build and deployment → Source = GitHub Actions**。

### 发版流程

发版由 tag 驱动 —— 改版本号、打 tag、推送即可：

```bash
# 1. 修改 src/clawperf/__init__.py  __version__ = "0.7.0"
# 2. 提交后打 tag 并推送
git commit -am "chore: release v0.7.0"
git tag v0.7.0 && git push origin main v0.7.0
```

`verify` 任务会在 tag 与 `clawperf.__version__` 不一致时立即失败，两者不可能悄悄错位。

随后一次性产出：

| 位置 | 内容 |
|------|------|
| **PyPI** | `clawperf==<版本>`（wheel + 源码包）—— 仅正式版 |
| **ghcr.io** | 多架构镜像 `:<版本>`、`:<主.次>`、`:latest` |
| **GitHub Release** | `clawperf-<v>-py3-none-any.whl`、`clawperf-<v>.tar.gz`、`clawperf-<v>-linux-amd64.tar.gz`、`clawperf-<v>-linux-arm64.tar.gz`、`SHA256SUMS` |

镜像 tag：`:<版本>`、`:<主.次>`、`:latest`（预发布 tag 如 `v0.7.0-rc1` 会产出镜像与 Release 制品，但**不移动 `latest`**，也**不推 PyPI**）。镜像**按架构原生构建** —— amd64 用 `ubuntu-latest`，arm64 用 `ubuntu-24.04-arm`，全程不涉及 QEMU 模拟；若 ARM runner 不可用，可手动触发并传 `arm_runner: ubuntu-latest`。

#### PyPI 凭据

`pypi` 任务会按当前配置自动选择认证方式，切换时无需改代码：

1. **API token**（本仓库采用）：存为仓库 secret `PYPI_API_TOKEN` ——
   ```bash
   gh secret set PYPI_API_TOKEN --repo ucm-system/ClawPerf   # 粘贴 pypi-... token
   ```
2. **Trusted Publishing**（无需长期密钥）：在 PyPI 项目 → *Publishing* 添加发布者（owner `ucm-system`、repository `ClawPerf`、workflow `release.yml`），然后删除该 secret。当 `PYPI_API_TOKEN` 不存在时，工作流会自动回退到 OIDC。

上传使用 `skip-existing`，重复执行发版不会因版本已存在而失败。

一次性仓库配置：**Settings → Actions → General → Workflow permissions → Read and write**（`GITHUB_TOKEN` 需要该权限才能推 ghcr.io）。

#### 让镜像可被匿名拉取

ghcr 的包**默认是私有的**，未登录的 `docker pull` 会失败。开关在包自己的设置页上：

1. 打开包的落地页 —— 由仓库工作流发布的包，用**仓库侧**地址：
   `https://github.com/<owner>/<repo>/pkgs/container/clawperf`
   （从仓库页面的 *Packages* 区域，或组织的 *Packages* 列表进入）
2. 右侧点击 **Package settings**
3. 页面底部 **Danger Zone** → **Change visibility** → **Public**

以下几点已在真实的组织级包上验证过：

- `release.yml` 推送的包**确实已链接到仓库**（API 返回 `repository.full_name`），尽管 GitHub 文档说组织级包默认不链接。
- 对这类包，**组织级包页面不提供可见性开关**，REST API 也改不了：即便用带 `packages: write` 的 token，`PATCH /orgs/<org>/packages/container/<name>` 也返回 `404 Not Found`。请用上面的仓库侧页面。
- 一旦改为公开，后续发版会保持公开（可见性属于包本身，不属于某个版本）。

想用命令行确认包的状态（需要 `packages` 权限，普通 `repo` token 没有）：

```bash
gh auth refresh -s read:packages,write:packages
gh api /orgs/<org>/packages/container/clawperf \
  --jq '{visibility, repository: .repository.full_name, owner: .owner.login}'
```

`release.yml` 也会尝试自动修改可见性，无权限时给出警告并提示手工路径。

## License

Apache License 2.0