"""CLI argument parser for ClawPerf.

Supports both flat ``--mode X`` invocations (backward compatible) and
subcommands (``clawperf report``, ``clawperf compare``) for post-hoc
report generation.

Exit codes (CI-friendly):
  0  — benchmark ran and at least one request/turn succeeded.
  1  — configuration or pre-flight error (no benchmark ran).
  2  — benchmark ran but all requests/turns failed.
  3  — no benchmark ran (interrupted during setup).
"""

from __future__ import annotations

import argparse
import sys

from clawperf.config import BenchmarkConfig

# ── Flat parser (backward-compatible --mode usage) ───────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clawperf",
        description=(
            "ClawPerf - Performance testing tool for LLM Serving backends. "
            "Simulates multi-user, multi-turn, long-context workloads against "
            "vLLM, SGLang, and MindIE backends. "
            "Built on EvalScope's perf infrastructure."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # ── Mode ──
    g = parser.add_argument_group("Mode")
    g.add_argument("--mode", type=str, default="scenario",
                   choices=["scenario", "hitrate", "slo", "agent", "record", "replay", "trace"],
                   help="'scenario' (default): multi-turn long-context workload. "
                        "'hitrate': controlled prefix-cache hit-rate test. "
                        "'slo': sweep concurrency to find max users meeting TTFT/TPOT SLO. "
                        "'agent': real agent-at-work perf (model runs coding tasks via tool calls). "
                        "'record': recording proxy — capture a real agent session as JSONL. "
                        "'replay': replay a recorded session against an endpoint. "
                        "'trace': simulate KV-cache hit rate from a trace file (kvcache.ai format).")

    # ── Context profile / suite (convenience layer) ──
    g = parser.add_argument_group("Context Profiles & Suites")
    g.add_argument("--context-profile", type=str, default=None,
                   help="Named context-size profile: fresh(6K), short(20K), medium(40K), "
                        "long(70K), full(100K), xl(200K), xxl(400K). Overrides raw token counts.")
    g.add_argument("--suite", type=str, default=None,
                   help="Pre-configured suite: quick, standard, full, hitrate. "
                        "Runs multiple (users × profile) scenarios in sequence.")
    g.add_argument("--model-context-length", type=int, default=0,
                   help="Model's max context window. Suite profiles exceeding this are skipped (0=no limit).")

    # ── Hit-rate mode configuration ──
    g = parser.add_argument_group("Hit-Rate Mode (only with --mode hitrate)")
    g.add_argument("--num-requests", type=int, default=100)
    g.add_argument("--input-len", type=int, default=1024)
    g.add_argument("--output-len", type=int, default=128)
    g.add_argument("--prefix-len", type=int, default=0)
    g.add_argument("--hit-rate", type=float, default=None)
    g.add_argument("--prefix-num", type=int, default=1)
    g.add_argument("--prefill", action="store_true", default=True)
    g.add_argument("--no-prefill", action="store_false", dest="prefill")
    g.add_argument("--seed", type=int, default=0)

    # ── SLO mode configuration ──
    g = parser.add_argument_group("SLO Mode (only with --mode slo)")
    g.add_argument("--slo-ttft-ms", type=float, default=None)
    g.add_argument("--slo-tpot-ms", type=float, default=None)
    g.add_argument("--slo-percentile", type=float, default=0.99)
    g.add_argument("--slo-error-rate", type=float, default=None)
    g.add_argument("--slo-min-users", type=int, default=1)
    g.add_argument("--slo-max-users", type=int, default=100)
    g.add_argument("--slo-step-strategy", type=str, default="geometric", choices=["geometric", "linear"])
    g.add_argument("--slo-step-turns", type=int, default=5)
    g.add_argument("--slo-step-warmup-turns", type=int, default=1)
    g.add_argument("--slo-step-timeout-s", type=int, default=300)
    g.add_argument("--slo-step-reset-cache", action="store_true", default=True)
    g.add_argument("--no-slo-step-reset-cache", action="store_false", dest="slo_step_reset_cache")

    # ── Agent mode configuration ──
    g = parser.add_argument_group("Agent Mode (only with --mode agent)")
    g.add_argument("--agent-tasks", type=int, default=4)
    g.add_argument("--agent-task-file", type=str, default=None)
    g.add_argument("--agent-max-steps", type=int, default=12)
    g.add_argument("--agent-max-tokens", type=int, default=512)
    g.add_argument("--agent-shell-timeout", type=int, default=30)
    g.add_argument("--agent-workdir", type=str, default=None,
                   help="Base dir for per-task workspaces (default: a temp dir).")

    # ── Record mode configuration ──
    g = parser.add_argument_group("Record Mode (only with --mode record)")
    g.add_argument("--upstream-endpoint", type=str, default=None,
                   help="Real LLM endpoint to forward requests to (env: CLAWPERF_UPSTREAM_ENDPOINT).")
    g.add_argument("--proxy-port", type=int, default=9090,
                   help="Port for the recording proxy to listen on.")
    g.add_argument("--recording", type=str, default="session.jsonl",
                   help="JSONL file to write the recording to.")
    g.add_argument("--upstream-api", type=str, default="auto",
                   choices=["openai", "anthropic", "auto"],
                   help="API type of the upstream endpoint (auto-detected if 'auto').")

    # ── Replay mode configuration ──
    g = parser.add_argument_group("Replay Mode (only with --mode replay)")
    # --recording is shared with record mode.
    g.add_argument("--history-mode", type=str, default="live",
                   choices=["live", "verbatim"],
                   help="'live' (recommended): feeds actual server responses into the "
                        "next turn's history, ensuring KV-cache prefix alignment. "
                        "'verbatim': sends each entry's messages as-is.")

    # ── Trace mode configuration ──
    g = parser.add_argument_group("Trace Mode (only with --mode trace)")
    g.add_argument("--trace-file", type=str, default=None,
                   help="JSONL trace file in kvcache.ai format: "
                        "lines of {hash_ids, input_length, block_size?}. "
                        "Supports .gz compression. Use '-' for stdin.")
    g.add_argument("--cache-budget-tokens", type=int, default=0,
                   help="Maximum KV cache capacity in tokens (0 = unlimited). "
                        "For budget sweep, use --budget-sweep instead.")
    g.add_argument("--cache-budget-gb", type=float, default=0.0,
                   help="Alternative: set cache budget in GB. Overrides --cache-budget-tokens. "
                        "Converted using --kv-bytes-per-token.")
    g.add_argument("--eviction-policy", type=str, default="lru",
                   choices=["lru", "fifo"],
                   help="Block eviction policy when cache exceeds budget.")
    g.add_argument("--trace-block-size", type=int, default=64,
                   help="Default block size in tokens (overridden per-trace-line if set).")
    g.add_argument("--trace-users", type=int, default=1,
                   help="Session-aware concurrency for real replay: how many "
                        "user/session groups run at once when the trace carries "
                        "user_id/session_id. Turns within a session stay ordered. "
                        "Without user ids, use --concurrency for request-level "
                        "parallelism instead.")
    g.add_argument("--budget-sweep", action="store_true", default=False,
                   help="Run the simulation at multiple budget levels to find the "
                        "inflection point (diminishing returns). Outputs a "
                        "hit-rate-vs-budget curve.")
    g.add_argument("--kv-bytes-per-token", type=float, default=2.0,
                   help="Bytes per KV cache token, for GB↔token conversion. "
                   "Varies by model (e.g. DeepSeek MLA ~0.5, Qwen2.5 72B ~4.0).")

    # ── User configuration ──
    g = parser.add_argument_group("User Configuration")
    g.add_argument("--num-users", type=int, default=1, help="Total concurrent users.")
    g.add_argument("--user-arrival", type=str, default="burst",
                   help="'burst', 'steady:<seconds>', or 'poisson:<lambda>'.")

    # ── Context configuration ──
    g = parser.add_argument_group("Context Configuration")
    g.add_argument("--system-prefix-tokens", type=int, default=15000)
    g.add_argument("--system-prefix-source", type=str, default="random")
    g.add_argument("--user-prefix-tokens", type=int, default=5000)
    g.add_argument("--input-tokens-per-turn", type=int, default=5000)
    g.add_argument("--output-tokens-per-turn", type=int, default=1000)
    g.add_argument("--max-context-tokens", type=int, default=128000)
    g.add_argument("--compaction-prefix-increment", type=int, default=5000)

    # ── Run configuration ──
    g = parser.add_argument_group("Run Configuration")
    g.add_argument("--concurrency", type=int, default=1,
                   help="Request-level concurrency: in-flight requests for "
                        "hitrate measure phase, replay, and trace real replay "
                        "(no user ids). For trace sessions use --trace-users.")
    g.add_argument("--max-turns", type=int, default=100)
    g.add_argument("--max-consecutive-failures", type=int, default=0,
                   help="Abort the benchmark after this many consecutive failures (0=disabled).")

    # ── API configuration ──
    g = parser.add_argument_group("API Configuration")
    g.add_argument("--endpoint", type=str, default=None,
                   help="LLM API endpoint URL (env: CLAWPERF_ENDPOINT).")
    g.add_argument("--model", type=str, default=None,
                   help="Model name (env: CLAWPERF_MODEL).")
    g.add_argument("--api-key", type=str, default=None,
                   help="API key (env: CLAWPERF_API_KEY).")
    g.add_argument("--tokenizer", type=str, default=None,
                   help="Tokenizer path (defaults to --model).")
    g.add_argument("--ignore-eos", action="store_true", default=True)
    g.add_argument("--no-ignore-eos", action="store_false", dest="ignore_eos")
    g.add_argument("--request-timeout", type=int, default=600)

    # ── System metrics ──
    g = parser.add_argument_group("System Metrics")
    g.add_argument("--metrics-endpoint", type=str, default=None)
    g.add_argument("--metrics-interval", type=int, default=5)
    g.add_argument("--metrics-samples", action="store_true", default=False)
    g.add_argument("--reset-cache", action="store_true", default=False)
    g.add_argument("--backend", type=str, default="vllm", choices=["vllm", "sglang", "mindie"])

    # ── Output ──
    g = parser.add_argument_group("Output")
    g.add_argument("--output", type=str, default=None,
                   help="Output JSON file path (default: timestamped results_<ts>.json). "
                        "Env: CLAWPERF_OUTPUT.")
    g.add_argument("--history", type=str, default=None,
                   help="Append a one-line record to this JSONL file per run. "
                        "Env: CLAWPERF_HISTORY. Pass '' to disable.")
    g.add_argument("-v", "--verbose", action="store_true", default=False)

    # ── Config file ──
    g = parser.add_argument_group("Configuration Files")
    g.add_argument("--config", type=str, default=None,
                   help="YAML config file. Lower precedence than CLI args and env vars.")

    return parser


def parse_args(argv: list[str] | None = None) -> BenchmarkConfig:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Validate prefix-len / hit-rate mutual exclusivity.
    if getattr(args, "prefix_len", 0) and getattr(args, "hit_rate", None) is not None:
        parser.error("--prefix-len and --hit-rate are mutually exclusive; specify one.")

    # Build the CLI-override dict: only arguments the user *actually* passed,
    # so argparse defaults don't clobber CLAWPERF_* env vars / YAML values.
    default_ns = parser.parse_args([])
    defaults = vars(default_ns)
    raw_flags = set()
    if argv is not None:
        for tok in argv:
            if tok.startswith("--"):
                raw_flags.add(tok.split("=")[0])
    dest_flags: dict = {}
    for opt, act in parser._option_string_actions.items():
        dest_flags.setdefault(act.dest, opt)

    cli_args: dict = {}
    for k, v in vars(args).items():
        if v is None:
            continue
        if isinstance(v, bool):
            flag = dest_flags.get(k)
            # Booleans are only kept when explicitly passed (--flag / --no-flag).
            if flag in raw_flags:
                cli_args[k] = v
            continue
        if v != defaults.get(k):
            cli_args[k] = v

    # Use layered config: CLI > env vars > YAML > defaults.
    from clawperf.config import build_config
    return build_config(cli_args, yaml_path=getattr(args, "config", ""))


# ── Subcommand: report ───────────────────────────────────────────────────────

def _run_report(args: argparse.Namespace):
    """Regenerate a Markdown report from a saved JSON result file."""
    from clawperf.report import generate_report, load_result

    result = load_result(args.input)
    out = args.output or args.input.rsplit(".", 1)[0] + ".md"
    md = generate_report(result, output_path=out)
    print(f"Report saved to: {out}")
    if args.print:
        print(md)


def _run_compare(args: argparse.Namespace):
    """Compare two result JSON files side-by-side."""
    from clawperf.report import generate_comparison, load_result

    ra = load_result(args.run_a)
    rb = load_result(args.run_b)
    out = args.output or "comparison.md"
    md = generate_comparison(ra, rb, label_a=args.label_a, label_b=args.label_b,
                             output_path=out)
    print(f"Comparison saved to: {out}")
    if args.print:
        print(md)


def build_report_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clawperf report", description="Generate a Markdown report from a saved JSON result.")
    p.add_argument("input", type=str, help="Path to the results JSON file.")
    p.add_argument("--output", "-o", type=str, default="", help="Output .md file path (default: <input>.md)")
    p.add_argument("--print", action="store_true", help="Also print the markdown to stdout.")
    return p


def build_compare_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clawperf compare", description="Compare two result JSON files side-by-side.")
    p.add_argument("run_a", type=str, help="Path to the first results JSON.")
    p.add_argument("run_b", type=str, help="Path to the second results JSON.")
    p.add_argument("--label-a", type=str, default="A", help="Label for the first run.")
    p.add_argument("--label-b", type=str, default="B", help="Label for the second run.")
    p.add_argument("--output", "-o", type=str, default="", help="Output .md file path.")
    p.add_argument("--print", action="store_true", help="Also print the markdown to stdout.")
    return p


def build_trace_convert_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clawperf trace-convert",
        description="Convert external agent-trace datasets into a ClawPerf replayable trace.",
    )
    p.add_argument("inputs", nargs="+", help="Input trace file(s). Supported formats: "
                   "Claude Code session JSONL, ShareGPT conversations, OpenAI messages JSONL.")
    p.add_argument("--output", "-o", type=str, default="trace.jsonl",
                   help="Output trace JSONL path (default: trace.jsonl).")
    p.add_argument("--block-size", type=int, default=64,
                   help="Block size in tokens for hash_ids (default 64).")
    p.add_argument("--max-turns", type=int, default=0,
                   help="For ShareGPT: emit one request per assistant turn up to this many "
                        "turns (0 = whole conversation as one request). For Claude Code: "
                        "cap requests to the last N turns.")
    return p


def _run_trace_convert(args: argparse.Namespace):
    from clawperf.trace_converter import (
        convert_many, detect_format, write_trace,
    )

    for inp in args.inputs:
        fmt = detect_format(inp)
        print(f"  {inp}: detected {fmt}")
    lines = convert_many(args.inputs, block_size=args.block_size, max_requests=args.max_turns)
    if not lines:
        print("[ClawPerf] No replayable requests found in the input files.", file=sys.stderr)
        sys.exit(EXIT_CONFIG_ERROR)
    write_trace(lines, args.output)
    sessions = {}
    for l in lines:
        sessions[l["user_id"]] = sessions.get(l["user_id"], 0) + 1
    print(f"\nConverted {len(lines)} requests across {len(sessions)} session(s):")
    for uid in sorted(sessions):
        print(f"  session {uid}: {sessions[uid]} requests")
    print(f"Output: {args.output}")


# ── Main entry ───────────────────────────────────────────────────────────────

# Exit codes.
EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_ALL_FAILED = 2
EXIT_INTERRUPTED = 3

_SUBCOMMANDS = {
    "report": build_report_parser,
    "compare": build_compare_parser,
    "trace-convert": build_trace_convert_parser,
}


def main():
    # Check for subcommands first (report, compare, trace-convert).
    if len(sys.argv) > 1 and sys.argv[1] in _SUBCOMMANDS:
        subcmd = sys.argv[1]
        parser = _SUBCOMMANDS[subcmd]()
        args = parser.parse_args(sys.argv[2:])
        if subcmd == "report":
            _run_report(args)
        elif subcmd == "compare":
            _run_compare(args)
        elif subcmd == "trace-convert":
            _run_trace_convert(args)
        sys.exit(EXIT_OK)

    # Flat parser: --mode X --endpoint ... (backward compatible).
    config = parse_args()

    from clawperf.logging_setup import setup_logging

    setup_logging(verbose=config.verbose)

    # Dispatch to the recording proxy or replay player for the new modes.
    # (BenchmarkRunner is imported lazily inside the standard-modes branch so
    # record/replay/trace don't need its heavier dependencies.)
    if config.mode == "record":
        import asyncio

        from clawperf.recorder import run_proxy
        try:
            asyncio.run(run_proxy(
                upstream_endpoint=config.upstream_endpoint,
                recording_path=config.recording,
                proxy_port=config.proxy_port,
                upstream_api=config.upstream_api,
                api_key=config.api_key,
            ))
        except KeyboardInterrupt:
            print("\n[ClawPerf] Recording proxy stopped.")
        sys.exit(EXIT_OK)

    if config.mode == "replay":
        import asyncio

        from clawperf.player import ReplayPlayer, load_recording, summarize_replay

        async def _replay():
            entries = load_recording(config.recording)
            player = ReplayPlayer(
                endpoint=config.endpoint, model=config.model,
                api_key=config.api_key, timeout=config.request_timeout,
                concurrency=config.concurrency, history_mode=config.history_mode,
            )
            results = await player.replay(entries)
            await player.close()

            summary = summarize_replay(results)
            result = {
                "config": config.to_dict(),
                "summary": summary,
                "results": [
                    {
                        "index": r.index, "success": r.success,
                        "ttft_ms": r.ttft_ms, "e2e_ms": round(r.e2e_ms, 3),
                        "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                        "itl_count": len(r.itl_values),
                        "error": r.error,
                    }
                    for r in results
                ],
                "timing": {"bench_time_s": round(
                    sum(r.e2e_ms for r in results) / 1000, 3
                )},
            }

            import json
            import os
            out_dir = os.path.dirname(config.output)
            if out_dir and not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)
            with open(config.output, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False, default=str)

            # Generate Markdown report.
            from clawperf.report import generate_report
            md_path = config.output.rsplit(".", 1)[0] + ".md"
            generate_report(result, output_path=md_path)

            # Print summary.
            print(f"\n{'=' * 70}")
            print("ClawPerf - Replay Complete")
            print(f"{'=' * 70}")
            print(f"  Entries:      {summary['total_requests']}")
            print(f"  Success:      {summary['success_count']}")
            print(f"  Errors:       {summary['error_count']}")
            print(f"  TTFT P50:     {summary['ttft_p50_ms']:.1f}ms" if summary.get('ttft_p50_ms') else "  TTFT P50:     N/A")
            print(f"  TTFT P95:     {summary['ttft_p95_ms']:.1f}ms" if summary.get('ttft_p95_ms') else "  TTFT P95:     N/A")
            print(f"  Decode tok/s: {summary['decode_tok_s']:.1f}" if summary.get('decode_tok_s') else "  Decode tok/s: N/A")
            print(f"  Results:      {config.output}")
            print(f"  Report:       {md_path}")
            print(f"{'=' * 70}")

            if summary["success_count"] == 0:
                sys.exit(EXIT_ALL_FAILED)

        try:
            asyncio.run(_replay())
        except KeyboardInterrupt:
            print("\n[ClawPerf] Replay interrupted.")
            sys.exit(EXIT_INTERRUPTED)
        sys.exit(EXIT_OK)

    if config.mode == "trace":
        import asyncio
        import json as _json
        import os as _os

        from clawperf.report import generate_report
        from clawperf.trace_simulator import (
            budget_sweep,
            default_budget_levels,
            load_trace,
            simulate_trace,
            summarize_simulation,
        )

        # Resolve trace file (can be from env/YAML too).
        trace_path = config.trace_file
        if not trace_path:
            print("[ClawPerf] trace: --trace-file is required.", file=sys.stderr)
            sys.exit(EXIT_CONFIG_ERROR)

        # Load trace.
        print(f"\n{'=' * 70}")
        print("ClawPerf - Trace-Based KV-Cache Hit-Rate Simulator")
        print(f"{'=' * 70}")
        print(f"  Trace:        {trace_path}")
        print(f"  Block size:   {config.trace_block_size}")
        print(f"  Policy:       {config.eviction_policy}")
        print(f"{'=' * 70}\n")

        entries, stats = load_trace(
            trace_path,
            block_size=config.trace_block_size,
        )
        print(f"  Requests:     {stats.request_count}")
        print(f"  Total tokens: {stats.total_input_tokens:,}")
        print(f"  Unique blocks: {stats.unique_blocks:,}")
        print(f"  Avg input:    {stats.average_input_tokens:.0f} tokens")
        if stats.parse_errors:
            print(f"  Parse errors: {stats.parse_errors}")
        if stats.has_messages:
            print("  Has messages: yes (real-request replay available)")
        print()

        # Resolve budget: GB → tokens.
        budget_tokens = config.cache_budget_tokens
        if config.cache_budget_gb > 0:
            budget_tokens = int(config.cache_budget_gb * (1024**3) / config.kv_bytes_per_token)
            print(f"  Budget:       {config.cache_budget_gb:.1f} GB = {budget_tokens:,} tokens "
                  f"({config.kv_bytes_per_token} B/tok)")
        elif budget_tokens > 0:
            print(f"  Budget:       {budget_tokens:,} tokens")
        else:
            print("  Budget:       unlimited (ceiling calculation)")

        if config.budget_sweep:
            # Run budget sweep across multiple levels.
            levels = default_budget_levels(stats.total_input_tokens, config.trace_block_size)
            # Add the user-specified budget if not already in the list.
            if budget_tokens > 0 and budget_tokens not in levels:
                levels.append(budget_tokens)
                levels.sort()
            print(f"  Sweep:        {len(levels)} budget levels")
            print()

            sweep = budget_sweep(
                entries, levels,
                policy=config.eviction_policy,
                block_size=config.trace_block_size,
            )

            # Single-run result at the max budget level (= ceiling). The headline
            # hit rate reflects what the cache achieves at full capacity; the
            # inflection point (diminishing returns) stays available separately.
            sim_budget = sweep.levels[-1]["budget_tokens"] if sweep.levels else 0
            result = simulate_trace(
                entries, sim_budget,
                policy=config.eviction_policy,
                block_size=config.trace_block_size,
            )

            summary = summarize_simulation(entries, stats, result, sweep)
            print(f"  Ceiling (unlimited):    {sweep.ceiling * 100:.2f}%")
            print(f"  Inflection budget:      {sweep.inflection_budget:,} tokens "
                  f"(hit rate: {sweep.inflection_hit_rate * 100:.2f}%)")
            print()
            print("  Budget Sweep Results:")
            print(f"  {'Budget (tokens)':>16s}  {'Hit Rate':>8s}  {'Speedup':>8s}  {'Evictions':>10s}")
            for lv in sweep.levels:
                print(f"  {lv['budget_tokens']:>16,}  {lv['hit_rate']*100:>7.2f}%  "
                      f"{lv['speedup']:>7.2f}x  {lv['evictions']:>10,}")
        else:
            # Single simulation.
            result = simulate_trace(
                entries, budget_tokens,
                policy=config.eviction_policy,
                block_size=config.trace_block_size,
            )
            summary = summarize_simulation(entries, stats, result)
            print(f"\n  Hit Rate:    {result.hit_rate * 100:.2f}%")
            print(f"  Ceiling:     {result.ceiling * 100:.2f}%")
            print(f"  Speedup:     {result.speedup:.2f}x  (= 1 / (1 - hit_rate))")
            print(f"  Hit tokens:  {result.hit_tokens:,}")
            print(f"  Miss tokens: {result.miss_tokens:,}")
            if result.evictions:
                print(f"  Evictions:   {result.evictions:,}")
            print(f"  Cache blocks: {result.cache_blocks:,}")

        # ── Real request replay (if the trace carries messages + an endpoint) ──
        replay_records: list = []
        if stats.has_messages:
            if config.endpoint and config.model:
                print("\n  Real replay: sending requests to {} (model={}) ...".format(
                    config.endpoint, config.model))
                from clawperf.trace_simulator import (
                    replay_summary,
                    replay_trace_requests,
                )

                async def _replay():
                    results, bench_s = await replay_trace_requests(
                        entries,
                        endpoint=config.endpoint,
                        model=config.model,
                        api_key=config.api_key,
                        timeout=config.request_timeout,
                        concurrency=config.concurrency,
                        active_users=config.trace_users,
                        max_tokens=config.output_tokens_per_turn,
                    )
                    return results, bench_s

                replayed, bench_s = asyncio.run(_replay())
                rsum = replay_summary(replayed)
                summary["replay"] = rsum
                replay_records = [
                    {
                        "index": r.index, "success": r.success,
                        "ttft_ms": r.ttft_ms, "e2e_ms": round(r.e2e_ms, 3),
                        "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                        "itl_count": len(r.itl_values),
                        "error": r.error, "status_code": r.status_code,
                    }
                    for r in replayed
                ]
                print(f"  Replay:      {rsum['success_count']}/{len(replayed)} succeeded")
                print(f"  TTFT P50:    {rsum['ttft_p50_ms']:.1f}ms" if rsum.get("ttft_p50_ms") else "  TTFT P50:    N/A")
                print(f"  Decode:      {rsum['decode_tok_s']:.1f} tok/s" if rsum.get("decode_tok_s") else "  Decode:      N/A")
                print(f"  Replay wall: {bench_s:.1f}s")
            else:
                print("\n  Real replay: trace has messages but no --endpoint/--model "
                      "(simulation only). Pass both to also replay real requests.")
        else:
            print("\n  Real replay: trace has no messages (simulation only).")

        # Save results.
        result_dict = {
            "config": config.to_dict(),
            "summary": summary,
            "trace_stats": {
                "request_count": stats.request_count,
                "total_input_tokens": stats.total_input_tokens,
                "unique_blocks": stats.unique_blocks,
                "total_blocks": stats.total_blocks,
                "average_input_tokens": stats.average_input_tokens,
                "block_size": stats.block_size,
                "parse_errors": stats.parse_errors,
                "has_messages": stats.has_messages,
            },
            "timing": {"bench_time_s": round(bench_s, 3)} if replay_records else {"bench_time_s": 0.0},
        }
        if replay_records:
            result_dict["replay_results"] = replay_records
        out_dir = _os.path.dirname(config.output)
        if out_dir and not _os.path.exists(out_dir):
            _os.makedirs(out_dir, exist_ok=True)
        with open(config.output, "w", encoding="utf-8") as f:
            _json.dump(result_dict, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  Results:     {config.output}")

        # Generate Markdown report.
        md_path = config.output.rsplit(".", 1)[0] + ".md"
        generate_report(result_dict, output_path=md_path)
        print(f"  Report:      {md_path}")
        print(f"{'=' * 70}")

        # CI exit code: 2 when a real replay ran and every request failed.
        if replay_records and rsum.get("success_count", 0) == 0:
            sys.exit(EXIT_ALL_FAILED)
        sys.exit(EXIT_OK)

    # Standard benchmark modes (scenario / hitrate / slo / agent).
    import asyncio

    from clawperf.runner import BenchmarkRunner

    # ── Suite mode: expand --suite into sequential (users × profile) scenarios ──
    if config.suite:
        if config.mode != "scenario":
            print("[ClawPerf] --suite is only valid with --mode scenario.", file=sys.stderr)
            sys.exit(EXIT_CONFIG_ERROR)
        import dataclasses
        import os as _os2

        from clawperf.context_profiles import resolve_suite, suite_settings

        try:
            scenarios = resolve_suite(config.suite, config.model_context_length)
        except ValueError as e:
            print(f"[ClawPerf] {e}", file=sys.stderr)
            sys.exit(EXIT_CONFIG_ERROR)
        if not scenarios:
            print("[ClawPerf] suite: every profile exceeds the model context window; nothing to run.",
                  file=sys.stderr)
            sys.exit(EXIT_CONFIG_ERROR)

        base_out = config.output
        stem, ext = _os2.path.splitext(base_out)
        suite_cfg = suite_settings(config.suite)
        all_failed = True
        for (users, profile, tokens) in scenarios:
            sub = dataclasses.replace(
                config,
                num_users=users,
                context_profile="",
                suite="",  # keep it one level deep
                system_prefix_tokens=tokens["system_prefix_tokens"],
                user_prefix_tokens=tokens["user_prefix_tokens"],
                input_tokens_per_turn=tokens["input_tokens_per_turn"],
                max_turns=suite_cfg["max_turns"],
                output_tokens_per_turn=suite_cfg["output_tokens_per_turn"],
                output=f"{stem}_{profile}_{users}u{ext}",
            )
            print(f"\n=== Suite [{config.suite}] scenario: profile={profile} users={users} "
                  f"(sys={tokens['system_prefix_tokens']:,} usr={tokens['user_prefix_tokens']:,} "
                  f"in={tokens['input_tokens_per_turn']:,} tokens, "
                  f"turns={suite_cfg['max_turns']}) ===", flush=True)
            runner = BenchmarkRunner(sub)
            try:
                asyncio.run(runner.run())
            except KeyboardInterrupt:
                setup_logging(verbose=config.verbose)
                print("\n[ClawPerf] Interrupted. Saving partial results...", file=sys.stderr)
                try:
                    asyncio.run(runner.shutdown_and_save())
                except Exception:
                    pass
                sys.exit(EXIT_INTERRUPTED)
            except RuntimeError as e:
                print(f"\n[ClawPerf] {e}", file=sys.stderr)
                sys.exit(EXIT_CONFIG_ERROR)
            if not runner._has_all_failures():
                all_failed = False
        sys.exit(EXIT_ALL_FAILED if all_failed else EXIT_OK)

    runner = BenchmarkRunner(config)
    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        setup_logging(verbose=config.verbose)
        print("\n[ClawPerf] Interrupted. Saving partial results...")
        try:
            asyncio.run(runner.shutdown_and_save())
        except Exception as e:
            print(f"[ClawPerf] Failed to save partial results: {e}", file=sys.stderr)
        sys.exit(EXIT_INTERRUPTED)
    except RuntimeError as e:
        print(f"\n[ClawPerf] {e}", file=sys.stderr)
        sys.exit(EXIT_CONFIG_ERROR)

    # CI exit code: all-failed → 2, success → 0.
    if runner._has_all_failures():
        sys.exit(EXIT_ALL_FAILED)
    sys.exit(EXIT_OK)
