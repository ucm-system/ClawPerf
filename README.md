# ClawPerf

[![CI](https://github.com/ucm-system/ClawPerf/actions/workflows/ci.yml/badge.svg)](https://github.com/ucm-system/ClawPerf/actions/workflows/ci.yml)
[![Release](https://github.com/ucm-system/ClawPerf/actions/workflows/release.yml/badge.svg)](https://github.com/ucm-system/ClawPerf/actions/workflows/release.yml)
[![Site](https://img.shields.io/badge/site-ucm--system.github.io-blue)](https://ucm-system.github.io/ClawPerf/)
[![PyPI Version](https://img.shields.io/pypi/v/clawperf.svg)](https://pypi.org/project/clawperf/)
[![Python Versions](https://img.shields.io/pypi/pyversions/clawperf.svg)](https://pypi.org/project/clawperf/)
[![License](https://img.shields.io/pypi/l/clawperf.svg)](https://github.com/ucm-system/ClawPerf/blob/main/LICENSE)

Performance benchmarking tool for LLM serving backends (vLLM / SGLang / MindIE / vllm-ascend) under **real agent workloads** — multi-turn, long-context, prefix-cache-heavy traffic.

📖 **[Project site](https://ucm-system.github.io/ClawPerf/)** (bilingual, with the workload and pipeline diagrams) · [中文文档](README_CN.md)

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

### Container image

Every release publishes a multi-arch image (`linux/amd64` + `linux/arm64`, incl. Ascend/aarch64 hosts) with all optional extras preinstalled:

```bash
docker pull ghcr.io/ucm-system/clawperf:latest
docker pull ghcr.io/ucm-system/clawperf:0.6.0        # pin a version

# benchmark a service on the host (host networking keeps 127.0.0.1 working)
docker run --rm --net=host -v "$PWD/results:/app/results" \
  ghcr.io/ucm-system/clawperf:0.6.0 \
  --mode scenario --endpoint http://127.0.0.1:8000/v1 --model qwen3 \
  --output /app/results/run.json
```

Runs as a non-root user, ships the bundled `examples/` traces and a local tokenizer, and writes its result history to the `/app/results` volume.

**Air-gapped / offline install** — each release also attaches per-architecture image tarballs:

```bash
gunzip -c clawperf-0.6.0-linux-amd64.tar.gz | docker load   # or -linux-arm64.tar.gz
docker images | grep clawperf
```

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
clawperf --mode hitrate --endpoint http://localhost:8000/v1 --model qwen3 \
  --num-requests 40 --input-len 4096 --hit-rate 0.5 \
  --request-rate 2
```

When `--request-rate` is set, `--concurrency` is ignored (true open-loop) and the summary reports the target vs achieved rate plus release skew, e.g. `Release Skew avg/max 1.2 / 8.4 ms`. Applies to `hitrate`, `replay` and `trace` real replay; `scenario`/`slo`/`agent` stay closed-loop multi-turn (that is the agent workload model — an agent fires its next request as soon as the previous one returns).

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
ruff check src/ tests/
```

### CI

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| [`ci.yml`](.github/workflows/ci.yml) | push to `main`, pull requests | `ruff check`, the test suite on Linux (3.10–3.13) + Windows/macOS, a packaging smoke test (build → `twine check` → install the wheel in a clean venv → run both entry points), and native Docker image builds for amd64 **and** arm64 with an in-image functional check |
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

ghcr packages are **private by default**, so `docker pull` fails for anyone who is not logged in. The visibility switch lives on the package's own settings page — and *which* page depends on who owns the package:

- Pushed by the workflow's `GITHUB_TOKEN` (what this repo does) → the package belongs to the **repository**:
  `https://github.com/<owner>/<repo>/pkgs/container/clawperf` → **Package settings** → *Danger Zone* → **Change visibility** → Public.
- Pushed with a personal access token → the package belongs to the **organization** instead, and GitHub does not allow changing its visibility at all; it has to be deleted and re-pushed with `GITHUB_TOKEN`.

Once public, it stays public across releases (visibility is a property of the package, not of a single version). `release.yml` also attempts the change automatically and emits a warning with the manual path if it is not permitted.

To inspect what you actually have:

```bash
gh auth refresh -s read:packages,write:packages     # the packages scope is needed for these endpoints
gh api /repos/<owner>/<repo>/packages/container/clawperf \
  --jq '{visibility, repository: .repository.full_name, owner: .owner.login}'
```

## License

Apache License 2.0