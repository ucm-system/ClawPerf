# ClawPerf

[![CI](https://github.com/ucm-system/ClawPerf/actions/workflows/ci.yml/badge.svg)](https://github.com/ucm-system/ClawPerf/actions/workflows/ci.yml)
[![Release](https://github.com/ucm-system/ClawPerf/actions/workflows/release.yml/badge.svg)](https://github.com/ucm-system/ClawPerf/actions/workflows/release.yml)
[![Site](https://img.shields.io/badge/site-ucm--system.github.io-blue)](https://ucm-system.github.io/ClawPerf/)
[![PyPI Version](https://img.shields.io/pypi/v/clawperf.svg)](https://pypi.org/project/clawperf/)
[![Python Versions](https://img.shields.io/pypi/pyversions/clawperf.svg)](https://pypi.org/project/clawperf/)
[![License](https://img.shields.io/pypi/l/clawperf.svg)](https://github.com/ucm-system/ClawPerf/blob/main/LICENSE)

Performance benchmarking tool for LLM serving backends (vLLM / SGLang / MindIE / vllm-ascend) under **real agent workloads** — multi-turn, long-context, prefix-cache-heavy traffic.

📖 **[Project site](https://ucm-system.github.io/ClawPerf/)** (bilingual, with the workload and pipeline diagrams) · **[Full reference](https://ucm-system.github.io/ClawPerf/reference.html)** — every mode, every context profile, all 73 parameters with examples · [中文文档](README_CN.md)

Built on [EvalScope](https://github.com/modelscope/evalscope)'s perf infrastructure, ClawPerf measures how an inference stack behaves when actual coding agents hammer it: growing contexts, shared prefixes between turns, tool calls, and concurrent sessions.

## Features

**Seven benchmark modes, one CLI:**

| Mode | What it does |
|------|--------------|
| `scenario` (default) | Multi-turn long-context workload: N users maintain independent growing conversations (system prefix + user prefix + history + current input), with append-mode compaction. The core agentic-load simulator. |
| `hitrate` | Controlled prefix-cache hit-rate test: prompts with a known `[shared prefix][boundary][unique suffix]` split, prefill, then **target vs measured** hit rate from the server's Prometheus counters. |
| `slo` | SLO-driven capacity sweep: ramps concurrency geometrically, then binary-refines the **max users** meeting your targets — any mix of `ttft`/`tpot`/`e2e` × `avg`/`P50`/`P90`/`P99`/`max` constraints. |
| `agent` | Real coding agent at work: the model actually calls tools (read/write files, run shell) via OpenAI function-calling across growing context. |
| `trace` | KV-cache hit-rate analysis + real replay from a trace file: simulates a block-level prefix cache (LRU/FIFO eviction, budget sweep) and, when the trace carries messages, replays real requests against the endpoint. |
| `record` | Recording proxy: sits between a real agent (Claude Code, etc.) and the LLM endpoint, captures every request/response round-trip as JSONL. |
| `replay` | Replays a recorded JSONL against any endpoint with live-history mode (feeds real responses forward so KV-cache prefixes stay aligned). |

**Three subcommands:**

| Command | Purpose |
|---------|---------|
| `clawperf report` | Regenerate a Markdown report (verdict + ASCII charts + findings) from a saved result JSON. |
| `clawperf compare` | Side-by-side comparison of two result JSONs (TTFT/decode/hit-rate/victory summary). |
| `clawperf trace-convert` | Convert external agent-trace datasets (Claude Code sessions, ShareGPT, OpenAI messages) into replayable traces. |

**Also included:**

- Command-line workflow is reachable without an LLM: `clawperf-mock-server` is a FastAPI mock LLM with a trie-based prefix-cache simulator and vLLM-style `/metrics`.
- User arrival scheduling (burst / steady / Poisson), reasoning-token (thinking) detection, early abort on consecutive failures, CI-friendly exit codes (0 ok / 1 config / 2 all-failed / 3 interrupted).
- Layered configuration: **CLI args > `CLAWPERF_*` env vars > YAML (`--config`) > defaults**.

## Real output

The docs site has **one page per mode**, each with a diagram, the command, the parameters that
matter, a real captured run and how to read it:

| Mode | Page |
|------|------|
| `scenario` | [growing conversations under load](https://ucm-system.github.io/ClawPerf/modes/scenario.html) |
| `hitrate` | [is the prefix cache actually working?](https://ucm-system.github.io/ClawPerf/modes/hitrate.html) |
| `slo` | [capacity under a latency budget](https://ucm-system.github.io/ClawPerf/modes/slo.html) |
| `agent` | [real tool-calling work](https://ucm-system.github.io/ClawPerf/modes/agent.html) |
| `trace` | [your own traffic as the workload](https://ucm-system.github.io/ClawPerf/modes/trace.html) |
| `record` & `replay` | [capture once, replay anywhere](https://ucm-system.github.io/ClawPerf/modes/record-replay.html) |

A real SLO sweep on a **vLLM-Ascend 910B3** (Qwen3-0.6B, 32K window) — the output of
`clawperf report results_e2e/slo.json --print`:

```
Report saved to: D:\Project\ClawPerf\results_e2e\slo.md
# ClawPerf Benchmark Report
| Field | Value |
| Model | `qwen3` |
| Endpoint | `http://110.138.0.3:9155/v1` |
| Backend | vllm |
| Mode | `slo` |
| SLO | ttft.p99<=1500ms, tpot.avg<=30ms, e2e.max<=20000ms |
| Max Users | 5 |
| Setup Time | 34.69s |
| Bench Time | 394.06s |
## Verdict: ✅ GOOD
- **Max sustained users:** 5
## Key Findings
- Max sustained users meeting SLO: 5
- SLO criteria: ttft.p99<=1500ms, tpot.avg<=30ms, e2e.max<=20000ms
## Summary
| Users | ttft.p99 | tpot.avg | e2e.max | Error | SLO |
| 1 | 228ms | 9ms | 8888ms | 0.0% | ✅ |
| 2 | 259ms | 9ms | 9090ms | 0.0% | ✅ |
| 4 | 624ms | 15ms | 15.5s | 0.0% | ✅ |
| 5 | 768ms | 15ms | 16.0s | 0.0% | ✅ |
| 6 | 945ms | 21ms | 22.4s | 0.0% | ❌ |
| 8 | 822ms | 25ms | 26.6s | 0.0% | ❌ |
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

Every command shown in the docs is a real run: the report-derived blocks are regenerated from the
committed `results_e2e/*.json` files, and the live ones from the bundled mock server, by
`python scripts/gen_samples.py`.

## Installation

```bash
pip install clawperf                      # core (scenario / hitrate / slo / trace)
pip install "clawperf[agent]"             # + real agent mode (openai SDK)
pip install "clawperf[record]"            # + recording proxy (fastapi/uvicorn)
pip install "clawperf[mock-server]"       # + mock LLM server
pip install "clawperf[dev]"               # + development tools
```

From source:

```bash
git clone https://github.com/ucm-system/ClawPerf.git
cd ClawPerf
pip install -e ".[dev]"
```

Notes:
- **Windows**: works out of the box — ClawPerf forces UTF-8 console I/O so help text and reports (✓/✅/█) never crash on GBK code pages, and JSONL readers accept UTF-8 BOM files.
- **No GPU / CI**: `clawperf-mock-server` provides a full fake endpoint (trie prefix cache + `/metrics`) — every mode except `agent`/`trace`-replay runs against it; hit-rate targets are verified end-to-end (see the E2E report).

### Container image

Every release publishes a multi-arch image (`linux/amd64` + `linux/arm64`, incl. Ascend/aarch64 hosts) with all optional extras preinstalled:

```bash
docker pull ghcr.io/ucm-system/clawperf:latest
docker pull ghcr.io/ucm-system/clawperf:0.6.0        # pin a version

# benchmark a service on the host (host networking keeps 127.0.0.1 working).
# The image bundles a tokenizer at /app/tokenizers/qwen3-0.6b; mount your own
# model directory instead when benchmarking a real model.
docker run --rm --net=host -v "$PWD/results:/app/results" \
  ghcr.io/ucm-system/clawperf:0.6.0 \
  --mode scenario --endpoint http://127.0.0.1:8000/v1 --model Qwen3-0.6B \
  --tokenizer /app/tokenizers/qwen3-0.6b \
  --output /app/results/run.json
```

Runs as a non-root user, ships the bundled `examples/` traces and a local tokenizer, and writes its result history to the `/app/results` volume.

**Air-gapped / offline install** — each release also attaches per-architecture image tarballs:

```bash
gunzip -c clawperf-0.6.0-linux-amd64.tar.gz | docker load   # or -linux-arm64.tar.gz
docker images | grep clawperf
```

## Quick Start

All examples assume a running vLLM-style endpoint (`http://localhost:8000/v1`) and a **local tokenizer
directory** — pass the directory your server loaded the model from. It is loaded strictly offline
(no hub lookup, no download) and drives exact token counting and content generation.

### scenario — multi-user long-context workload

```bash
clawperf \
  --endpoint http://localhost:8000/v1 \
  --model Qwen3-32B \
  --tokenizer /mnt/model/Qwen3-32B \   # local dir: loaded offline, exact tokenization
  --context-profile medium \           # named profile: sys=28K + usr=10K + in=5K
  --num-users 8 \
  --max-turns 20 \
  --metrics-endpoint http://localhost:8000/metrics \
  --output results.json
```

Or use a pre-configured suite that runs several (users × profile) scenarios in sequence:

```bash
clawperf --endpoint http://localhost:8000/v1 --model Qwen3-32B \
  --tokenizer /mnt/model/Qwen3-32B \
  --suite standard --output results_suite.json
```

### hitrate — controlled prefix-cache hit rate

```bash
clawperf --mode hitrate \
  --endpoint http://localhost:8000/v1 --model Qwen3-32B \
  --tokenizer /mnt/model/Qwen3-32B \
  --num-requests 100 --input-len 4096 --output-len 128 \
  --hit-rate 0.5 \                  # target 50% (or --prefix-len 2048)
  --prefix-num 10 \
  --metrics-endpoint http://localhost:8000/metrics --backend vllm \
  --reset-cache
```

The summary prints **TARGET vs MEASURED** hit rate (measured from `vllm:prefix_cache_hits_total`/`queries_total` deltas) plus a per-engine breakdown.

### slo — max concurrency under SLO

Constraints are freely composable: any latency metric (`ttft` / `tpot` / `e2e`) × any aggregate (`avg`, `min`, `max`, `p25`, `p50`, `p75`, `p90`, `p95`, `p99`, `p99.9`, …) × any operator (`<=`, `<`, `>=`, `>`), in milliseconds. Repeat `--slo` to combine — all constraints AND together.

> **Shell safety.** `<` and `>` are redirection operators in bash/zsh, so `--slo ttft.p99<=500` **unquoted** makes the shell eat the operator and try to read a file named `=500` (`bash: =500: No such file or directory` — ClawPerf never even starts). Either quote the spec, or use the separator form, which needs no quoting at all:

```bash
# Shell-safe: ':' or '=' means '<='
clawperf --mode slo \
  --endpoint http://localhost:8000/v1 --model Qwen3-32B \
  --tokenizer /mnt/model/Qwen3-32B \
  --slo ttft.p99:500 --slo tpot.avg:30 --slo e2e.max:30000 \
  --slo-min-users 1 --slo-max-users 200 \
  --slo-step-strategy geometric \
  --output results_slo.json

# Equivalent — quoted symbolic operators (or one quoted, comma-separated value)
clawperf --mode slo ... \
  --slo 'ttft.p99<=500' --slo 'tpot.avg<=30' --slo 'e2e.max<=30000'
clawperf --mode slo ... --slo 'ttft.p99<=500,tpot.avg<=30,e2e.max<=30000'
```

| Written as | Means | Notes |
|------------|-------|-------|
| `ttft.p99:500` / `ttft.p99=500` | `ttft.p99 <= 500` | shell-safe, no quotes needed |
| `ttft.p99<=500` | `ttft.p99 <= 500` | quote it in a shell |
| `ttft.p99:le:500` / `ttft.p99 le 500` | `ttft.p99 <= 500` | word operators: `le lt ge gt` |
| `ttft.p99:ge:500` | `ttft.p99 >= 500` | the only shell-safe way to say `>=` |
| `ttft.p99<=500ms` | same, unit optional | |

If the shell still eats the operator, ClawPerf detects the leftover bare metric and tells you exactly what happened instead of failing on an unrelated file:

```
[ClawPerf] configuration error: invalid SLO constraint 'ttft.p99': no operator or threshold
found after the metric. If you wrote --slo ttft.p99<=1500 without quotes, your shell consumed
'<' as a redirection ... quote it (--slo 'ttft.p99<=1500') or use --slo ttft.p99:1500.
```

Legacy shorthand is still supported (and converted to `ttft.p99<=X` style internally):

```bash
clawperf --mode slo ... --slo-ttft-ms 500 --slo-tpot-ms 30 --slo-percentile 0.99
```

Output: a capacity curve (one column per constraint, users × values × SLO verdict) and the max sustained users. Example against a real vLLM-Ascend endpoint:

```
| Users | ttft.p99 | tpot.avg |   e2e.max | Error | SLO |
|     1 |  228.2ms |    8.6ms |  8887.7ms |  0.0% |  ✓  |
|     4 |  624.2ms |   14.7ms | 15471.1ms |  0.0% |  ✓  |
|     6 |  945.1ms |   20.9ms | 22360.6ms |  0.0% |  ✗  |
SLO: ttft.p99<=1500ms, tpot.avg<=30ms, e2e.max<=20000ms
Max sustained users: 5
```

### agent — real coding agent

Requires the backend to support tool calling (e.g. `vllm serve ... --enable-auto-tool-choice --tool-call-parser qwen3_xml`).

```bash
clawperf --mode agent \
  --endpoint http://localhost:8000/v1 --model Qwen3-32B \
  --tokenizer /mnt/model/Qwen3-32B \
  --agent-tasks 10 \
  --agent-max-steps 12 --agent-max-tokens 512 \
  --metrics-endpoint http://localhost:8000/metrics --backend vllm
```

Custom tasks via `--agent-task-file` (one `{"prompt", "workspace": {"path":"content"}, "max_steps"}` per line).

### trace — KV-cache analysis + real replay

```bash
# Local simulation only (no endpoint needed): hit rate at a given budget,
# plus a budget sweep to find the inflection point.
clawperf --mode trace --trace-file trace.jsonl --budget-sweep

# Trace with messages → also replays real requests against the endpoint.
# --model-context-length clamps each request's max_tokens to the remaining
# window (exact tokenization when --tokenizer is given) and skips requests
# whose input alone exceeds the window with a clear error.
clawperf --mode trace \
  --trace-file trace.jsonl \
  --endpoint http://localhost:8000/v1 --model Qwen3-32B \
  --tokenizer /mnt/model/Qwen3-32B \
  --model-context-length 32768 \
  --trace-users 3                    # session-aware concurrency
```

### record & replay — capture a real agent session, then replay it

```bash
# Terminal 1: start the recording proxy (agents point their base URLs here).
# Accepts OpenAI (/v1/chat/completions) AND Anthropic (/v1/messages) clients,
# translating Anthropic→OpenAI on the fly. The recording JSONL is appended
# across restarts (you'll be told how many prior entries are kept).
clawperf --mode record --upstream-endpoint http://localhost:8000 \
  --proxy-port 9090 --recording session.jsonl

# Point Claude Code at the proxy, work for a while, Ctrl+C.
# Terminal 2: replay the recording against any endpoint with live history.
clawperf --mode replay \
  --recording session.jsonl \
  --endpoint http://localhost:8000/v1 --model Qwen3-32B \
  --tokenizer /mnt/model/Qwen3-32B \
  --history-mode live
```

### report & compare

```bash
clawperf report results.json                       # → results.md
clawperf compare run_a.json run_b.json --label-a vLLM --label-b SGLang
```

## Trace Datasets

ClawPerf consumes the major trace formats used by the agent ecosystem:

| Format | Structure | Examples |
|--------|-----------|----------|
| **kvcache.ai** (native) | `{hash_ids, input_length, block_size?, user_id?}` | kvcache.ai hit-rate simulator |
| **Claude Code sessions** | line-per-message with Anthropic content blocks | Fable-5-traces, kimi-k2.6-claude-code-traces |
| **ShareGPT / Hermes** | `{conversations: [{from: human\|gpt\|system, value}]}` | vLLM & LMCache benchmarks, carnice traces, CodexBench |
| **OpenAI messages** | `{messages: [{role, content, tool_calls}]}` | generic API exports |

Convert external datasets with `trace-convert`, then run `--mode trace`:

```bash
clawperf trace-convert session.jsonl sharegpt.jsonl \
  --output trace.jsonl --max-turns 4
```

Trace files you can try right away (ModelScope):

```bash
clawperf trace-convert \
  https://www.modelscope.cn/datasets/Glint-Research/Fable-5-traces/... \
  ...
```

## Configuration

Precedence: **CLI args (explicit) > `CLAWPERF_*` env vars > YAML (`--config`) > dataclass defaults.**

```bash
export CLAWPERF_ENDPOINT=http://localhost:8000/v1
export CLAWPERF_MODEL=qwen3
export CLAWPERF_MAX_TURNS=20
clawperf --config config.yaml       # YAML may also carry any of these keys
```

Example `config.yaml`:

```yaml
mode: scenario
context_profile: medium
num_users: 8
max_turns: 20
metrics_endpoint: http://localhost:8000/metrics
backend: vllm
```

### Context profiles & suites

A **profile** is a named context size, so you don't have to invent token counts. `--context-profile <name>` sets all three numbers at once:

| Profile | system prefix | user prefix | input / turn | base context | use it for |
|---------|--------------:|------------:|-------------:|-------------:|------------|
| `fresh`  | 4,000 | 1,500 | 1,500 | **7K** | smoke test, quick sanity check |
| `short`  | 14,000 | 5,000 | 3,000 | **22K** | short chat with a few tool calls |
| `medium` | 28,000 | 10,000 | 5,000 | **43K** | typical coding session |
| `long`   | 50,000 | 18,000 | 7,000 | **75K** | long session, many files + history |
| `full`   | 72,000 | 25,000 | 8,000 | **105K** | approaching a 100K window |
| `xl`     | 150,000 | 45,000 | 10,000 | **205K** | prefill stress (a request can dominate a step) |
| `xxl`    | 300,000 | 80,000 | 12,000 | **392K** | near the largest model windows |

Names are case-insensitive. `--context-profile medium` overrides the raw `--system-prefix-tokens / --user-prefix-tokens / --input-tokens-per-turn` flags.

A **suite** runs the (users × profiles) cross-product in sequence, writing one result file per scenario:

| Suite | user counts | profiles | turns | out/turn | scenarios |
|-------|-------------|----------|------:|---------:|----------:|
| `quick` | 1, 4, 8 | `fresh` | 10 | 256 | 3 |
| `standard` | 1, 8, 16, 32 | `medium` + `long` | 20 | 512 | 8 |
| `full` | 1, 4, 8, 16, 32, 64 | `fresh` → `full` | 30 | 512 | 30 |
| `hitrate` | 1 | `fresh` → `full` | 5 | 128 | 5 |

```bash
# one profile
clawperf --mode scenario --context-profile medium --num-users 8 ...

# sweep profiles × users (writes results_<profile>_<users>u.json per scenario)
clawperf --mode scenario --suite full --model-context-length 32768 ...

# raw token counts instead of a named profile
clawperf --mode scenario --system-prefix-tokens 28000 \
  --user-prefix-tokens 10000 --input-tokens-per-turn 5000 ...
```

`--model-context-length` skips profiles whose base context cannot fit the model window (and clamps trace-replay `max_tokens` to what remains).

📖 **[Full reference — every mode, every profile and all 73 parameters, with examples](https://ucm-system.github.io/ClawPerf/reference.html)** (generated from `clawperf --help`, so it can't drift).

### Key options by mode

| Mode | Core options |
|------|--------------|
| All | `--endpoint --model --api-key --tokenizer --request-timeout --output --verbose --config` |
| Reliability | `--no-preflight` (skip the pre-flight probe), `--preflight-retries N` (default 3) |
| scenario | `--num-users --user-arrival --context-profile` or raw `--system-prefix-tokens/--user-prefix-tokens/--input-tokens-per-turn`, `--max-turns --max-context-tokens --compaction-prefix-increment --suite --max-consecutive-failures` |
| hitrate | `--num-requests --input-len --output-len --hit-rate` or `--prefix-len`, `--prefix-num --prefill/--no-prefill --seed` |
| slo | `--slo <metric>.<agg><sep><ms>` (repeatable; ttft/tpot/e2e × avg/min/max/p25…p99.9; `<sep>` = `:`/`=`/`<=`/`<`/`>=`/`>`/`le`/`lt`/`ge`/`gt`), or legacy `--slo-ttft-ms/--slo-tpot-ms --slo-percentile`; `--slo-error-rate --slo-min-users --slo-max-users --slo-step-*` |
| agent | `--agent-tasks --agent-task-file --agent-max-steps --agent-max-tokens --agent-shell-timeout --agent-workdir` |
| record | `--upstream-endpoint --proxy-port --recording --upstream-api` |
| replay | `--recording --history-mode live\|verbatim` |
| trace | `--trace-file --cache-budget-tokens/--cache-budget-gb --eviction-policy --trace-block-size --budget-sweep --trace-users --kv-bytes-per-token --model-context-length` |
| Shared concurrency | `--concurrency` (request-level: hitrate/replay/trace); `--trace-users` (session-level: trace) |
| Metrics | `--metrics-endpoint` (repeatable / comma-separated; `name=url` labels) `--metrics-interval --metrics-samples --reset-cache --backend` |
| Pacing | `--user-arrival` (when sessions *join*) and `--request-rate` (requests/second, open-loop) |

### Request rate: open-loop vs closed-loop

Three different knobs, often confused:

| Knob | Controls | Semantics |
|------|----------|-----------|
| `--user-arrival burst\|steady:<s>\|poisson:<λ>` | when each **session/user joins** the benchmark | users then run their turns back-to-back |
| `--concurrency N` | **closed-loop** in-flight request cap (hitrate / replay / trace) | next request starts as soon as one finishes — the server throttles the load |
| `--request-rate R` | **open-loop** request issue rate in req/s | requests are released on a Poisson process at R req/s *regardless of completions* (the `benchmark_serving --request-rate` semantics) |

Closed-loop answers "how fast can the server go at N in flight"; open-loop answers "what happens when traffic arrives at R req/s" — the two are not interchangeable, because a closed loop can never overload the server while an open loop can.

```bash
# 40 requests arriving at 2 req/s (Poisson) — no in-flight cap
clawperf --mode hitrate --endpoint http://localhost:8000/v1 --model Qwen3-32B \
  --tokenizer /mnt/model/Qwen3-32B \
  --num-requests 40 --input-len 4096 --hit-rate 0.5 \
  --request-rate 2
```

When `--request-rate` is set, `--concurrency` is ignored (true open-loop) and the summary reports the target vs achieved rate plus release skew, e.g. `Release Skew avg/max 1.2 / 8.4 ms`. Applies to `hitrate`, `replay` and `trace` real replay; `scenario`/`slo`/`agent` stay closed-loop multi-turn (that is the agent workload model — an agent fires its next request as soon as the previous one returns).

### Multi-instance & PD-disaggregated metrics

PD-disaggregated (and plain multi-replica) services expose **one `/metrics` port per instance**. Pass them all — ClawPerf polls every endpoint concurrently and merges them into one fleet-wide view: counters are summed, ratio gauges averaged, and the per-engine breakdown gains one row per instance (engine ids namespaced by endpoint):

```bash
clawperf --mode scenario \
  --endpoint http://lb:9000/v1 --model Qwen3-32B \
  --tokenizer /mnt/model/Qwen3-32B \
  --metrics-endpoint prefill=http://10.0.0.1:9101/metrics \
  --metrics-endpoint decode=http://10.0.0.2:9102/metrics
```

```
|            Engine | Query Tokens | Hit Tokens | Hit Rate |
| engine prefill:0  |       41,427 |     27,520 |   66.43% |
| engine decode:0   |       40,287 |     26,752 |   66.40% |
|            TOTAL  |       81,714 |     54,272 |   66.42% |
```

`--metrics-endpoint` is repeatable and also accepts comma-separated lists and `label=url` (default label: host:port). `--reset-cache` (and SLO's per-step reset) hits every instance's reset endpoint. In a PD deployment the prefill instance usually carries the prefix-cache hits — this table shows exactly where reuse happens.

## Troubleshooting

### `--slo` and other flags

| Symptom | Cause | Fix |
|---------|-------|-----|
| `bash: =10000: No such file or directory` | unquoted `<`/`>` in `--slo ttft.p99<=10000` — bash reads it as a redirection | `--slo ttft.p99:10000` (shell-safe) or `--slo 'ttft.p99<=10000'` |
| `invalid SLO constraint 'ttft.p99': no operator or threshold found` | the shell already ate the operator; ClawPerf only received the bare metric | same as above |

### Tokenizer

A **local directory** is loaded strictly offline (`local_files_only=True`), transformers first, ModelScope as fallback — no hub lookup, no download, no hang. A hub id (`Qwen/Qwen3-0.6B`) still uses ModelScope first, then HuggingFace. Force one backend with `CLAWPERF_TOKENIZER_BACKEND=transformers|modelscope`.

```
INFO:clawperf:Loaded local tokenizer from /mnt/model/Qwen3-0.6B [local dir (transformers)] — vocab=151669, chat_template=yes
```

The container image bundles a known-good tokenizer, so you can isolate a tokenizer problem from an endpoint problem in one command:

```bash
docker run --rm ghcr.io/ucm-system/clawperf:0.6.1 clawperf --mode scenario \
  --endpoint http://host.docker.internal:8000/v1 --model Qwen3-32B \
  --tokenizer /app/tokenizers/qwen3-0.6b --num-users 1 --max-turns 1 --no-preflight
```

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Tokenizer path '/mnt/model/X' does not exist on this machine` | the path isn't visible inside the container (missing `-v` mount) — the error lists the parent directory's contents | mount it: `-v /mnt/model:/mnt/model:ro` |
| `Failed to load a local tokenizer ... Files present: ...` | the directory has no tokenizer files (weights only), or no backend is installed | point `--tokenizer` at the directory containing `tokenizer.json` / `tokenizer_config.json` |
| `Failed to load tokenizer '<id>' from the model hub` | air-gapped host or a typo in the model id | use `--tokenizer /local/dir` |

### Pre-flight probe

Before a run, ClawPerf sends one tiny request to catch a wrong endpoint/model in seconds rather than after content generation. Transport failures (connection reset while the server is still loading its weights, timeouts) are **retried with backoff** (`--preflight-retries`, default 3); 4xx rejections fail immediately. The error keeps only the exception line, not EvalScope's full aiohttp traceback:

```
[ClawPerf] Pre-flight: request to http://host:8000/v1/chat/completions failed:
server rejected the probe (status=None, aiohttp.client_exceptions.ClientOSError: [Errno 104] Connection reset by peer).
  Check --endpoint / --model / --api-key, and that the server has finished loading the model.
  If the server is up and serves real traffic, re-run with --no-preflight to skip this probe.
```

If the server serves real traffic but keeps resetting this probe, add `--no-preflight`.

## Output

Every run produces:
- **JSON** (`--output`, default `results_<timestamp>.json`) — config, summary, per-user/per-turn detail (mode-specific), system metrics, timeline.
- **Markdown report** (`<output>.md`) — verdict ✅/⚠️/❌, auto-generated key findings, per-mode summary tables, ASCII TTFT scaling chart, budget sweep / real replay sections for trace mode.

Example verdict section:

```markdown
## Verdict: ✅ GOOD

- **TTFT (P50):** 180ms — instant (GOOD)
- **Decode throughput:** 114.8 tok/s — smooth (GOOD)
```

### Result history

Every run appends one compact line to `clawperf_history.jsonl` (config + summary + per-user aggregates, no heavy per-turn arrays). Queryable with `jq`:

```bash
tail -n1 clawperf_history.jsonl | jq '.summary.prefix_cache_token_hit_rate'
```

## Architecture

| Module | Role |
|--------|------|
| `cli.py` | Argparse entry point; mode dispatch; subcommands (report/compare/trace-convert); exit codes |
| `config.py` | `BenchmarkConfig` dataclass; layered config (CLI > env > YAML); validation |
| `context_profiles.py` | Named context profiles + suites |
| `runner.py` | `BenchmarkRunner`: scenario/hitrate/slo/agent orchestration, results finalization |
| `context.py` | `UserContext`: context assembly + compaction with infinite-loop guard |
| `scheduler.py` | Burst/steady/Poisson user arrival generators |
| `player.py` | `ReplayPlayer`: streaming replay engine (live/verbatim, session-aware concurrency) |
| `trace_simulator.py` | Prefix-cache simulation (LRU/FIFO, budget sweep) + trace replay (via player) |
| `trace_converter.py` | External trace conversion (Claude Code / ShareGPT / OpenAI) |
| `recorder.py` | Recording proxy (FastAPI, Anthropic↔OpenAI translation on the fly) |
| `translators.py` | Anthropic↔OpenAI message/tool/SSE translation, endpoint normalization |
| `agent.py` | Real coding-agent loop with tool calls + reasoning-token detection |
| `agent_tasks.py` | Preset agent task bank + workspace materialization |
| `system_metrics.py` | Prometheus polling, prefix-cache delta math (HBM+external, per-engine) |
| `mock_server.py` | Standalone mock LLM server (trie prefix cache, `/metrics`) |
| `report.py` | Markdown reports, verdicts, comparisons |

## Testing Philosophy

ClawPerf simulates the **real workload of an Agent system** — not single-shot API calls but sustained multi-turn conversations that push serving backends to their limits:

- **Prefix cache effectiveness** — token-level reuse across turns (a single-request benchmark can't measure this).
- **Compaction under load** — how the system recovers when context hits the window.
- **Latency degradation** — TTFT/TPOT as context grows from 7K to 100K+ tokens.
- **Concurrent pressure** — mixed prefix states from independent user conversations.
- **Real traces** — replay actual agent sessions (Claude Code, ShareGPT, Codex) to measure the stack under the exact access patterns agents generate.

## End-to-End Test Report

See [docs/E2E_TEST_REPORT.md](docs/E2E_TEST_REPORT.md) for a full end-to-end
run against a vLLM-Ascend endpoint covering all 7 modes + 3 subcommands
(including real ModelScope trace replay). Raw per-mode results live in
`results_e2e/`.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src/ tests/
```

### CI

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| [`ci.yml`](.github/workflows/ci.yml) | push to `main`, pull requests | `ruff check`, the test suite on Linux (3.10–3.13) + Windows/macOS, an end-to-end job (real mock server + bundled local tokenizer + the shell-quoting matrix in real bash), a packaging smoke test (build → `twine check` → install the wheel in a clean venv → run both entry points), and native Docker image builds for amd64 **and** arm64 with an in-image functional check |
| [`release.yml`](.github/workflows/release.yml) | tag `v*` (or manual dispatch) | test gate → sdist + wheel → **PyPI** → native `linux/amd64` and `linux/arm64` images pushed to ghcr.io → multi-arch manifest → GitHub Release with every artifact attached |
| [`pages.yml`](.github/workflows/pages.yml) | push to `main` touching `docs/` | validates the site (asset paths, tag balance, SVG XML) and deploys it to GitHub Pages |

### Project site

The landing page lives in `docs/` and is deployed to **https://ucm-system.github.io/ClawPerf/** by `pages.yml`.

```bash
python3 scripts/check_site.py docs     # validate before pushing (assets, tags, SVG XML)
python3 -m http.server -d docs 8000    # preview locally at http://localhost:8000
```

It is a single self-contained `index.html` (no build step, no CDN, no external fonts) with inline SVG figures in `docs/assets/`, an EN/中文 toggle and light/dark themes. Adding a diagram means dropping an SVG into `docs/assets/` and referencing it — the check script enforces that every reference resolves.

One-time setup: **Settings → Pages → Build and deployment → Source = GitHub Actions**.

### Releasing

Releases are tag-driven — bump the version, tag, push:

```bash
# 1. bump src/clawperf/__init__.py  __version__ = "0.7.0"
# 2. commit, then tag and push
git commit -am "chore: release v0.7.0"
git tag v0.7.0 && git push origin main v0.7.0
```

The `verify` job fails fast if the tag does not match `clawperf.__version__`, so the two can never drift.

The release then produces, in one go:

| Where | What |
|-------|------|
| **PyPI** | `clawperf==<version>` (wheel + sdist) — stable tags only |
| **ghcr.io** | multi-arch image `:<version>`, `:<major>.<minor>`, `:latest` |
| **GitHub Release** | `clawperf-<v>-py3-none-any.whl`, `clawperf-<v>.tar.gz`, `clawperf-<v>-linux-amd64.tar.gz`, `clawperf-<v>-linux-arm64.tar.gz`, `SHA256SUMS` |

Container tags: `:<version>`, `:<major>.<minor>` and `:latest` (prerelease tags such as `v0.7.0-rc1` publish images and release assets but do **not** move `latest` and do **not** go to PyPI). Images are built **natively per architecture** — `ubuntu-latest` for amd64, `ubuntu-24.04-arm` for arm64 — so no QEMU emulation is involved; re-dispatch the workflow with `arm_runner: ubuntu-latest` if the ARM runner is unavailable.

#### PyPI credentials

The `pypi` job authenticates in whichever way is configured, so nothing needs editing when you switch:

1. **API token** (what this repo uses): store it as the repository secret `PYPI_API_TOKEN` —
   ```bash
   gh secret set PYPI_API_TOKEN --repo ucm-system/ClawPerf   # paste the pypi-... token
   ```
2. **Trusted Publishing** (no long-lived secret): add a publisher on PyPI (project → *Publishing* → owner `ucm-system`, repository `ClawPerf`, workflow `release.yml`) and delete the secret. The workflow automatically falls back to OIDC when `PYPI_API_TOKEN` is absent.

Uploads use `skip-existing`, so re-running a release never fails on an already-published version.

One-time repository setup: **Settings → Actions → General → Workflow permissions → Read and write** (so `GITHUB_TOKEN` may push to ghcr.io).

#### Making the image publicly pullable

ghcr packages are **private by default**, so `docker pull` fails for anyone who is not logged in. Changing that is a two-step, **UI-only** procedure:

1. **Unlock public packages at the organization level** — otherwise the package page shows *"Setting is disabled by organization administrators"* next to Public and Internal and there is nothing to click:

   `https://github.com/organizations/<org>/settings/packages` → **Package Creation** → tick **Public** (and **Internal** if wanted) → save.

2. **Switch the package itself**:
   `https://github.com/orgs/<org>/packages/container/clawperf/settings` → **Danger Zone** → **Change visibility** → **Public** → type the package name to confirm.

Notes:

- Step 1 needs an organization owner. If the organization belongs to an **enterprise**, an enterprise owner may have to allow public packages first.
- Once public, a package **cannot be made private again**, and it stays public across releases (visibility belongs to the package, not to a version).
- The REST API cannot do either step: the GitHub Packages API only lists/gets/deletes/restores packages, so `PATCH /orgs/<org>/packages/container/<name>` always answers `404` (this was verified with a token holding `write:packages`).
- Fallback when the policy cannot be changed: publish to a **user** namespace (e.g. `ghcr.io/<user>/clawperf`), where the account owner controls visibility directly — or hand out the offline image tarballs from the release, which need no registry authentication at all.

## License

Apache License 2.0