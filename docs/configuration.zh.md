---
description: 上下文档位、套件、施压旋钮与指标端点。
---

# 你真正会动的几个旋钮

其余全部内容 —— 所有参数、默认值与可选值 —— 都在[完整参考](reference.zh.md#params)里，由 `clawperf --help` 自动生成。

## 上下文档位

一个档位同时设定共享系统前缀、每用户前缀与每轮输入三个数字，免去自己拼 token 数。档位名大小写不敏感。

| 档位 | 系统前缀 | 用户前缀 | 每轮输入 | 基础上下文 | 约 |
|---|---|---|---|---|---|
| `fresh` | 4,000 | 1,500 | 1,500 | **7,000** | ~7K |
| `short` | 14,000 | 5,000 | 3,000 | **22,000** | ~22K |
| `medium` | 28,000 | 10,000 | 5,000 | **43,000** | ~43K |
| `long` | 50,000 | 18,000 | 7,000 | **75,000** | ~75K |
| `full` | 72,000 | 25,000 | 8,000 | **105,000** | ~105K |
| `xl` | 150,000 | 45,000 | 10,000 | **205,000** | ~205K |
| `xxl` | 300,000 | 80,000 | 12,000 | **392,000** | ~392K |

![上下文如何构成：共享系统前缀、用户前缀、不断增长的历史与最新输入](assets/context_model.svg)

!!! note

    也可以直接用原始数字：`--system-prefix-tokens`、`--user-prefix-tokens`、`--input-tokens-per-turn`。档位只是把这三个一起覆盖掉。

## 套件

套件按序跑完（并发 × 档位）的笛卡尔积，每个场景各写一份结果文件。`--model-context-length` 会跳过放不进模型窗口的档位。

| 套件 | 并发用户 | 档位 | 轮数 | 每轮输出 | 场景数 |
|---|---|---|---|---|---|
| `quick` | 1, 4, 8 | `fresh` | 10 | 256 | 3 |
| `standard` | 1, 8, 16, 32 | `medium` + `long` | 20 | 512 | 8 |
| `full` | 1, 4, 8, 16, 32, 64 | `fresh` → `short` → `medium` → `long` → `full` | 30 | 512 | 30 |
| `hitrate` | 1 | `fresh` → `short` → `medium` → `long` → `full` | 5 | 128 | 5 |

```bash title="bash"
clawperf --mode scenario --context-profile medium --num-users 8 ...

# sweep profiles x users
clawperf --mode scenario --suite full --model-context-length 32768 ...
```

## 节奏与并发

四个容易混淆的旋钮。关键区别：闭环永远压不垮服务端，开环可以。

| 旋钮 | 控制什么 | 语义 |
|---|---|---|
| `--user-arrival` | 每个**会话**何时加入 | 加入后各自连续跑自己的轮次 |
| `--concurrency` | **闭环**：在途请求上限 | 上一个返回才发下一个 —— 节奏由服务端决定 |
| `--request-rate` | **开环**：每秒发送速率 | 按泊松过程发送，与是否完成无关 —— 只有它会真正压垮服务端 |
| `--trace-users` | trace 回放的会话级并发 | 同一会话内的轮次保持有序 |

![三种会话到达形态：burst、steady 与 poisson](assets/arrival_patterns.svg)

## 指标端点

PD 分离与多副本服务每个实例各暴露一个 `/metrics`。全部传进来即可：计数器求和成全局视图、比率类指标取均值、逐引擎表按实例分行。

```bash title="bash"
clawperf --mode scenario \
  --endpoint http://lb:9000/v1 --model Qwen3-0.6B \
  --tokenizer /mnt/model/Qwen3-0.6B \
  --metrics-endpoint prefill=http://10.0.0.1:9101/metrics \
  --metrics-endpoint decode=http://10.0.0.2:9102/metrics \
  --reset-cache
```

!!! tip

    标签可选（`名称=url`，默认 host:port）；该参数可重复或用逗号分隔。`--reset-cache` 会逐个重置所有实例。

### 实跑得到的逐引擎指标表

实跑后的汇总表与逐引擎指标。

```console title="clawperf --mode hitrate --endpoint http://127.0.0.1:18095/v1/chat/completions --model \
    qwen3-0.6b --tokenizer tokenizers/qwen3-0.6b --num-requests 60 --input-len 4096 \
    --output-len 32 --hit-rate 0.7 --prefix-num 2 --concurrency 4 --metrics-endpoint \
    http://127.0.0.1:18095/metrics --reset-cache --output results.json"
  HBM Prefix Cache (per engine)
+----------+--------------+------------+----------+
|   Engine | Query Tokens | Hit Tokens | Hit Rate |
+----------+--------------+------------+----------+
| engine 0 |      299,636 |    209,760 |   70.00% |
|    TOTAL |      299,636 |    209,760 |   70.00% |
+----------+--------------+------------+----------+
  Performance Results
+-------------+----------+----------+----------+----------+----------+----------+----------+----------+----+
|      Metric |      Avg |      Min |      P25 |      P50 |      P75 |      P90 |      P99 |      Max |  N |
+-------------+----------+----------+----------+----------+----------+----------+----------+----------+----+
|        TTFT | 55.27 ms | 27.45 ms | 57.15 ms | 57.81 ms | 58.40 ms | 58.96 ms | 59.55 ms | 59.62 ms | 60 |
| E2E Latency | 59.08 ms | 28.34 ms | 61.06 ms | 61.68 ms | 62.00 ms | 62.80 ms | 63.59 ms | 63.89 ms | 60 |
|        TPOT |  0.12 ms |  0.03 ms |  0.12 ms |  0.12 ms |  0.13 ms |  0.14 ms |  0.15 ms |  0.15 ms | 60 |
+-------------+----------+----------+----------+----------+----------+----------+----------+----------+----+
======================================================================
INFO:clawperf:Results saved to: C:\Users\keriko\AppData\Local\Temp\sample_hitrate.json
```

## 环境变量与配置文件

优先级：**CLI > 环境变量 > YAML（`--config`）> 默认值**。每个配置字段都有对应的大写 `CLAWPERF_*` 变量。显式传入的 flag 永远优先 —— 即使取值恰好等于默认值。

| 变量 | 等价于 |
|---|---|
| `CLAWPERF_ENDPOINT` | `--endpoint` |
| `CLAWPERF_MODEL` | `--model` |
| `CLAWPERF_API_KEY` | `--api-key` |
| `CLAWPERF_OUTPUT` | `--output` |
| `CLAWPERF_HISTORY` | `--history`（`''` 表示禁用） |
| `CLAWPERF_UPSTREAM_ENDPOINT` | `--upstream-endpoint` |
| `CLAWPERF_TOKENIZER_BACKEND` | `transformers` \| `modelscope` |
| `CLAWPERF_<FIELD>` | 任意字段：`CLAWPERF_NUM_USERS`、`CLAWPERF_CONTEXT_PROFILE` 等 |

```yaml title="clawperf.yaml —— 优先级 CLI > 环境变量 > YAML > 默认值"
mode: scenario
endpoint: http://localhost:8000/v1
model: Qwen3-0.6B
tokenizer: /mnt/model/Qwen3-0.6B
context_profile: medium
num_users: 8
max_turns: 20
slo_constraints: ["ttft.p99<=1500", "tpot.avg<=30"]
```

```bash title="bash"
clawperf --config clawperf.yaml --num-users 16
```
