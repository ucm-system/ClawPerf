# ClawPerf 端到端测试报告 (E2E Test Report)

**日期**: 2026-08-27
**被测服务**: vLLM-Ascend `quay.io/ascend/vllm-ascend:v0.23.0rc1` @ `110.138.0.3:8123`
**模型**: `Qwen3-0.6B-131072`（served as `qwen3`，yarn rope-scaling factor 3.2，`max_model_len=131072`，NPU 2 单卡，tool-calling 开启 `--tool-call-parser qwen3_xml`）
**客户端**: ClawPerf 0.6.0（本机 Windows，Python 3.11）

> 原始结果 JSON/Markdown 见 `results_e2e/`（gitignored，本报告为归档摘要）。

---

## 1. 模式覆盖矩阵

| # | 模式 | 命令要点 | 结果 | 关键指标 |
|---|------|----------|------|----------|
| 1 | **scenario** | `--context-profile fresh --num-users 2 --max-turns 4` | ✅ 8/8 成功 | 前缀命中率 **73.95%**，输出吞吐 228.6 tok/s |
| 2 | **hitrate** | `--hit-rate 0.5 --num-requests 40 --prefix-num 2 --concurrency 4` | ✅ 40/40 | **TARGET 50.00% vs MEASURED 49.90%** |
| 3 | **slo** | `--slo-ttft-ms 1500 --slo-min-users 1 --slo-max-users 8` | ✅ 8 步全过 | 容量曲线 1→8 用户（见 §2） |
| 4 | **agent** | `--agent-tasks 2 --agent-task-file examples/agent_task_tooltest.jsonl` | ✅ 2/2 任务完成 | 工具调用路径验证，前缀命中率 **42.76%** |
| 5 | **trace** | 真实 ModelScope trace 34 请求 `--trace-users 3 --budget-sweep` | ✅ 34/34 | ceiling **82.79%**，TTFT P50 109.7ms，decode 115.1 tok/s |
| 6 | **suite** | `--suite quick`（3 场景：1/4/8 users × fresh） | ✅ 130/130 | 1u: 10/10，4u: 40/40，8u: 80/80 |
| 7 | **replay** | `--recording examples/agentic_trace_real.jsonl --history-mode live` | ✅ 11/11 | TTFT P50 69.9ms，decode 114.1 tok/s |
| 8 | **record** | `--mode record` CLI 代理 + HTTP 客户端 | ✅ 200 + 33 SSE | 录制 JSONL 完整（request_body + chunks） |
| 9 | **report** | `clawperf report results_e2e/scenario.json` | ✅ | 生成 Markdown 报告（结论 + 图表） |
| 10 | **compare** | `clawperf compare hitrate.json trace.json` | ✅ | 生成对比报告 |

## 2. SLO 容量曲线（P99 TTFT ≤ 1500ms）

| 并发用户 | P99 TTFT | P99 TPOT | 错误率 | SLO |
|---------|----------|----------|--------|-----|
| 1 | 207ms | 8.2ms | 0.0% | ✅ |
| 2 | 318ms | 9.2ms | 0.0% | ✅ |
| 4 | 515ms | 15.2ms | 0.0% | ✅ |
| 8 | 743ms | 26.6ms | 0.0% | ✅ |

**Max sustained users: 8**（扫描上限内全部满足，P99 TTFT 增长接近线性）

## 3. 真实 Trace 回放（ModelScope 数据集）

来源：`Glint-Research/Fable-5-traces`（Claude Code 会话）+ `armand0e/kimi-k2.6-claude-code-traces`（2 个会话），经
`clawperf trace-convert` 转为 ClawPerf flat trace（34 请求 / 3 会话 / 累积前缀）。

| 指标 | 值 |
|------|-----|
| 回放成功率 | **34/34** |
| TTFT P50 / P95 | 109.7ms / 776ms |
| Decode | 115.1 tok/s |
| 模拟 ceiling（无限预算） | **82.79%** |
| 模拟 speedup（= 1/(1−r)） | 5.81× |

结论：真实 Agent 会话表现出极高的前缀复用性（82.79%），显著高于合成负载（scenario ~74%）。

## 4. 端到端验证覆盖的能力清单

- ✅ 全部 7 种运行模式 + 3 个子命令在真实 vLLM-Ascend 端点上工作
- ✅ 131072 长上下文（模型窗口确认）+ 40K batch 参数
- ✅ 前缀缓存命中率闭环：hitrate 目标/实测对比、scenario/slo/agent 实测 Prometheus 指标
- ✅ 工具调用（agent 模式真实 function-calling）
- ✅ 录制→回放闭环（record CLI 代理 → JSONL → replay live-history）
- ✅ 外部 trace 数据集转换 → 真实回放
- ✅ Markdown 报告与对比报告生成

## 5. 回归

- **单元测试: 234 passed**（含报告内容断言、配置分层、trace 转换/模拟/回放、agent、系统指标等 18 个测试文件）
- **ruff: 全部通过**

## 6. 复现命令

```bash
# 环境
export NO_PROXY="*"   # 绕过本机代理（否则 lab 端点 502）

# scenario
clawperf --mode scenario --endpoint http://110.138.0.3:8123/v1 --model qwen3 \
  --tokenizer tokenizers/qwen3-0.6b --context-profile fresh --num-users 2 \
  --max-turns 4 --max-context-tokens 30000 \
  --metrics-endpoint http://110.138.0.3:8123/metrics --output results_e2e/scenario.json

# hitrate
clawperf --mode hitrate --endpoint http://110.138.0.3:8123/v1 --model qwen3 \
  --tokenizer tokenizers/qwen3-0.6b --num-requests 40 --input-len 4096 \
  --hit-rate 0.5 --prefix-num 2 --output-len 32 --concurrency 4 \
  --metrics-endpoint http://110.138.0.3:8123/metrics --output results_e2e/hitrate.json

# slo
clawperf --mode slo --endpoint http://110.138.0.3:8123/v1 --model qwen3 \
  --tokenizer tokenizers/qwen3-0.6b --context-profile short --max-context-tokens 30000 \
  --slo-ttft-ms 1500 --slo-min-users 1 --slo-max-users 8 \
  --slo-step-turns 3 --output results_e2e/slo.json

# agent（需要模型文件包含固定任务）
clawperf --mode agent --endpoint http://110.138.0.3:8123/v1 --model qwen3 \
  --agent-tasks 2 --agent-task-file examples/agent_task_tooltest.jsonl \
  --agent-max-steps 8 --agent-max-tokens 256 \
  --metrics-endpoint http://110.138.0.3:8123/metrics --output results_e2e/agent.json

# trace（真实数据集回放）
clawperf trace-convert examples/ms_traces/fable_sample.jsonl examples/ms_traces/kimi_sample_1.jsonl \
  examples/ms_traces/kimi_sample_2.jsonl --output examples/ms_traces/real_ms_traces.jsonl
clawperf --mode trace --trace-file examples/ms_traces/real_ms_traces.jsonl \
  --endpoint http://110.138.0.3:8123/v1 --model qwen3 \
  --trace-users 3 --budget-sweep --output results_e2e/trace.json

# suite
clawperf --mode scenario --suite quick --endpoint http://110.138.0.3:8123/v1 \
  --model qwen3 --tokenizer tokenizers/qwen3-0.6b --max-context-tokens 30000 \
  --output results_e2e/suite.json

# replay
clawperf --mode replay --endpoint http://110.138.0.3:8123/v1 --model qwen3 \
  --recording examples/agentic_trace_real.jsonl --history-mode live \
  --output results_e2e/replay.json

# record（终端 1 起代理，终端 2 发请求）
clawperf --mode record --upstream-endpoint http://110.138.0.3:8123 \
  --proxy-port 9092 --recording examples/e2e_record_test.jsonl

# report / compare
clawperf report results_e2e/scenario.json
clawperf compare results_e2e/hitrate.json results_e2e/trace.json
```

## 7. 测试环境与注意事项

- **本机代理**: Windows 系统代理（127.0.0.1:7892）会劫持非公网请求导致 502，所有请求需 `NO_PROXY=*` 或客户端 `trust_env=False`（ClawPerf 内部已默认关闭 trust_env）。
- **vLLM 配置**: tool-calling 需要 `--enable-auto-tool-choice --tool-call-parser qwen3_xml`（此版本无 `qwen3` 解析器名）。
- **前缀缓存 reset**: vllm-ascend 0.23 无 `/reset_prefix_cache` 端点（404 提示后继续，delta 计算仍隔离窗口）。