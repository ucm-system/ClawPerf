# ClawPerf

[![PyPI Version](https://img.shields.io/pypi/v/clawperf.svg)](https://pypi.org/project/clawperf/)
[![Python Versions](https://img.shields.io/pypi/pyversions/clawperf.svg)](https://pypi.org/project/clawperf/)
[![License](https://img.shields.io/pypi/l/clawperf.svg)](https://github.com/ucm-system/ClawPerf/blob/main/LICENSE)

Performance benchmarking tool for LLM serving backends (vLLM / SGLang / MindIE / vllm-ascend) under **real agent workloads** — multi-turn, long-context, prefix-cache-heavy traffic.

[中文文档](README_CN.md)

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

## Quick Start

All examples assume a running vLLM-style endpoint (`http://localhost:8000/v1`).

### scenario — multi-user long-context workload

```bash
clawperf \
  --endpoint http://localhost:8000/v1 \
  --model qwen2.5-72b \
  --context-profile medium \        # named profile: sys=28K + usr=10K + in=5K
  --num-users 8 \
  --max-turns 20 \
  --metrics-endpoint http://localhost:8000/metrics \
  --output results.json
```

Or use a pre-configured suite that runs several (users × profile) scenarios in sequence:

```bash
clawperf --endpoint http://localhost:8000/v1 --model qwen2.5-72b \
  --suite standard --output results_suite.json
```

### hitrate — controlled prefix-cache hit rate

```bash
clawperf --mode hitrate \
  --endpoint http://localhost:8000/v1 --model qwen2.5-72b \
  --num-requests 100 --input-len 4096 --output-len 128 \
  --hit-rate 0.5 \                  # target 50% (or --prefix-len 2048)
  --prefix-num 10 \
  --metrics-endpoint http://localhost:8000/metrics --backend vllm \
  --reset-cache
```

The summary prints **TARGET vs MEASURED** hit rate (measured from `vllm:prefix_cache_hits_total`/`queries_total` deltas) plus a per-engine breakdown.

### slo — max concurrency under SLO

Constraints are freely composable: any latency metric (`ttft` / `tpot` / `e2e`) × any aggregate (`avg`, `min`, `max`, `p25`, `p50`, `p75`, `p90`, `p95`, `p99`, `p99.9`, …) × any operator (`<=`, `<`, `>=`, `>`), in milliseconds. Repeat `--slo` to combine — all constraints AND together:

```bash
clawperf --mode slo \
  --endpoint http://localhost:8000/v1 --model qwen2.5-72b \
  --slo ttft.p99<=500 --slo tpot.avg<=30 --slo e2e.max<=30000 \
  --slo-min-users 1 --slo-max-users 200 \
  --slo-step-strategy geometric \
  --output results_slo.json
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
  --endpoint http://localhost:8000/v1 --model qwen3 \
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
  --endpoint http://localhost:8000/v1 --model qwen3 \
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
  --endpoint http://localhost:8000/v1 --model qwen3 \
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

| Profile | sys+usr+in (tokens) | | Suite | users × profiles |
|---------|---------------------|-|-------|------------------|
| `fresh` | 7K | | `quick` | [1,4,8] × fresh |
| `short` | 22K | | `standard` | [1,8,16,32] × medium+long |
| `medium` | 43K | | `full` | [1,4,8,16,32,64] × fresh→full |
| `long` | 75K | | `hitrate` | [1] × fresh→full |
| `full` | 105K | | | |
| `xl` | 205K | | | |
| `xxl` | 392K | | | |

`--model-context-length` skips profiles whose base context exceeds the model window.

### Key options by mode

| Mode | Core options |
|------|--------------|
| All | `--endpoint --model --api-key --request-timeout --output --verbose --config` |
| scenario | `--num-users --user-arrival --context-profile` or raw `--system-prefix-tokens/--user-prefix-tokens/--input-tokens-per-turn`, `--max-turns --max-context-tokens --compaction-prefix-increment --suite --max-consecutive-failures` |
| hitrate | `--num-requests --input-len --output-len --hit-rate` or `--prefix-len`, `--prefix-num --prefill/--no-prefill --seed` |
| slo | `--slo <metric>.<agg><op><ms>` (repeatable; ttft/tpot/e2e × avg/min/max/p25…p99.9), or legacy `--slo-ttft-ms/--slo-tpot-ms --slo-percentile`; `--slo-error-rate --slo-min-users --slo-max-users --slo-step-*` |
| agent | `--agent-tasks --agent-task-file --agent-max-steps --agent-max-tokens --agent-shell-timeout --agent-workdir` |
| record | `--upstream-endpoint --proxy-port --recording --upstream-api` |
| replay | `--recording --history-mode live\|verbatim` |
| trace | `--trace-file --cache-budget-tokens/--cache-budget-gb --eviction-policy --trace-block-size --budget-sweep --trace-users --kv-bytes-per-token --model-context-length` |
| Shared concurrency | `--concurrency` (request-level: hitrate/replay/trace); `--trace-users` (session-level: trace) |
| Metrics | `--metrics-endpoint` (repeatable / comma-separated; `name=url` labels) `--metrics-interval --metrics-samples --reset-cache --backend` |

### Multi-instance & PD-disaggregated metrics

PD-disaggregated (and plain multi-replica) services expose **one `/metrics` port per instance**. Pass them all — ClawPerf polls every endpoint concurrently and merges them into one fleet-wide view: counters are summed, ratio gauges averaged, and the per-engine breakdown gains one row per instance (engine ids namespaced by endpoint):

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

`--metrics-endpoint` is repeatable and also accepts comma-separated lists and `label=url` (default label: host:port). `--reset-cache` (and SLO's per-step reset) hits every instance's reset endpoint. In a PD deployment the prefill instance usually carries the prefix-cache hits — this table shows exactly where reuse happens.

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
ruff check src/
```

## License

Apache License 2.0