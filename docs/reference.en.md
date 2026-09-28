---
description: Every ClawPerf parameter, generated from clawperf --help.
---

# Every parameter, generated from the code

This page is generated from `clawperf --help` and the context-profile definitions, so it cannot drift from the tool. **73 parameters / 77 flags.**

## SLO constraint syntax

The constraint is `<metric>.<agg><sep><ms>` — repeat `--slo` to AND several constraints together.

| Write | Means | Notes |
|---|---|---|
| `ttft.p99:1500` | `ttft.p99 <= 1500ms` | shell-safe (no quoting needed) |
| `tpot.avg=30` | `tpot.avg <= 30ms` | shell-safe (no quoting needed) |
| `'ttft.p99<=1500'` | `ttft.p99 <= 1500ms` | must be quoted in bash/zsh |
| `ttft.p99\:ge:1500` | `ttft.p99 >= 1500ms` | the only shell-safe way to write `>=` |
| `'a<=1,b<=2'` | both constraints | one quoted argument, several constraints |

!!! warning

    In a shell, quote `<=` or use a separator without `<` / `>`, because those characters are redirections.

**Metrics** — `ttft` (time to first token), `tpot` (time per output token), `e2e` (end-to-end latency).

**Aggregates** — `avg`, `min`, `max`, and any percentile `p25 p50 p75 p90 p95 p99 p99.9`. Several constraints AND together; the sweep stops at the first level that breaks any of them.

The shell-quoting trap, and the diagnostic when a bare metric reaches ClawPerf.

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

## All parameters {#params}

Every option, its default and its accepted values. Mode-specific groups are listed after the shared ones.

### Mode

| Option | Default | Description |
|---|---|---|
| `--mode <MODE>` | `scenario` | 'scenario' (default): multi-turn long-context workload. 'hitrate': controlled prefix-cache hit-rate test. 'slo': sweep concurrency to find max users meeting TTFT/TPOT SLO. 'agent': real agent-at-work perf (model runs coding tasks via tool calls). 'record': recording proxy — capture a real agent session as JSONL. 'replay': replay a recorded session against an endpoint. 'trace': simulate KV-cache hit rate from a trace file (kvcache.ai format).<br>**choices:** `scenario`, `hitrate`, `slo`, `agent`, `record`, `replay`, `trace` |

### Context Profiles & Suites

| Option | Default | Description |
|---|---|---|
| `--context-profile <NAME>` | `—` | Named context-size profile (case-insensitive), overriding the raw token counts below: fresh, short, medium, long, full, xl, xxl (6K→400K base context; see the reference for the exact system/user/input split). |
| `--suite <NAME>` | `—` | Pre-configured suite: quick, standard, full, hitrate. Runs multiple (users × profile) scenarios in sequence. |
| `--model-context-length <TOKENS>` | `0` | Model's max context window. Suite profiles exceeding this are skipped, and trace-replay max_tokens is clamped so requests fit the window (0=no limit). |

### User Configuration

| Option | Default | Description |
|---|---|---|
| `--num-users <NUM_USERS>` | `1` | Total concurrent users. |
| `--user-arrival <USER_ARRIVAL>` | `burst` | 'burst' (all sessions at once), 'steady:<seconds>' (one new session every N seconds), or 'poisson:<lambda>' (Poisson arrivals). |

### Context Configuration

| Option | Default | Description |
|---|---|---|
| `--system-prefix-tokens <SYSTEM_PREFIX_TOKENS>` | `15000` | Shared system prompt every user starts with (the bulk of the context). Overridden by --context-profile/--suite. |
| `--system-prefix-source <SYSTEM_PREFIX_SOURCE>` | `random` | 'random' (synthesised filler) or a file path whose contents become the system prefix. |
| `--user-prefix-tokens <USER_PREFIX_TOKENS>` | `5000` | Per-user distinct prefix (each user has its own, so prefix caching does not trivially hit). |
| `--input-tokens-per-turn <INPUT_TOKENS_PER_TURN>` | `5000` | New user content appended every turn. |
| `--output-tokens-per-turn <OUTPUT_TOKENS_PER_TURN>` | `1000` | Max generated tokens per turn (with --ignore-eos this is the decode length actually measured). |
| `--max-context-tokens <MAX_CONTEXT_TOKENS>` | `128000` | Window at which append-mode compaction triggers (must fit the model's real context window). |
| `--compaction-prefix-increment <COMPACTION_PREFIX_INCREMENT>` | `5000` | Tokens appended to the compacted prefix each time compaction runs. |

### Run Configuration

| Option | Default | Description |
|---|---|---|
| `--request-rate <RPS>` | `0.0` | Open-loop request issue rate in req/s (Poisson inter-arrival, benchmark_serving semantics). 0 (default) = closed-loop: pacing driven by --concurrency (hitrate/replay/trace) or back-to-back turns (scenario/slo/agent). When > 0, --concurrency is ignored for hitrate/replay/trace — requests are released on schedule regardless of completions. Note: --user-arrival schedules when users (sessions) JOIN; --request-rate paces individual requests. |
| `--concurrency <CONCURRENCY>` | `1` | Request-level concurrency: in-flight requests for hitrate measure phase, replay, and trace real replay (no user ids). For trace sessions use --trace-users. |
| `--max-turns <MAX_TURNS>` | `100` | Turns (round trips) per user in scenario mode; --suite overrides it. |
| `--max-consecutive-failures <MAX_CONSECUTIVE_FAILURES>` | `0` | Abort the benchmark after this many consecutive failures (0=disabled). |

### API Configuration

| Option | Default | Description |
|---|---|---|
| `--endpoint <ENDPOINT>` | `—` | LLM API endpoint URL (env: CLAWPERF_ENDPOINT). |
| `--model <MODEL>` | `—` | Model name (env: CLAWPERF_MODEL). |
| `--api-key <API_KEY>` | `—` | API key (env: CLAWPERF_API_KEY). |
| `--tokenizer <TOKENIZER>` | `—` | Tokenizer path or model id (defaults to --model). A local directory is loaded strictly offline (no hub lookup); CLAWPERF_TOKENIZER_BACKEND=transformers\|modelscope forces a backend. |
| `--ignore-eos`<br>`--no-ignore-eos` | `on` | Ask the server to ignore EOS so every request decodes its full output length (the fair way to compare throughput).<br>Let the model stop naturally at EOS (realistic chat latencies). |
| `--request-timeout <REQUEST_TIMEOUT>` | `600` | Per-request timeout in seconds. |
| `--no-preflight` | `on` | Skip the pre-flight probe (the one tiny request sent before a run to catch a wrong endpoint/model). Use it when the server resets that probe but serves real traffic. |
| `--preflight-retries <PREFLIGHT_RETRIES>` | `3` | Attempts for the pre-flight probe before giving up (default: 3; transient connection errors are retried with backoff). |

### System Metrics

| Option | Default | Description |
|---|---|---|
| `--metrics-endpoint <URL>` | `—` | Prometheus metrics endpoint. Repeatable (or comma-separated) for multi-instance / PD-disaggregated services where every prefill/decode instance exposes its own /metrics — counters are summed into one fleet-wide view with a per-instance engine breakdown. Optional label via 'name=url' (default: host:port). |
| `--metrics-interval <METRICS_INTERVAL>` | `5` | Seconds between periodic /metrics polls (only with --metrics-samples). |
| `--metrics-samples` | `off` | Poll /metrics periodically during the run, not just at start/end (adds a little background traffic). |
| `--reset-cache` | `off` | Evict the server's prefix cache before the run so the measured hit rate reflects only this benchmark. |
| `--backend <BACKEND>` | `vllm` | Serving backend, which selects the Prometheus metric names to read.<br>**choices:** `vllm`, `sglang`, `mindie` |

### Output

| Option | Default | Description |
|---|---|---|
| `--output <OUTPUT>` | `—` | Output JSON file path (default: timestamped results_<ts>.json). Env: CLAWPERF_OUTPUT. |
| `--history <HISTORY>` | `—` | Append a one-line record to this JSONL file per run. Env: CLAWPERF_HISTORY. Pass '' to disable. |
| `-v`<br>`--verbose` | `off` | Log every request instead of a progress bar (useful in CI logs). |

### Configuration Files

| Option | Default | Description |
|---|---|---|
| `--config <CONFIG>` | `—` | YAML config file. Lower precedence than CLI args and env vars. |

#### Hit-Rate Mode (only with --mode hitrate) {#opt-hitrate}

| Option | Default | Description |
|---|---|---|
| `--num-requests <NUM_REQUESTS>` | `100` | Total requests in the measure phase. |
| `--input-len <INPUT_LEN>` | `1024` | Total prompt length per request = shared prefix + boundary + unique suffix. |
| `--output-len <OUTPUT_LEN>` | `128` | Generated tokens per request (the prefill phase uses 1). |
| `--prefix-len <PREFIX_LEN>` | `0` | Shared-prefix length in tokens (0 = derive it from --hit-rate). |
| `--hit-rate <HIT_RATE>` | `—` | Target shared fraction 0..1; derives --prefix-len. Mutually exclusive with --prefix-len. |
| `--prefix-num <PREFIX_NUM>` | `1` | Number of distinct prefixes; requests per prefix = N//prefix-num. |
| `--prefill`<br>`--no-prefill` | `on` | Inject every distinct prefix into the KV cache before measuring.<br>Skip the prefill phase, measuring cold-cache behaviour. |
| `--seed <SEED>` | `0` | Reproducibility seed for prompt construction. |

#### SLO Mode (only with --mode slo) {#opt-slo}

| Option | Default | Description |
|---|---|---|
| `--slo <SPEC>` | `—` | Flexible SLO constraint, repeatable: '<metric>.<agg><op><ms>', e.g. ttft.p99<=1500, tpot.avg<=30, e2e.max<=30000. Metrics: ttft\|tpot\|e2e; aggregates: avg\|min\|max\|p25\|p50\|p75\|p90\|p95\|p99(…); operators: <=\|<\|>=\|>. All constraints AND together. SHELL SAFETY: '<' and '>' are redirection operators, so quote the spec (--slo 'ttft.p99<=1500') or use the shell-safe separator form --slo ttft.p99:1500 (':' or '=' means '<=', and --slo ttft.p99\:ge:1500 means '>='). Several constraints may be comma-separated inside one quoted value: --slo 'ttft.p99<=1500,tpot.avg<=30'. When given, replaces the legacy --slo-ttft-ms/--slo-tpot-ms. |
| `--slo-ttft-ms <SLO_TTFT_MS>` | `—` | Legacy: TTFT threshold at --slo-percentile (prefer --slo ttft.p99<=X). |
| `--slo-tpot-ms <SLO_TPOT_MS>` | `—` | Legacy: TPOT threshold at --slo-percentile (prefer --slo tpot.p99<=X). |
| `--slo-percentile <SLO_PERCENTILE>` | `0.99` | Percentile for the legacy --slo-ttft-ms/--slo-tpot-ms thresholds (ignored when --slo constraints are given). |
| `--slo-error-rate <FRACTION>` | `—` | Extra pass condition: the step's error rate must stay at or below this fraction (0..1), e.g. 0.01 = 1%. |
| `--slo-min-users <SLO_MIN_USERS>` | `1` | Lowest concurrency level the sweep starts from. |
| `--slo-max-users <SLO_MAX_USERS>` | `100` | Highest concurrency level the sweep may reach. |
| `--slo-step-strategy <SLO_STEP_STRATEGY>` | `geometric` | How the sweep picks the next level: 'geometric' doubles (1→2→4→8, fast for large ranges), 'linear' increments by one level.<br>**choices:** `geometric`, `linear` |
| `--slo-step-turns <SLO_STEP_TURNS>` | `5` | Measured turns per user at each concurrency level. |
| `--slo-step-warmup-turns <SLO_STEP_WARMUP_TURNS>` | `1` | Unmeasured warm-up turns per user before each measured step. |
| `--slo-step-timeout-s <SLO_STEP_TIMEOUT_S>` | `300` | Wall-clock budget for one step; a step that overruns is reported as TIMEOUT and fails the SLO. |
| `--slo-step-reset-cache`<br>`--no-slo-step-reset-cache` | `on` | Evict the server's prefix cache before each step so every level starts cold.<br>Keep the cache warm across steps, measuring steady-state reuse. |

#### Agent Mode (only with --mode agent) {#opt-agent}

| Option | Default | Description |
|---|---|---|
| `--agent-tasks <AGENT_TASKS>` | `4` | Number of coding tasks to run concurrently. |
| `--agent-task-file <AGENT_TASK_FILE>` | `—` | JSON/YAML file with custom tasks (default: the built-in presets). |
| `--agent-max-steps <AGENT_MAX_STEPS>` | `12` | Max tool-calling steps per task before it is cut off. |
| `--agent-max-tokens <AGENT_MAX_TOKENS>` | `512` | Max generated tokens per model call inside a task. |
| `--agent-shell-timeout <AGENT_SHELL_TIMEOUT>` | `30` | Seconds a single shell command the agent runs may take. |
| `--agent-workdir <AGENT_WORKDIR>` | `—` | Base dir for per-task workspaces (default: a temp dir). |

#### Record Mode (only with --mode record) {#opt-record}

| Option | Default | Description |
|---|---|---|
| `--upstream-endpoint <UPSTREAM_ENDPOINT>` | `—` | Real LLM endpoint to forward requests to (env: CLAWPERF_UPSTREAM_ENDPOINT). |
| `--proxy-port <PROXY_PORT>` | `9090` | Port for the recording proxy to listen on. |
| `--recording <RECORDING>` | `session.jsonl` | JSONL file to write the recording to. |
| `--upstream-api <UPSTREAM_API>` | `auto` | API type of the upstream endpoint (auto-detected if 'auto').<br>**choices:** `openai`, `anthropic`, `auto` |

#### Replay Mode (only with --mode replay) {#opt-replay}

| Option | Default | Description |
|---|---|---|
| `--history-mode <HISTORY_MODE>` | `live` | 'live' (recommended): feeds actual server responses into the next turn's history, ensuring KV-cache prefix alignment. 'verbatim': sends each entry's messages as-is.<br>**choices:** `live`, `verbatim` |

#### Trace Mode (only with --mode trace) {#opt-trace}

| Option | Default | Description |
|---|---|---|
| `--trace-file <TRACE_FILE>` | `—` | JSONL trace file in kvcache.ai format: lines of {hash_ids, input_length, block_size?}. Supports .gz compression. Use '-' for stdin. |
| `--cache-budget-tokens <CACHE_BUDGET_TOKENS>` | `0` | Maximum KV cache capacity in tokens (0 = unlimited). For budget sweep, use --budget-sweep instead. |
| `--cache-budget-gb <CACHE_BUDGET_GB>` | `0.0` | Alternative: set cache budget in GB. Overrides --cache-budget-tokens. Converted using --kv-bytes-per-token. |
| `--eviction-policy <EVICTION_POLICY>` | `lru` | Block eviction policy when cache exceeds budget.<br>**choices:** `lru`, `fifo` |
| `--trace-block-size <TRACE_BLOCK_SIZE>` | `64` | Default block size in tokens (overridden per-trace-line if set). |
| `--trace-users <TRACE_USERS>` | `1` | Session-aware concurrency for real replay: how many user/session groups run at once when the trace carries user_id/session_id. Turns within a session stay ordered. Without user ids, use --concurrency for request-level parallelism instead. |
| `--budget-sweep` | `off` | Run the simulation at multiple budget levels to find the inflection point (diminishing returns). Outputs a hit-rate-vs-budget curve. |
| `--kv-bytes-per-token <KV_BYTES_PER_TOKEN>` | `2.0` | Bytes per KV cache token, for GB↔token conversion. Varies by model (e.g. DeepSeek MLA ~0.5, Qwen2.5 72B ~4.0). |

## Output & exit codes

| Code | Meaning |
|---|---|
| `0` | the benchmark ran; results written |
| `1` | configuration or pre-flight error (no benchmark ran) |
| `2` | the benchmark ran but **every** request failed (CI gate) |
| `3` | interrupted (Ctrl+C); partial results are written |

Every run writes a JSON result plus a Markdown report next to it. `clawperf report results.json` regenerates the report from any result, and `clawperf compare a.json b.json` diffs two runs.

## Troubleshooting {#trouble}

| Symptom | Fix |
|---|---|
| `bash: =10000: No such file or directory` | the shell ate the `<` in `--slo ttft.p99<=10000`. Use `--slo ttft.p99:10000` or quote the spec. |
| `Tokenizer path '...' does not exist` | the path is not visible inside the container — the error lists the parent directory; mount it with `-v /mnt/model:/mnt/model:ro`. |
| `Pre-flight: ... Connection reset by peer` | the server reset the tiny probe (often while still loading weights). Transient errors are retried 3× with backoff; add `--no-preflight` to skip the probe. |
| `UnicodeEncodeError` on Windows | the CLI already forces UTF-8 stdio; if a third-party tool still fails, set `PYTHONIOENCODING=utf-8`. |

More detail (including tokenizer backend selection) is in the [README](https://github.com/ucm-system/ClawPerf#troubleshooting) and the [E2E test report](E2E_TEST_REPORT.md).
