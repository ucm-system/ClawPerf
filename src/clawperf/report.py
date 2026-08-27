"""Markdown report generator with verdict system and ASCII charts.

Produces a self-contained ``.md`` file from a ClawPerf result JSON, suitable
for pasting into GitHub PRs, issues, or wikis. Inspired by agentic-swarm-bench's
``report/markdown.py`` (verdicts, auto-findings, ASCII charts).

Usage as a library::

    from clawperf.report import generate_report
    generate_report(result_dict, output_path="report.md")

Or via CLI::

    clawperf report --input results_20240101_120000.json
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

# ── Verdict thresholds ───────────────────────────────────────────────────────
# These map raw numbers to human-feel quality bands. Tuned for coding-agent
# workloads: agents are more latency-sensitive than batch inference because
# the user is watching the stream in real time.

TTFT_GOOD_MS = 3_000   # under 3s = "instant" start
TTFT_OK_MS = 10_000    # under 10s = "responsive"; above = "slow start"

TOKS_GOOD = 30          # 30+ tok/s = "smooth" streaming
TOKS_OK = 15            # 15-30 tok/s = "acceptable"; below = "sluggish"

# Icon/color mapping for tables (plain text — no ANSI for .md portability).
_VERDICT_ICONS = {"GOOD": "✅", "MARGINAL": "⚠️", "POOR": "❌"}
_TTFT_FEEL = {0: "instant", 1: "responsive", 2: "slight pause", 3: "slow start"}
_TOKS_FEEL = {0: "smooth", 1: "acceptable", 2: "slow streaming", 3: "sluggish"}


def _ttft_grade(ttft_ms: Optional[float]) -> Tuple[str, str]:
    """Return (verdict, feel_label) for a TTFT value."""
    if ttft_ms is None:
        return ("POOR", "N/A")
    if ttft_ms <= TTFT_GOOD_MS:
        return ("GOOD", _TTFT_FEEL[0])
    if ttft_ms <= TTFT_OK_MS:
        return ("MARGINAL", _TTFT_FEEL[1])
    if ttft_ms <= 20_000:
        return ("MARGINAL", _TTFT_FEEL[2])
    return ("POOR", _TTFT_FEEL[3])


def _toks_grade(toks: Optional[float]) -> Tuple[str, str]:
    """Return (verdict, feel_label) for a decode throughput value."""
    if toks is None or toks <= 0:
        return ("POOR", "N/A")
    if toks >= TOKS_GOOD:
        return ("GOOD", _TOKS_FEEL[0])
    if toks >= TOKS_OK:
        return ("MARGINAL", _TOKS_FEEL[1])
    if toks >= 5:
        return ("MARGINAL", _TOKS_FEEL[2])
    return ("POOR", _TOKS_FEEL[3])


def _verdict_from_grades(grades: List[str]) -> str:
    """Aggregate per-metric grades into one overall verdict."""
    if not grades:
        return "POOR"
    if all(g == "GOOD" for g in grades):
        return "GOOD"
    if any(g == "POOR" for g in grades):
        return "POOR"
    return "MARGINAL"


def _percentile(values: list, q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n == 1:
        return s[0]
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def _bar(value: float, max_val: float, width: int = 30, fill: str = "█", empty: str = "░") -> str:
    """Render a horizontal ASCII bar."""
    if max_val <= 0:
        return empty * width
    ratio = min(value / max_val, 1.0) if value > 0 else 0.0
    n_fill = int(ratio * width)
    return fill * n_fill + empty * (width - n_fill)


def _fmt_ms(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    if v >= 10_000:
        return f"{v / 1000:.1f}s"
    return f"{v:.0f}ms"


def _fmt_toks(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:.1f}"


# ── Mode-specific verdict extraction ─────────────────────────────────────────

def _scenario_verdict(result: Dict) -> Dict:
    """Extract verdict-relevant metrics from a scenario-mode result."""
    summary = result.get("summary", {})
    users = result.get("users", [])

    all_ttft = []
    all_tpot = []
    all_decode_toks = []
    for u in users:
        agg = u.get("aggregate", {})
        ttft = agg.get("ttft", {})
        tpot = agg.get("tpot", {})
        all_ttft.append(ttft.get("P50", 0) or 0)
        all_tpot.append(tpot.get("P50", 0) or 0)
        if agg.get("throughput_tok_s"):
            all_decode_toks.append(agg["throughput_tok_s"])

    # Use minimum-concurrency user (user 0) as the primary verdict point.
    primary_ttft = all_ttft[0] if all_ttft else None
    primary_tpot = all_tpot[0] if all_tpot else None
    primary_decode = all_decode_toks[0] if all_decode_toks else None

    ttft_v, ttft_f = _ttft_grade(primary_ttft)
    toks_v, toks_f = _toks_grade(primary_decode)
    overall = _verdict_from_grades([ttft_v, toks_v])

    return {
        "overall": overall,
        "ttft_grade": ttft_v,
        "ttft_feel": ttft_f,
        "toks_grade": toks_v,
        "toks_feel": toks_f,
        "p50_ttft_ms": primary_ttft,
        "p50_tpot_ms": primary_tpot,
        "decode_toks": primary_decode,
        "num_users": len(users),
        "compactions": summary.get("total_compactions", 0),
    }


def _hitrate_verdict(result: Dict) -> Dict:
    summary = result.get("summary", {})
    target = summary.get("target_hit_rate")
    measured = summary.get("measured_hit_rate")
    ttft = summary.get("ttft", {}).get("P50")

    grades = []
    if measured is not None and target is not None:
        if measured >= target * 0.95:
            grades.append("GOOD")
        elif measured >= target * 0.80:
            grades.append("MARGINAL")
        else:
            grades.append("POOR")
    ttft_v, ttft_f = _ttft_grade(ttft)
    grades.append(ttft_v)

    return {
        "overall": _verdict_from_grades(grades),
        "target_hit_rate": target,
        "measured_hit_rate": measured,
        "p50_ttft_ms": ttft,
        "ttft_grade": ttft_v,
        "ttft_feel": ttft_f,
    }


def _slo_verdict(result: Dict) -> Dict:
    summary = result.get("summary", {})
    max_users = summary.get("max_sustained_users", 0)
    steps = result.get("capacity_curve", [])

    if max_users > 0:
        overall = "GOOD"
    elif steps:
        overall = "MARGINAL"
    else:
        overall = "POOR"

    return {
        "overall": overall,
        "max_sustained_users": max_users,
        "slo_label": summary.get("slo", ""),
        "steps_tested": summary.get("steps_tested", 0),
    }


def _agent_verdict(result: Dict) -> Dict:
    summary = result.get("summary", {})
    ttft = summary.get("ttft", {}).get("P50")
    tasks = summary.get("tasks_finished", 0)
    total = summary.get("tasks_run", 1)
    finish_rate = tasks / total if total else 0

    ttft_v, ttft_f = _ttft_grade(ttft)
    if finish_rate >= 0.75:
        finish_v = "GOOD"
    elif finish_rate >= 0.25:
        finish_v = "MARGINAL"
    else:
        finish_v = "POOR"

    return {
        "overall": _verdict_from_grades([ttft_v, finish_v]),
        "p50_ttft_ms": ttft,
        "ttft_grade": ttft_v,
        "ttft_feel": ttft_f,
        "tasks_finished": tasks,
        "tasks_run": total,
        "finish_rate": finish_rate,
    }


def _trace_verdict(result: Dict) -> Dict:
    """Verdict for trace-based KV-cache simulation results."""
    summary = result.get("summary", {})
    hit_rate = summary.get("hit_rate", 0.0)
    ceiling = summary.get("ceiling", 0.0)
    speedup = summary.get("speedup", 1.0)

    # Grade by how close the achieved hit rate is to the ceiling.
    if ceiling > 0:
        ratio = hit_rate / ceiling
    else:
        ratio = hit_rate

    if ratio >= 0.90 or hit_rate >= 0.80:
        hit_grade = "GOOD"
    elif ratio >= 0.50 or hit_rate >= 0.30:
        hit_grade = "MARGINAL"
    else:
        hit_grade = "POOR"

    # If real-request replay ran, fold the measured TTFT into the verdict.
    replay = summary.get("replay")
    p50_ttft = replay.get("ttft_p50_ms") if replay else None
    ttft_grade, ttft_feel = None, None
    if p50_ttft is not None:
        ttft_v, ttft_f = _ttft_grade(p50_ttft)
        ttft_grade, ttft_feel = ttft_v, ttft_f

    return {
        "overall": _verdict_from_grades([hit_grade, ttft_grade]) if ttft_grade else hit_grade,
        "hit_rate": hit_rate,
        "ceiling": ceiling,
        "speedup": speedup,
        "hit_rate_grade": hit_grade,
        "inflection_budget_tokens": summary.get("inflection_budget_tokens", 0),
        "inflection_hit_rate": summary.get("inflection_hit_rate", 0.0),
        "policy": summary.get("policy", "lru"),
        "request_count": summary.get("request_count", 0),
        "p50_ttft_ms": p50_ttft,
        "ttft_grade": ttft_grade,
        "ttft_feel": ttft_feel,
        "replay_decode_tok_s": replay.get("decode_tok_s") if replay else None,
    }


def compute_verdict(result: Dict) -> Dict:
    """Dispatch to the mode-specific verdict extractor."""
    mode = result.get("summary", {}).get("mode") or result.get("config", {}).get("mode", "scenario")
    if mode == "hitrate":
        return _hitrate_verdict(result)
    if mode == "slo":
        return _slo_verdict(result)
    if mode == "agent":
        return _agent_verdict(result)
    if mode == "trace":
        return _trace_verdict(result)
    return _scenario_verdict(result)


# ── Key findings auto-generation ──────────────────────────────────────────────

def _key_findings(result: Dict, verdict: Dict) -> List[str]:
    findings: List[str] = []
    mode = result.get("summary", {}).get("mode", "scenario")

    if mode == "scenario":
        users = result.get("users", [])
        if len(users) >= 2:
            ttft_vals = [u.get("aggregate", {}).get("ttft", {}).get("P50", 0) or 0 for u in users]
            if ttft_vals:
                ratio = max(ttft_vals) / max(min(ttft_vals), 1)
                if ratio > 2:
                    findings.append(
                        f"TTFT degrades {ratio:.1f}× from {min(ttft_vals):.0f}ms (1 user) "
                        f"to {max(ttft_vals):.0f}ms ({len(users)} users) — concurrency contention"
                    )
            thru_vals = [u.get("aggregate", {}).get("throughput_tok_s", 0) or 0 for u in users]
            if thru_vals:
                findings.append(
                    f"Per-user decode throughput ranges {min(thru_vals):.1f}–{max(thru_vals):.1f} tok/s"
                )
                eff = max(thru_vals) / (min(thru_vals) * len(users)) * 100 if min(thru_vals) else 0
                findings.append(f"Concurrency efficiency: {eff:.0f}% (max_thru / (min_thru × N))")
        comp = verdict.get("compactions", 0)
        if comp:
            findings.append(f"Context compaction triggered {comp} time(s) — history eviction active")
    elif mode == "hitrate":
        target = verdict.get("target_hit_rate")
        measured = verdict.get("measured_hit_rate")
        if target is not None and measured is not None:
            findings.append(f"Target hit rate: {target*100:.1f}%  |  Measured: {measured*100:.1f}%")
    elif mode == "slo":
        max_u = verdict.get("max_sustained_users", 0)
        findings.append(f"Max sustained users meeting SLO: {max_u}")
        findings.append(f"SLO criteria: {verdict.get('slo_label', '(none)')}")
    elif mode == "agent":
        fr = verdict.get("finish_rate", 0)
        findings.append(f"Task completion rate: {fr*100:.0f}% ({verdict['tasks_finished']}/{verdict['tasks_run']})")
    elif mode == "trace":
        hr = verdict.get("hit_rate", 0)
        ceil = verdict.get("ceiling", 0)
        sp = verdict.get("speedup", 1.0)
        findings.append(f"KV cache hit rate: {hr*100:.2f}%  (ceiling: {ceil*100:.2f}%)")
        findings.append(f"Ideal prefill speedup: {sp:.2f}x  (= 1 / (1 - {hr*100:.2f}%))")
        if verdict.get("inflection_budget_tokens"):
            findings.append(
                f"Inflection point: {verdict['inflection_budget_tokens']:,} tokens "
                f"(hit rate: {verdict.get('inflection_hit_rate', 0)*100:.2f}%)"
            )
        if verdict.get("p50_ttft_ms") is not None:
            findings.append(
                f"Real replay: TTFT P50 {_fmt_ms(verdict['p50_ttft_ms'])}, "
                f"decode {_fmt_toks(verdict.get('replay_decode_tok_s'))} tok/s"
            )
        return findings  # trace mode already reports TTFT above

    if verdict.get("p50_ttft_ms") is not None:
        findings.append(
            f"P50 TTFT: {_fmt_ms(verdict['p50_ttft_ms'])} — {verdict.get('ttft_feel', 'N/A')}"
        )

    return findings


# ── Markdown rendering ───────────────────────────────────────────────────────

def _md_header(result: Dict) -> str:
    cfg = result.get("config", {})
    summary = result.get("summary", {})
    mode = summary.get("mode", "scenario")
    lines = [
        "# ClawPerf Benchmark Report",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Model | `{cfg.get('model', 'N/A')}` |",
        f"| Endpoint | `{cfg.get('endpoint', 'N/A')}` |",
        f"| Backend | {cfg.get('backend', 'N/A')} |",
        f"| Mode | `{mode}` |",
    ]
    if mode == "scenario":
        lines.append(f"| Users | {cfg.get('num_users', 'N/A')} |")
        lines.append(f"| Max Turns | {cfg.get('max_turns', 'N/A')} |")
        lines.append(f"| Context | sys={cfg.get('system_prefix_tokens', '?')} + "
                     f"usr={cfg.get('user_prefix_tokens', '?')} + "
                     f"in={cfg.get('input_tokens_per_turn', '?')} tokens |")
    elif mode == "hitrate":
        lines.append(f"| Input Len | {summary.get('input_len', 'N/A')} |")
        lines.append(f"| Prefix Len | {summary.get('prefix_len', 'N/A')} |")
        lines.append(f"| Concurrency | {cfg.get('concurrency', 1)} |")
    elif mode == "slo":
        lines.append(f"| SLO | {summary.get('slo', 'N/A')} |")
        lines.append(f"| Max Users | {summary.get('max_sustained_users', 0)} |")
    elif mode == "agent":
        lines.append(f"| Tasks | {summary.get('tasks_run', 'N/A')} |")
        lines.append(f"| Max Steps | {cfg.get('agent_max_steps', 'N/A')} |")
    elif mode == "trace":
        lines.append(f"| Requests | {summary.get('request_count', 'N/A')} |")
        lines.append(f"| Total Tokens | {summary.get('total_input_tokens', 0):,} |")
        lines.append(f"| Unique Blocks | {summary.get('unique_blocks', 0):,} |")
        lines.append(f"| Policy | {summary.get('policy', 'lru')} |")
    timing = result.get("timing", {})
    lines.append(f"| Setup Time | {timing.get('setup_time_s', 0):.2f}s |")
    lines.append(f"| Bench Time | {timing.get('bench_time_s', 0):.2f}s |")
    lines.append("")
    return "\n".join(lines)


def _md_verdict(verdict: Dict) -> str:
    icon = _VERDICT_ICONS.get(verdict["overall"], "❓")
    lines = [
        f"## Verdict: {icon} {verdict['overall']}",
        "",
    ]
    mode_key = "p50_ttft_ms"
    if verdict.get(mode_key) is not None:
        # Only the trace mode labels this row as coming from real replay;
        # other modes report it as plain TTFT.
        label = "Real replay TTFT (P50)" if verdict.get("replay_decode_tok_s") is not None else "TTFT (P50)"
        lines.append(
            f"- **{label}:** {_fmt_ms(verdict[mode_key])} — {verdict.get('ttft_feel', 'N/A')} "
            f"({verdict.get('ttft_grade', 'N/A')})"
        )
    if verdict.get("decode_toks") is not None:
        lines.append(
            f"- **Decode throughput:** {_fmt_toks(verdict['decode_toks'])} tok/s — "
            f"{verdict.get('toks_feel', 'N/A')} ({verdict.get('toks_grade', 'N/A')})"
        )
    if verdict.get("measured_hit_rate") is not None:
        lines.append(
            f"- **Measured hit rate:** {verdict['measured_hit_rate']*100:.2f}% "
            f"(target: {verdict.get('target_hit_rate', 0)*100:.2f}%)"
        )
    if verdict.get("max_sustained_users") is not None:
        lines.append(f"- **Max sustained users:** {verdict['max_sustained_users']}")
    if verdict.get("finish_rate") is not None:
        lines.append(f"- **Task completion:** {verdict['finish_rate']*100:.0f}%")
    if verdict.get("replay_decode_tok_s") is not None:
        lines.append(
            f"- **Real replay decode:** {_fmt_toks(verdict['replay_decode_tok_s'])} tok/s"
        )
    lines.append("")
    return "\n".join(lines)


def _md_findings(findings: List[str]) -> str:
    if not findings:
        return ""
    lines = ["## Key Findings", ""]
    for f in findings:
        lines.append(f"- {f}")
    lines.append("")
    return "\n".join(lines)


def _md_summary_table(result: Dict) -> str:
    """Per-user summary table (scenario mode) or per-request (hitrate)."""
    mode = result.get("summary", {}).get("mode", "scenario")
    users = result.get("users", [])
    if not users and mode not in ("hitrate", "slo", "agent", "trace"):
        return ""

    lines = ["## Summary", ""]
    if mode == "scenario":
        lines.append("| User | In Tok | Out Tok | TTFT P50 | TPOT P50 | E2E P50 | tok/s | Comp | Succ | Fail |")
        lines.append("|------|--------|---------|----------|----------|---------|-------|------|------|------|")
        for u in users:
            a = u.get("aggregate", {})
            ttft = a.get("ttft", {}).get("P50")
            tpot = a.get("tpot", {}).get("P50")
            e2e = a.get("e2e_latency", {}).get("P50")
            thru = a.get("throughput_tok_s")
            tpot_s = f"{tpot:.2f}ms" if tpot else "N/A"
            lines.append(
                f"| {u['user_id']} | {a.get('total_input_tokens', 0):,} | "
                f"{a.get('total_output_tokens', 0):,} | {_fmt_ms(ttft)} | "
                f"{tpot_s} | {_fmt_ms(e2e)} | "
                f"{_fmt_toks(thru)} | {a.get('compaction_count', 0)} | "
                f"{a.get('success_count', 0)} | {a.get('error_count', 0)} |"
            )
    elif mode == "hitrate":
        s = result.get("summary", {})
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Requests | {s.get('num_requests', 'N/A')} |")
        lines.append(f"| Success | {s.get('success_count', 0)} |")
        lines.append(f"| Errors | {s.get('error_count', 0)} |")
        lines.append(f"| Target Hit Rate | {s.get('target_hit_rate', 0)*100:.1f}% |")
        measured = s.get("measured_hit_rate")
        lines.append(f"| Measured Hit Rate | {measured*100:.2f}%" if measured else "| Measured Hit Rate | N/A |")
        for key in ("ttft", "e2e_latency", "tpot"):
            pct = s.get(key, {})
            if pct:
                lines.append(f"| {key} P50 | {_fmt_ms(pct.get('P50'))} |")
    elif mode == "slo":
        steps = result.get("capacity_curve", [])
        lines.append("| Users | P99 TTFT | P99 TPOT | Error | SLO |")
        lines.append("|-------|----------|----------|-------|-----|")
        for step in steps:
            tpot_s = f"{step['p_tpot_ms']:.2f}ms" if step.get('p_tpot_ms') else "N/A"
            lines.append(
                f"| {step['n_users']} | {_fmt_ms(step.get('p_ttft_ms'))} | "
                f"{tpot_s} | {step.get('error_rate', 0)*100:.1f}% | "
                f"{'✅' if step.get('slo_met') else '❌'} |"
            )
    elif mode == "agent":
        tasks = result.get("tasks", [])
        lines.append("| Task | Steps | Finished | Wall(s) | In Tok | Out Tok |")
        lines.append("|------|-------|----------|---------|--------|---------|")
        for t in tasks:
            lines.append(
                f"| {t.get('task_id', -1)} | {t.get('steps', 0)} | "
                f"{'yes' if t.get('finished') else 'no'} | "
                f"{t.get('total_wall_s', 0):.2f} | "
                f"{t.get('total_input_tokens', 0):,} | "
                f"{t.get('total_output_tokens', 0):,} |"
            )
    elif mode == "trace":
        s = result.get("summary", {})
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Requests | {s.get('request_count', 0):,} |")
        lines.append(f"| Total Input Tokens | {s.get('total_input_tokens', 0):,} |")
        lines.append(f"| Unique Blocks | {s.get('unique_blocks', 0):,} |")
        lines.append(f"| Hit Rate | {s.get('hit_rate', 0)*100:.2f}% |")
        lines.append(f"| Ceiling | {s.get('ceiling', 0)*100:.2f}% |")
        lines.append(f"| Speedup | {s.get('speedup', 1):.2f}x |")
        lines.append(f"| Hit Tokens | {s.get('hit_tokens', 0):,} |")
        lines.append(f"| Miss Tokens | {s.get('miss_tokens', 0):,} |")
        if s.get("evictions"):
            lines.append(f"| Evictions | {s['evictions']:,} |")
        if s.get("budget_sweep"):
            lines.append("")
            lines.append("### Budget Sweep")
            lines.append("")
            lines.append("| Budget (tokens) | Hit Rate | Speedup | Evictions |")
            lines.append("|-----------------|----------|---------|-----------|")
            for lv in s["budget_sweep"]:
                lines.append(
                    f"| {lv['budget_tokens']:,} | {lv['hit_rate']*100:.2f}% | "
                    f"{lv['speedup']:.2f}x | {lv.get('evictions', 0):,} |"
                )
        # Real-request replay section (if the trace was played against an endpoint).
        rp = s.get("replay")
        if rp:
            lines.append("")
            lines.append("### Real Replay (measured)")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(f"| Requests | {rp.get('success_count', 0)} ok / "
                         f"{rp.get('success_count', 0) + rp.get('error_count', 0)} total |")
            lines.append(f"| Total Input Tokens | {rp.get('total_input_tokens', 0):,} |")
            lines.append(f"| Total Output Tokens | {rp.get('total_output_tokens', 0):,} |")
            for key, label in (
                ("ttft_p50_ms", "TTFT P50"),
                ("ttft_p95_ms", "TTFT P95"),
                ("ttft_p99_ms", "TTFT P99"),
                ("e2e_p50_ms", "E2E P50"),
                ("decode_tok_s", "Decode tok/s"),
                ("itl_p50_ms", "ITL P50"),
                ("itl_p95_ms", "ITL P95"),
            ):
                if rp.get(key) is not None:
                    unit = "ms" if key.endswith("_ms") else "tok/s" if "tok_s" in key else "ms"
                    lines.append(f"| {label} | {rp[key]:.2f} {unit} |")
    lines.append("")
    return "\n".join(lines)


def _md_ascii_chart(result: Dict) -> str:
    """ASCII bar chart for TTFT scaling (scenario mode with multiple users)."""
    mode = result.get("summary", {}).get("mode", "scenario")
    if mode != "scenario":
        return ""

    users = result.get("users", [])
    if len(users) < 2:
        return ""

    lines = ["## TTFT Scaling (P50)", "", "```"]
    ttft_vals = [u.get("aggregate", {}).get("ttft", {}).get("P50", 0) or 0 for u in users]
    max_ttft = max(ttft_vals) if ttft_vals else 1
    for i, u in enumerate(users):
        v = ttft_vals[i]
        bar = _bar(v, max_ttft, width=30)
        label = u.get("user_id", 0) + 1  # 1-based user count
        lines.append(f"  {label:2d} user(s) | {bar} {_fmt_ms(v)}")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _md_concurrency_efficiency(result: Dict) -> str:
    """Concurrency scaling efficiency table (scenario mode)."""
    mode = result.get("summary", {}).get("mode", "scenario")
    if mode != "scenario":
        return ""

    users = result.get("users", [])
    if len(users) < 2:
        return ""

    lines = ["## Concurrency Scaling", "", "| Users | Total tok/s | Per-user tok/s | Efficiency |", "|-------|------------|----------------|------------|"]
    thru_vals = [u.get("aggregate", {}).get("throughput_tok_s", 0) or 0 for u in users]
    base = thru_vals[0] if thru_vals else 0
    for i, u in enumerate(users):
        n = u["user_id"] + 1
        per = thru_vals[i]
        total = per * n
        eff = (per / base * 100) if base else 0
        lines.append(f"| {n} | {total:.1f} | {per:.1f} | {eff:.0f}% |")
    lines.append("")
    return "\n".join(lines)


def _md_methodology() -> str:
    return (
        "## Methodology\n\n"
        "<details>\n<summary>Click to expand</summary>\n\n"
        "- **TTFT** (Time to First Token): wall time from request send to first "
        "content chunk on the wire.\n"
        "- **TPOT** (Time Per Output Token): decode time / output tokens, excluding prefill.\n"
        "- **ITL** (Inter-Token Latency): gap between consecutive output chunks.\n"
        "- **Prefix cache hit rate**: token-level, read from the backend's Prometheus "
        "counters (start/end delta). Not request-level.\n"
        "- **Verdict thresholds**: TTFT GOOD ≤3s / OK ≤10s; throughput GOOD ≥30 tok/s / "
        "OK ≥15 tok/s.\n"
        "- **Compaction**: when context exceeds ``max_context_tokens``, history is "
        "cleared and the user prefix is incremented.\n"
        "- **Decode throughput** isolates generation speed from prefill (excludes TTFT).\n"
        "- **Wall-clock per-user throughput** uses real start/end timestamps, not "
        "summed per-request latencies.\n\n"
        "</details>\n"
    )


def generate_report(result: Dict, output_path: Optional[str] = None) -> str:
    """Generate a full Markdown report from a result dict.

    If ``output_path`` is given, also writes the markdown to that file.
    Returns the markdown string.
    """
    verdict = compute_verdict(result)
    findings = _key_findings(result, verdict)

    sections = [
        _md_header(result),
        _md_verdict(verdict),
        _md_findings(findings),
        _md_summary_table(result),
        _md_ascii_chart(result),
        _md_concurrency_efficiency(result),
        _md_methodology(),
    ]
    md = "\n".join(s for s in sections if s)

    if output_path:
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md)

    return md


def generate_comparison(result_a: Dict, result_b: Dict, label_a: str = "A",
                        label_b: str = "B", output_path: Optional[str] = None) -> str:
    """Generate a side-by-side comparison Markdown report."""
    va = compute_verdict(result_a)
    vb = compute_verdict(result_b)

    lines = [
        "# ClawPerf Comparison Report",
        "",
        f"**{label_a}** vs **{label_b}**",
        "",
        "| Metric | " + label_a + " | " + label_b + " | Delta |",
        "|--------|-------|-------|-------|",
    ]

    def _row(label, a, b, fmt="{}", pct=True):
        if a is None or b is None:
            return f"| {label} | {a if a is not None else 'N/A'} | {b if b is not None else 'N/A'} | — |"
        delta = b - a
        sign = "+" if delta >= 0 else ""
        if pct and a != 0:
            pct_str = f" ({sign}{delta / a * 100:.1f}%)"
        else:
            pct_str = ""
        return f"| {label} | {fmt.format(a)} | {fmt.format(b)} | {sign}{fmt.format(delta)}{pct_str} |"

    # TTFT (lower is better — negative delta = improvement)
    ta = va.get("p50_ttft_ms")
    tb = vb.get("p50_ttft_ms")
    if ta is not None and tb is not None:
        lines.append(_row("P50 TTFT (ms)", ta, tb, "{:.1f}"))
    else:
        lines.append(f"| P50 TTFT | {_fmt_ms(ta)} | {_fmt_ms(tb)} | — |")

    # Throughput (higher is better). Fall back to the trace-mode real-replay
    # decode rate when the verdict exposes it under replay_decode_tok_s.
    da = va.get("decode_toks")
    if da is None:
        da = va.get("replay_decode_tok_s")
    db = vb.get("decode_toks")
    if db is None:
        db = vb.get("replay_decode_tok_s")
    if da is not None and db is not None:
        lines.append(_row("Decode tok/s", da, db, "{:.1f}"))
    else:
        lines.append(f"| Decode tok/s | {_fmt_toks(da)} | {_fmt_toks(db)} | — |")

    # Hit rate (if applicable)
    ha = va.get("measured_hit_rate")
    hb = vb.get("measured_hit_rate")
    ha_s = f"{ha*100:.1f}%" if ha is not None else "N/A"
    hb_s = f"{hb*100:.1f}%" if hb is not None else "N/A"
    lines.append(f"| Hit Rate | {ha_s} | {hb_s} | — |")

    # Verdict
    lines.append(f"| Verdict | {_VERDICT_ICONS.get(va['overall'], '?')} {va['overall']} | "
                 f"{_VERDICT_ICONS.get(vb['overall'], '?')} {vb['overall']} | — |")

    # Bench time
    ba = result_a.get("timing", {}).get("bench_time_s", 0)
    bb = result_b.get("timing", {}).get("bench_time_s", 0)
    lines.append(_row("Bench Time (s)", ba, bb, "{:.2f}"))

    # Total output tokens — falls back to the replay/aggregate totals since the
    # field lives in mode-specific places (summary, replay, user aggregates).
    def _output_tokens(result: Dict) -> int:
        s = result.get("summary", {})
        if s.get("total_output_tokens"):
            return s["total_output_tokens"]
        replay = s.get("replay") or {}
        if replay.get("total_output_tokens"):
            return replay["total_output_tokens"]
        users = result.get("users", [])
        return sum(u.get("aggregate", {}).get("total_output_tokens", 0) or 0 for u in users)

    oa = _output_tokens(result_a)
    ob = _output_tokens(result_b)
    lines.append(_row("Total Output Tok", oa, ob, "{:,}"))

    lines.append("")

    # ASCII bar chart
    lines.append("## TTFT Comparison")
    lines.append("```")
    max_val = max(ta or 0, tb or 0, 1)
    bar_a = _bar(ta or 0, max_val, width=25, fill="█")
    bar_b = _bar(tb or 0, max_val, width=25, fill="█")
    lines.append(f"  {label_a:8s} | {bar_a} {_fmt_ms(ta)}")
    lines.append(f"  {label_b:8s} | {bar_b} {_fmt_ms(tb)}")
    lines.append("```")
    lines.append("")

    md = "\n".join(lines)

    if output_path:
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md)

    return md


def load_result(path: str) -> Dict:
    """Load a ClawPerf result JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
