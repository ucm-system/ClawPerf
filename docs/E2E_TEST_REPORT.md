# ClawPerf 端到端测试报告 (E2E Test Report)

**日期**: 2026-09-22
**被测服务**: vLLM-Ascend `quay.io/ascend/vllm-ascend:v0.23.0` @ `110.138.0.3:9155`
**模型**: `Qwen3-0.6B`（served as `qwen3`，`max_model_len=32768`，NPU 6 / 910B3 单卡，tool-calling 开启 `--enable-auto-tool-choice --tool-call-parser qwen3_xml`）
**客户端**: ClawPerf（本仓库源码，含本轮修复）@ Windows / Python 3.11
**单元回归**: `pytest` — **269 passed, 0 failed**（本轮新增 SLO 约束与上下文裁剪共 35 个用例）

> 原始结果 JSON/Markdown 见 `results_e2e/`（gitignored，本报告为归档摘要）。

---

## 1. 模式覆盖矩阵

| # | 模式 | 命令要点 | 结果 | 关键指标 |
|---|------|----------|------|----------|
| 1 | **scenario** | `--context-profile fresh --num-users 2 --max-turns 4` | ✅ 8/8 成功 | 前缀命中率 **71.27%**（Prometheus 实测），decode 108.3 tok/s，TTFT P50 231ms |
| 2 | **hitrate** | `--hit-rate 0.5 --num-requests 40 --prefix-num 2 --concurrency 4 --reset-cache` | ✅ 40/40 | **TARGET 50.00% vs MEASURED 49.90%**；TPOT 9.18ms（本轮修复前恒为 0） |
| 3 | **slo**（新约束语法） | `--slo ttft.p99<=1500 --slo tpot.avg<=30 --slo e2e.max<=20000` | ✅ 6 步全跑 | 容量曲线见 §2，**Max sustained users: 5**（绑定约束为 e2e.max） |
| 4 | **agent** | `--agent-tasks 2 --agent-task-file examples/agent_task_tooltest.jsonl` | ✅ 2/2 任务完成 | 10 步真实 function-calling，前缀命中率 **84.20%** |
| 5 | **trace** | ModelScope 真实 trace 34 请求 `--trace-users 3 --budget-sweep --model-context-length 32768` | ✅ 29/29 已发送全成功 | ceiling **90.42%**，TTFT P50 111ms；5 请求因输入 ≥ 32K 窗口被明确跳过（见 §3） |
| 6 | **suite** | `--suite quick`（1/4/8 users × fresh） | ✅ 130/130 | TTFT P50: 1u 203ms → 4u 290ms → 8u 379ms |
| 7 | **replay** | `--recording examples/agentic_trace_real.jsonl`，live 与 verbatim 各一遍 | ✅ 11/11 ×2 | live: TTFT P50 59.0ms / decode 107.8 tok/s |
| 8 | **record** | 录制代理 @9090，2 个 OpenAI 流式 + 2 个 Anthropic 流式请求 | ✅ 4/4 全 200 | Anthropic→OpenAI 实时互译验证通过；录制 JSONL 含 request_body + chunks |
| 9 | **record→replay 闭环** | 回放本次录制的 JSONL | ✅ 5/5 | TTFT P50 49.3ms |
| 10 | **report / compare** | `clawperf report scenario.json`、`compare hitrate.json trace.json` | ✅ | Markdown 报告 + 对比报告（含 ASCII 图） |
| 11 | **mock-server** | 本地 `clawperf-mock-server`，hitrate + scenario | ✅ 30/30、6/6 | hitrate **TARGET 50.00% vs MEASURED 49.21%**（字典树块粒度），scenario 命中率 72.23% |
| 12 | **trace-convert** | Claude Code ×3 + ShareGPT + OpenAI messages（含带 BOM 文件） | ✅ | 三种格式均转换成功；BOM 文件可读；不支持的格式报清晰错误并 exit 1 |

## 2. SLO 容量曲线（灵活约束：ttft.p99 / tpot.avg / e2e.max）

| 并发用户 | ttft.p99 | tpot.avg | e2e.max | 错误率 | SLO |
|---------|----------|----------|---------|--------|-----|
| 1 | 228.2ms | 8.6ms | 8,887.7ms | 0.0% | ✅ |
| 2 | 259.3ms | 8.8ms | 9,089.6ms | 0.0% | ✅ |
| 4 | 624.2ms | 14.7ms | 15,471.1ms | 0.0% | ✅ |
| 5 | 768.4ms | 15.1ms | 15,980.6ms | 0.0% | ✅ |
| 6 | 945.1ms | 20.9ms | 22,360.6ms | 0.0% | ❌ |
| 8 | 822.4ms | 25.5ms | 26,554.0ms | 0.0% | ❌ |

**Max sustained users: 5**。绑定约束是 `e2e.max<=20000ms`——正是混合约束才能暴露的洞察（TTFT/TPOT 在 8 用户时仍达标）。

## 3. 真实 Trace 回放与上下文裁剪

来源：`Glint-Research/Fable-5-traces` + `armand0e/kimi-k2.6-claude-code-traces`（3 会话 / 34 请求，`trace-convert` 转换）。

| 指标 | 值 |
|------|-----|
| 已发送回放成功率 | **29/29** |
| 被跳过（输入 ≥ 32K 窗口） | 5（明确报错并说明原因，不再发送必然 400 的请求） |
| 模拟 ceiling（无限预算） | **90.42%**（本轮修复 trace 转换计入 tool 块后，从 82.79% 上修） |
| 模拟 speedup（= 1/(1−r)） | 10.4× |

本轮发现并修复的两个关键问题：

1. **trace 转换的 token 估算漏计 tool 内容** —— 旧实现对 `tool_use`/`tool_result` 块视而不见，而 Claude Code 会话里这些才是主要载荷（文件内容、shell 输出）。`input_length` 低估 ~40%（1,688 vs 实际 ~31.8K）。修复后按完整 wire 内容（含 tool_calls JSON）估算。
2. **上下文裁剪闭环** —— `--model-context-length 32768` + `--tokenizer` 时：精确分词 → 剩余空间裁剪 `max_tokens`；仅输入即超窗的请求直接跳过并给出可行动的错误信息。此前这些请求会收到 vLLM 的误导性 400（其报错中的 "input tokens" 数值实为 `window+1−max_tokens` 反推值，并非真实长度——本轮用 `max_tokens=1` 探测证实）。

## 4. 本轮发现并修复的缺陷

| # | 缺陷 | 影响 | 修复 |
|---|------|------|------|
| 1 | **Windows GBK 控制台崩溃**：`clawperf --help`/摘要输出含 `↔ ✓ ✅ █`，GBK 代码页下 `UnicodeEncodeError` 直接崩溃 | 中文 Windows 用户完全不可用 | CLI 入口强制 UTF-8 stdio（`errors=replace`） |
| 2 | **hitrate 模式 TPOT 恒为 0**：evalscope 仅在其 multi-turn 路径调用 `BenchmarkData.finalize()`，hitrate 直连 `AioHttpClient.post()` 拿到的是默认值 | hitrate 报告缺一列关键指标 | 成功记录统一补调 `bd.finalize()`（幂等） |
| 3 | **trace 转换 token 低估**（见 §3） | 预算扫描/GB 换算/裁剪全部失真 | 按 wire 内容估算（tool 块 + tool_calls + 每消息开销） |
| 4 | **trace 回放超窗报错不可读** | 5/34 请求收到误导性 400 | 精确裁剪 + 溢出跳过 + 明确错误文案 |
| 5 | **trace-convert 遇不支持的格式抛裸 traceback** | CI 里不友好 | 捕获 ValueError → 干净报错 + 格式提示 + exit 1 |
| 6 | **agent shell 超时杀进程不回收**：Windows ProactorEventLoop 下留下 unclosed-transport 告警 | 告警噪音 / 资源泄漏 | kill 后 `communicate()` 收尸并关闭管道 |
| 7 | **测试不可移植**：`sleep 10` 在 Windows 不存在 | Windows 上 1 个用例必挂 | 改用 `sys.executable` 跑跨平台 sleeper |
| 8 | **配置错误抛 traceback**（如非法 `--user-arrival`、坏 SLO 约束） | 违背"exit 1 = 配置错误"的 CI 契约 | `main()` 捕获 ValueError → `[ClawPerf] configuration error: ...` + exit 1 |
| 9 | **录制代理静默追加**旧录制文件 | 多次会话悄悄混在一个文件里 | 追加时打印已有条数并提示如何重开 |
| 10 | **JSONL 读取不兼容 BOM**（Windows 工具导出的文件） | `detected unknown` 误报 | 所有外部文件读取改 `utf-8-sig` |
| 11 | **tokenizer 加载失败提示不含解法** | 用户不知可传 `--tokenizer` | 错误信息加入 `--tokenizer <path>` 提示 |
| 12 | **SLO 约束被 shell 重定向吃掉**（0.6.1）：`--slo ttft.p99<=10000` 未加引号时 bash 把 `<` 当重定向，报 `bash: =10000: No such file or directory`，ClawPerf 根本没启动 | 用户照文档复制命令即失败，且完全看不出原因 | 新增**免引号分隔符语法** `:`/`=`（等价 `<=`）与单词运算符 `le/lt/ge/gt`；单个引号串内可用逗号写多个约束；只收到裸指标名时直接说明"shell 吃掉了 `<`"并给出两种改法 |
| 13 | **布尔开关在真实命令行下全部失效**（0.6.1）：`main()` 调 `parse_args()`（argv=None），而"是否显式传了该 flag"只从显式 argv 构造、且只收集 `--` 前缀 token | `--no-preflight`、`--reset-cache`、`--metrics-samples`、`-v`、`--no-ignore-eos` 全部被静默丢弃（长跑才发现没生效） | 改从 `sys.argv[1:]` 构造；按 `_option_string_actions` 映射 dest（支持 `-v`、`--flag=value`、`-vv`）；显式 CLI 值即使等于默认值也压过 env/YAML |
| 14 | **本地 tokenizer 先走 ModelScope，日志有歧义**（0.6.1）：本地目录先试 modelscope，日志写 `Loaded tokenizer from ModelScope: /local/path`（看起来像用了远端）；路径不存在时抛 hub 异常 | 离线/NPU 机器上"本地 tokenizer 加载不上"且无从排查 | 本地目录一律 `local_files_only=True` **严格离线**（transformers 优先 → modelscope 兜底）；日志写 `local dir (transformers)` + vocab + chat_template；路径不存在时列出父目录内容；两后端都失败时列出各自错误 + 目录文件清单；补 `tokenizer.json` 直载兜底与 `CLAWPERF_TOKENIZER_BACKEND` 开关 |
| 15 | **预检探针单次失败即终止，并 dump 整段 traceback**（0.6.1）：evalscope 的 `AioHttpClient.post()` 不抛异常，而是把整段 aiohttp traceback 塞进 `bd.error` 且 `status_code=None`；旧代码按 status_code 判定重试，`None` 被当成"不可重试的 4xx" | 服务端加载权重期间的**一次**连接重置就终止整轮，并打印上百行 traceback；无任何跳过手段 | `status_code is None`（传输层失败）与 5xx 视为可重试，退避 1/2/4s、默认 3 次（`--preflight-retries`）；4xx 立即失败；报错只保留异常行（`_summarize_error`）；新增 `--no-preflight` |

## 5. 新增功能

1. **灵活 SLO 约束**（本次主要需求）：`--slo ttft.p99<=1500 --slo tpot.avg<=30 --slo e2e.max<=30000`，可重复、任意组合；旧 `--slo-ttft-ms/--slo-tpot-ms/--slo-percentile` 自动等价转换；容量曲线表/Markdown 报告/JSON 摘要均按约束动态出列；旧结果文件 `clawperf report` 仍按旧列渲染（向后兼容）。
2. **`--model-context-length` 作用于 trace 回放**：精确分词（提供 `--tokenizer` 时）→ 逐请求裁剪 `max_tokens` → 溢出请求跳过并归类为 `context overflow`。
3. **多 metrics 端点聚合**（PD 分离/多副本场景，见 §5.1）：`--metrics-endpoint` 可重复/逗号分隔/`标签=url`；计数器求和、比率取均值、per-engine 按实例分行；`--reset-cache` 对每个实例逐一重置。

## 5.1 多实例 / PD 分离指标采集（真实环境模拟验证）

PD 分离服务每个 prefill/decode 实例各暴露一个 `/metrics` 端口。为验证多端点聚合，在服务器上起了 **2 个独立 vLLM 实例**（davinci6:9155 + davinci7:9156，同 Qwen3-0.6B）和一个**轮询反代**（:9150，aiohttp 流式透传，请求交替打到两个实例）模拟单一服务入口。

| # | 场景 | 命令要点 | 结果 | 验证点 |
|---|------|----------|------|--------|
| A | 基线：单实例+单 metrics | endpoint=A, metrics=[A] | 49.90% | 与目标 50% 对齐 |
| B | 聚合数学：A 服务 + [A, B空闲] | metrics=[A,B] | **49.90%（不变）** | 空闲端点不扭曲总值；引擎表出现 `110.138.0.3:9155:0`（49.90%）与 `110.138.0.3:9156:0`（0 查询）两行 |
| C | PD 模拟：RR 代理 + [A,B] | endpoint=proxy | 47.41% | 两实例查询均分（82,082/82,080）、命中率一致；总表正确汇总 |
| D | PD 标签：`prefill=`/`decode=` | metrics=[prefill=A, decode=B] | 44.91%（20 请求） | 引擎表显示 `engine prefill:0` / `engine decode:0` + TOTAL 行 |
| E | scenario 多轮会话过代理 | 2 用户 × 4 轮 | 66.42% | per-engine 明细（66.43%/66.40%）首次落盘到 JSON |

**真实发现（RR 路由 + 实例本地缓存）**：预期 RR 会把命中率砍半（25%），实测 47.41%——前缀缓存是内容寻址、懒填充的：每个实例首次见到某前缀就自行缓存，跨实例路由只损失**重复冷启动**（每实例每前缀多一次 miss，2.5pp），而不是一半命中。对 PD 部署的启示：prefill/decode 各自的本地缓存会各自累积前缀，跨实例的 KV 迁移省的是冷启动成本，稳态命中率由内容寻址保证。逐实例引擎表正是观察这一行为的工具。

## 5.2 0.6.1 修复轮：真实用户命令复现 + 回归（`scripts/e2e_local.py` / `scripts/e2e_bash.sh`）

用户实际命令（Linux 容器内 bash）：

```bash
clawperf --mode slo --endpoint http://141.111.32.62:8000/v1 --model /mnt/model/Qwen3.5-0.8B \
  --slo ttft.p99<=10000 --slo tpot.avg<=50 --slo e2e.max<=30000 \
  --slo-min-users 1 --slo-max-users 200 --slo-step-strategy geometric --output results_slo.json
# bash: =10000: No such file or directory
```

在 **真实 bash**（WSL，`e2e_bash.sh`，`clawperf.exe` 经 interop 调用）中逐条复现：

| # | 命令行 | 结果 |
|---|--------|------|
| 1 | `--slo ttft.p99<=10000`（未加引号） | `bash: =10000: No such file or directory`（用户原报错，clawperf 未启动） |
| 2 | `--slo 'ttft.p99<=10000'`（加引号） | exit 0，`SLO=ttft.p99<=10000ms` |
| 3 | `--slo ttft.p99:10000 --slo tpot.avg:50 --slo e2e.max:30000` | exit 0，`SLO=ttft.p99<=10000ms, tpot.avg<=50ms, e2e.max<=30000ms` |
| 4 | `--slo ttft.p99`（被 shell 吃掉后剩下的） | exit 1 + 明确的"shell 吃掉了 `<`"指引（不再是无头报错） |

`scripts/e2e_local.py`（真实 mock server + 真实本地 tokenizer 目录，19/19 通过；**已接入 CI 的 `e2e` job，每次 push 都跑**）：

| # | 场景 | 结果 |
|---|------|------|
| A | scenario：`--tokenizer tokenizers/qwen3-0.6b`（本地目录） | exit 0；日志 `Loaded local tokenizer ... [local dir (transformers)] — vocab=151669, chat_template=yes`；**不出现** ModelScope 字样 |
| B | slo：`ttft.p99:10000` / `tpot.avg:50` / `e2e.max:30000` | exit 0，容量曲线正常 |
| C | slo：`--slo 'ttft.p99<=10000,tpot.avg<=50,e2e.max<=30000'`（单个引号串） | exit 0 |
| D | **连接重置的服务端**（accept 后 SO_LINGER=0 直接 RST，模拟 vLLM 加载权重中） | 探针重试 **3 次**（1s/2s 退避）→ exit 1；报错为单行 `ClientOSError: [Errno 104] Connection reset by peer` + `--no-preflight` 提示，**无 traceback dump** |
| E | 同一服务端 + `--no-preflight` | 探针被跳过，整轮正常跑完（全错 → exit 2，符合 CI 契约） |
| F | `--tokenizer /mnt/model/DoesNotExist-0.8B` | exit 1，`does not exist on this machine` + 父目录内容清单 |
| G | 产物 | `v061_scenario.json` / `v061_slo.json` 均为合法 JSON |

新增回归用例（CI 覆盖）：`tests/test_cli_args.py`（12 例，锁死布尔开关/`-v`/`=` 形式/env 优先级）、`tests/test_preflight.py`（14 例，锁死重试与错误摘要）、`tests/test_tokenizer_loading.py`（18 例，含**真实**本地 tokenizer 离线加载）、`tests/test_slo.py` 新增 26 例（免引号语法矩阵）。

## 6. 可服务性 / 易用性评估（后续建议）

**已验证良好**：
- CI 契约（exit 0/1/2）实测成立；配置错误信息可行动。
- 单一 NPU 上与其他用户容器共存无干扰（只占 davinci6）。
- mock-server 让无 GPU 环境可跑通 scenario/hitrate/slo/replay 的完整闭环，命中率目标端到端可验证（50% 目标 → 49.21% 实测，差异来自模拟器的块粒度）。
- record 代理同时讲 OpenAI 与 Anthropic 两种协议，Claude Code 可直接指向。

**建议改进（按优先级）**：
1. **ruff 版本债**：仓库按 ruff<0.15 水平写的，ruff 0.15 报 175 个存量违规（123 个 E501）。建议 pin `ruff>=0.15` 并一次性 `--fix` + 手工收尾，恢复 "lint 全绿"。
2. **trace 回放的估算兜底**：无 tokenizer 时 chars/4 对 tool 密集内容仍低估 ~11%；可考虑在 `--model-context-length` 生效但 tokenizer 不可用时打 WARNING（当前已有）并在文档强调配 `--tokenizer`。
3. **metrics-endpoint 自动推导**：`--metrics-endpoint` 未配置时静默跳过命中率采集；可默认尝试 `<endpoint>/../metrics`，失败再降级并提示。
4. **结果体积**：8 用户 × 10 轮的 JSON 达 7.6MB（含逐轮明细）；可加 `--no-detail` 开关只留摘要（CI 产物更轻）。
5. **evalscope 版本面**：`finalize()` 契约在 1.8.0 验证通过；依赖声明 `>=1.5.0`，建议收窄到实测版本区间并在 CI 矩阵里跑最低/最高版本。
6. **Windows 复现命令**：PowerShell 下带引号的 curl/json 参数会被拆分；报告统一给 `python -m clawperf` 形式（本报告同）。

## 7. 复现命令

```bash
# 环境（Windows 客户端）
export NO_PROXY="*"   # 绕过本机代理（否则内网端点 502）

# 服务端（910B3 单卡）
docker run -d --name clawperf-e2e --net=host --shm-size=50g \
  -e ASCEND_RT_VISIBLE_DEVICES=0 --device /dev/davinci6 \
  --device /dev/davinci_manager --device /dev/devmm_svm --device /dev/hisi_hdc \
  -v /usr/local/dcmi:/usr/local/dcmi \
  -v /usr/local/Ascend/driver/tools/hccn_tool:/usr/local/Ascend/driver/tools/hccn_tool \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
  -v /usr/local/Ascend/driver/lib64/:/usr/local/Ascend/driver/lib64/ \
  -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info \
  -v /etc/ascend_install.info:/etc/ascend_install.info \
  -v /root/.cache:/root/.cache -v /mnt/model:/mnt/model:ro \
  quay.io/ascend/vllm-ascend:v0.23.0 \
  vllm serve /mnt/model/Qwen3-0.6B --served-model-name qwen3 \
  --tensor-parallel-size 1 --max-model-len 32768 --max-num-batched-tokens 32768 \
  --port 9155 --gpu-memory-utilization 0.85 \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml

EP=http://110.138.0.3:9155/v1
M=http://110.138.0.3:9155/metrics
TOK=tokenizers/qwen3-0.6b

# scenario
clawperf --mode scenario --endpoint $EP --model qwen3 --tokenizer $TOK \
  --context-profile fresh --num-users 2 --max-turns 4 --max-context-tokens 30000 \
  --metrics-endpoint $M --output results_e2e/scenario.json

# hitrate
clawperf --mode hitrate --endpoint $EP --model qwen3 --tokenizer $TOK \
  --num-requests 40 --input-len 4096 --hit-rate 0.5 --prefix-num 2 \
  --output-len 32 --concurrency 4 --metrics-endpoint $M --reset-cache \
  --output results_e2e/hitrate.json

# slo（灵活约束）
clawperf --mode slo --endpoint $EP --model qwen3 --tokenizer $TOK \
  --context-profile short --max-context-tokens 30000 \
  --slo ttft.p99<=1500 --slo tpot.avg<=30 --slo e2e.max<=20000 \
  --slo-min-users 1 --slo-max-users 8 --slo-step-turns 3 --output results_e2e/slo.json

# agent
clawperf --mode agent --endpoint $EP --model qwen3 \
  --agent-tasks 2 --agent-task-file examples/agent_task_tooltest.jsonl \
  --agent-max-steps 8 --agent-max-tokens 256 \
  --metrics-endpoint $M --output results_e2e/agent.json

# trace（真实数据集回放 + 上下文裁剪）
clawperf trace-convert examples/ms_traces/fable_sample.jsonl \
  examples/ms_traces/kimi_sample_1.jsonl examples/ms_traces/kimi_sample_2.jsonl \
  --output examples/ms_traces/real_ms_traces.jsonl
clawperf --mode trace --trace-file examples/ms_traces/real_ms_traces.jsonl \
  --endpoint $EP --model qwen3 --tokenizer $TOK --trace-users 3 --budget-sweep \
  --model-context-length 32768 --output results_e2e/trace.json

# suite
clawperf --mode scenario --suite quick --endpoint $EP --model qwen3 \
  --tokenizer $TOK --max-context-tokens 30000 --output results_e2e/suite.json

# replay（live / verbatim）
clawperf --mode replay --endpoint $EP --model qwen3 \
  --recording examples/agentic_trace_real.jsonl --history-mode live \
  --output results_e2e/replay.json

# record（终端 1 起代理；终端 2 用任意 OpenAI/Anthropic 客户端发请求）
clawperf --mode record --upstream-endpoint http://110.138.0.3:9155 \
  --proxy-port 9090 --recording results_e2e/e2e_record_test.jsonl

# report / compare
clawperf report results_e2e/scenario.json
clawperf compare results_e2e/hitrate.json results_e2e/trace.json \
  --label-a hitrate --label-b trace-replay

# mock-server（无 GPU 闭环）
clawperf-mock-server --port 9100
clawperf --mode hitrate --endpoint http://127.0.0.1:9100/v1 --model mock \
  --tokenizer $TOK --num-requests 30 --input-len 2048 --hit-rate 0.5 \
  --prefix-num 2 --output-len 16 --concurrency 3 \
  --metrics-endpoint http://127.0.0.1:9100/metrics --backend vllm \
  --reset-cache --output results_e2e/mock_hitrate.json

# 多实例 / PD 模拟（2 实例 + 轮询反代，见 §5.1；脚本在 examples/pd_sim/）
# 服务端：bash examples/pd_sim/start_pd_sim.sh
#   （起 clawperf-pd-a: davinci6/9155、clawperf-pd-b: davinci7/9156、clawperf-rr: 9150 轮询代理）
clawperf --mode hitrate --endpoint http://110.138.0.3:9150/v1 --model qwen3 \
  --tokenizer tokenizers/qwen3-0.6b \
  --num-requests 40 --input-len 4096 --hit-rate 0.5 --prefix-num 2 \
  --output-len 32 --concurrency 4 \
  --metrics-endpoint prefill=http://110.138.0.3:9155/metrics \
  --metrics-endpoint decode=http://110.138.0.3:9156/metrics \
  --reset-cache --output results_e2e/pd_labels.json
```

## 8. 测试环境与注意事项

- **本机代理**: Windows 系统代理会劫持内网请求导致 502，客户端需 `NO_PROXY=*`（ClawPerf 内部 HTTP 已默认 `trust_env=False`，此处为 curl 等外部工具兜底）。
- **vLLM 配置**: tool-calling 需 `--enable-auto-tool-choice --tool-call-parser qwen3_xml`（此版本无 `qwen3`/`hermes` 之外的 Qwen3 解析器名）。
- **前缀缓存 reset**: vllm-ascend 0.23.0 无 `/reset_prefix_cache` 端点（404 警告后继续，delta 计算仍隔离窗口）。
- **模型窗口**: 本轮 `Qwen3-0.6B` 为 32K 窗口（上轮 E2E 用的是 131072 yarn 版本）；长会话尾部请求（输入 ~39.5K tokens）物理上放不进 32K，属预期跳过而非缺陷。
- **NPU 资源**: 主轮只占 davinci6；多实例模拟轮占 davinci6+davinci7（均为空闲卡）；测试结束即 `docker rm -f clawperf-pd-a clawperf-pd-b clawperf-rr`。
