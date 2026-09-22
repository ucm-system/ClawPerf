#!/usr/bin/env python3
"""Generate the GitHub Pages parameter/mode reference from the code.

Why generated: a hand-written option table rots the moment someone adds a flag.
Everything about the *parameters* (names, defaults, choices, help text) is read
straight out of ``clawperf.cli.build_parser()``, so ``--help`` and the website
can never disagree. Chinese descriptions live in ``docs/i18n/params_zh.json``
(keyed by argparse ``dest``) and fall back to the English help when missing.

The curated prose (mode walkthroughs, examples, SLO syntax, exit codes) is
written here, bilingual, and interleaved with the generated tables.

Usage:
  python scripts/gen_reference.py            # write docs/reference.html
  python scripts/gen_reference.py --check    # fail if the file is out of date
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from clawperf.cli import build_parser  # noqa: E402
from clawperf.context_profiles import (  # noqa: E402
    CONTEXT_PROFILES,
    PROFILE_ORDER,
    REALISTIC_PROFILES,
    SUITES,
)

DOCS = ROOT / "docs"
OUT = DOCS / "reference.html"
I18N = DOCS / "i18n" / "params_zh.json"
REPO = "https://github.com/ucm-system/ClawPerf"

# Groups that hold only per-mode tuning knobs: rendered under the mode they
# belong to, in the order the mode walkthrough appears on the page.
GROUP_TITLES_ZH = {
    "Mode": "模式选择",
    "Context Profiles & Suites": "上下文档位与套件",
    "Hit-Rate Mode (only with --mode hitrate)": "hitrate 模式参数",
    "SLO Mode (only with --mode slo)": "slo 模式参数",
    "Agent Mode (only with --mode agent)": "agent 模式参数",
    "Record Mode (only with --mode record)": "record 模式参数",
    "Replay Mode (only with --mode replay)": "replay 模式参数",
    "Trace Mode (only with --mode trace)": "trace 模式参数",
    "User Configuration": "并发用户",
    "Context Configuration": "上下文构造",
    "Run Configuration": "运行节奏",
    "API Configuration": "API 与可靠性",
    "System Metrics": "系统指标采集",
    "Output": "输出",
    "Configuration Files": "配置文件",
}

GROUP_BLURB = {
    "Mode": ("Pick the benchmark. Each mode answers a different question — see the walkthroughs above.",
             "选择基准模式。每种模式回答不同的问题，详见上文各模式介绍。"),
    "Context Profiles & Suites": ("Named context sizes and multi-scenario suites. These override the raw token counts.",
                                  "命名的上下文档位与多场景套件，会覆盖下面的原始 token 数。"),
    "Hit-Rate Mode (only with --mode hitrate)": ("Controlled prefix-cache experiment.", "受控前缀缓存实验。"),
    "SLO Mode (only with --mode slo)": ("Concurrency sweep until the SLO breaks.", "并发扫描直到 SLO 被打破。"),
    "Agent Mode (only with --mode agent)": ("Real tool-calling agent tasks.", "真实工具调用 Agent 任务。"),
    "Record Mode (only with --mode record)": ("Capture a real session through a proxy.", "通过代理录制真实会话。"),
    "Replay Mode (only with --mode replay)": ("Replay a recording against any endpoint.", "把录制内容回放到任意端点。"),
    "Trace Mode (only with --mode trace)": ("KV-cache simulation + real replay from a trace file.",
                                            "基于 trace 文件的 KV 缓存模拟 + 真实回放。"),
    "User Configuration": ("How many sessions run, and when they join.", "多少会话并发，以及它们何时加入。"),
    "Context Configuration": ("The shape of the workload: what the context is made of.",
                              "负载的形状：上下文由什么构成。"),
    "Run Configuration": ("Pacing, turn limits and failure cut-offs.", "节奏、轮数上限与失败熔断。"),
    "API Configuration": ("Where to send traffic and how to be resilient about it.",
                          "把流量发到哪里，以及如何容错。"),
    "System Metrics": ("Prometheus scraping for cache/throughput ground truth.",
                       "抓取 Prometheus 指标，获得缓存/吞吐的真值。"),
    "Output": ("Artifacts and logging.", "产物与日志。"),
    "Configuration Files": ("Layered configuration (CLI > env > YAML > defaults).",
                            "分层配置（CLI > 环境变量 > YAML > 默认值）。"),
}

MODE_ORDER = ["scenario", "hitrate", "slo", "agent", "trace", "record", "replay"]

MODE_GROUP = {
    "hitrate": "Hit-Rate Mode (only with --mode hitrate)",
    "slo": "SLO Mode (only with --mode slo)",
    "agent": "Agent Mode (only with --mode agent)",
    "record": "Record Mode (only with --mode record)",
    "replay": "Replay Mode (only with --mode replay)",
    "trace": "Trace Mode (only with --mode trace)",
}


def e(text: str) -> str:
    return html.escape(str(text), quote=False)


def en(s: str) -> str:
    return f'<span class="en">{s}</span>'


def zh(s: str) -> str:
    return f'<span class="zh">{s}</span>'


def both(en_text: str, zh_text: str) -> str:
    return en(en_text) + zh(zh_text)


def code(text: str, cls: str = "inline") -> str:
    return f'<code class="{cls}">{e(text)}</code>'


# ── Option introspection ─────────────────────────────────────────────────────

def _help_text(action) -> str:
    """Raw help string, with argparse's ``%%`` escaping undone.

    argparse runs help strings through ``%``-formatting, so a literal percent
    sign has to be written ``%%`` in the source (and renders as ``%`` in
    ``--help``). We read ``action.help`` directly, so undo it here.
    """
    return (action.help or "").strip().replace("%%", "%")


def collect_groups() -> list[tuple[str, list[dict]]]:
    """Return [(group title, [option rows])] straight from argparse."""
    parser = build_parser()
    groups: list[tuple[str, list[dict]]] = []
    for group in parser._action_groups:
        actions = [a for a in group._group_actions if a.option_strings]
        if not actions or group.title == "options":  # skip -h/--help
            continue
        by_dest: dict = {}
        order: list = []
        for action in actions:
            if action.dest not in by_dest:
                by_dest[action.dest] = {"dest": action.dest, "opts": [], "helps": [],
                                        "default": action.default, "choices": action.choices,
                                        "metavar": action.metavar, "actions": []}
                order.append(action.dest)
            row = by_dest[action.dest]
            row["opts"].extend(action.option_strings)
            if _help_text(action):
                row["helps"].append(_help_text(action))
            row["actions"].append(type(action).__name__)
            if action.metavar:
                row["metavar"] = action.metavar
            if action.choices:
                row["choices"] = action.choices
        rows = []
        for dest in order:
            row = by_dest[dest]
            row["helps"] = list(dict.fromkeys(row["helps"]))
            row["help"] = " ".join(row["helps"])
            rows.append(row)
        groups.append((group.title, rows))
    return groups


def default_text(row: dict) -> str:
    value = row["default"]
    # The declared default wins: several flags are store_true with default=True
    # (paired with a --no-... counterpart), so the action type alone would lie.
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None or value == "":
        acts = set(row["actions"])
        if "_StoreTrueAction" in acts:
            return "off"
        if "_StoreFalseAction" in acts:
            return "on"
        return "—"  # not set unless the user passes it
    return str(value)


def option_text(row: dict) -> str:
    parts = []
    for opt in row["opts"]:
        takes_value = "_StoreTrueAction" not in row["actions"] and "_StoreFalseAction" not in row["actions"]
        if takes_value:
            metavar = row["metavar"] or row["dest"].upper()
            parts.append(f"{opt} &lt;{e(metavar)}&gt;")
        else:
            parts.append(opt)
    return "<br>".join(f'<code class="opt">{p}</code>' for p in parts)


def choices_text(row: dict) -> str:
    if not row["choices"]:
        return ""
    vals = ", ".join(code(str(c), "inline") for c in row["choices"])
    return f'<div class="meta">{both("choices", "可选值")}: {vals}</div>'


def render_options_table(rows: list[dict], i18n: dict) -> str:
    out = ['<div class="tbl-scroll"><table class="params">',
           '<thead><tr><th>Option</th><th>Default</th><th>Description</th></tr></thead><tbody>']
    for row in rows:
        # One escaped line per spelling: the table's option cell lists the same
        # spellings in the same order, so the mapping is unambiguous.
        helps = row["helps"] or [""]
        help_en = "<br>".join(e(h) for h in helps if h) or '<span class="muted">—</span>'
        help_zh = i18n.get(row["dest"], "")
        desc = f'<span class="en">{help_en}</span>'
        if help_zh:
            desc += f'<span class="zh">{e(help_zh)}</span>'
        out.append(
            "<tr>"
            f'<td class="opt-cell">{option_text(row)}</td>'
            f'<td class="def-cell"><code class="inline">{e(default_text(row))}</code></td>'
            f'<td>{desc}{choices_text(row)}</td>'
            "</tr>"
        )
    out.append("</tbody></table></div>")
    return "\n".join(out)


def render_group(title: str, rows: list[dict], i18n: dict, anchor: str) -> str:
    title_zh = GROUP_TITLES_ZH.get(title, title)
    blurb = GROUP_BLURB.get(title, ("", ""))
    sub = both(blurb[0], blurb[1]) if blurb[0] else ""
    return (
        f'<h3 id="{anchor}">{both(title, title_zh)}</h3>\n'
        f'<p class="sub">{sub}</p>\n'
        f"{render_options_table(rows, i18n)}"
    )


# ── Curated content ──────────────────────────────────────────────────────────

def profiles_table() -> str:
    rows = []
    for name in PROFILE_ORDER:
        p = CONTEXT_PROFILES[name]
        base = p["system_prefix_tokens"] + p["user_prefix_tokens"] + p["input_tokens_per_turn"]
        rows.append(
            "<tr>"
            f'<td><code class="inline">{name}</code></td>'
            f'<td class="num">{p["system_prefix_tokens"]:,}</td>'
            f'<td class="num">{p["user_prefix_tokens"]:,}</td>'
            f'<td class="num">{p["input_tokens_per_turn"]:,}</td>'
            f'<td class="num"><b>{base:,}</b></td>'
            f'<td class="num">~{round(base / 1000)}K</td>'
            "</tr>"
        )
    return (
        '<div class="tbl-scroll"><table>'
        "<thead><tr>"
        f'<th>{both("Profile", "档位")}</th>'
        f'<th>{both("system prefix", "系统前缀")}</th>'
        f'<th>{both("user prefix", "用户前缀")}</th>'
        f'<th>{both("input / turn", "每轮输入")}</th>'
        f'<th>{both("base context", "基础上下文")}</th>'
        f'<th>{both("rounded", "约")}</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def suites_table() -> str:
    rows = []
    for name, suite in SUITES.items():
        profiles = suite["profiles"]
        if profiles == "realistic":
            shown = f'<code class="inline">{" → ".join(REALISTIC_PROFILES)}</code>'
        elif isinstance(profiles, str):
            shown = f'<code class="inline">{profiles}</code>'
        else:
            shown = " + ".join(f'<code class="inline">{p}</code>' for p in profiles)
        users = ", ".join(str(u) for u in suite["users"])
        scenarios = len(REALISTIC_PROFILES if profiles == "realistic"
                        else ([profiles] if isinstance(profiles, str) else profiles)) * len(suite["users"])
        rows.append(
            "<tr>"
            f'<td><code class="inline">{name}</code></td>'
            f'<td class="num">{users}</td>'
            f"<td>{shown}</td>"
            f'<td class="num">{suite["max_turns"]}</td>'
            f'<td class="num">{suite["output_tokens_per_turn"]}</td>'
            f'<td class="num">{scenarios}</td>'
            "</tr>"
        )
    return (
        '<div class="tbl-scroll"><table>'
        "<thead><tr>"
        f'<th>{both("Suite", "套件")}</th>'
        f'<th>{both("users", "并发用户")}</th>'
        f'<th>{both("profiles", "档位")}</th>'
        f'<th>{both("turns", "轮数")}</th>'
        f'<th>{both("out/turn", "每轮输出")}</th>'
        f'<th>{both("runs", "场景数")}</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def mode_section(key: str) -> str:
    """Curated walkthrough for one mode (bilingual)."""
    return MODE_CONTENT[key].strip()


MODE_CONTENT = {
"scenario": """
<h3 id="mode-scenario">scenario <span class="tag-pill">default</span></h3>
<p class="sub en">Multi-turn long-context workload: N users, each growing its own conversation until
compaction kicks in.</p>
<p class="sub zh">多轮长上下文负载：N 个用户各自维护不断增长的会话，直到触发压缩。</p>
<div class="grid c2">
  <div class="card">
    <p class="en"><b>Answers:</b> how does TTFT / TPOT degrade as a real conversation grows and
    several users share the server? Every turn appends to history, so the prefill grows turn by
    turn — the effect a single-shot benchmark misses.</p>
    <p class="zh"><b>回答的问题：</b>当真实会话不断增长、多个用户共享服务时，TTFT / TPOT 如何劣化？
    每轮都会把新内容追加到历史，预填充量逐轮增长 —— 这正是单次请求压测看不到的效果。</p>
  </div>
  <div class="card">
    <p class="en"><b>Use it when</b> you are validating a serving configuration for agent traffic,
    sizing concurrency, or checking that long-context decode stays within budget.</p>
    <p class="zh"><b>适用场景：</b>为 Agent 流量验证服务配置、评估可支撑并发，或检查长上下文解码是否在预算内。</p>
  </div>
</div>
<pre><code>clawperf --mode scenario \\
  --endpoint http://localhost:8000/v1 --model qwen3-32b \\
  --tokenizer /mnt/model/Qwen3-32B \\
  --context-profile medium \\
  --num-users 8 --max-turns 20 --user-arrival poisson:2 \\
  --metrics-endpoint http://localhost:8000/metrics --reset-cache \\
  --output results_scenario.json</code></pre>
<p class="note"><span class="en">Context comes from <code class="inline">--context-profile</code>
(or raw <code class="inline">--system-prefix-tokens / --user-prefix-tokens /
--input-tokens-per-turn</code>). <code class="inline">--max-context-tokens</code> must match the
model's real window, otherwise compaction triggers at the wrong time.</span>
<span class="zh">上下文由 <code class="inline">--context-profile</code>（或原始
<code class="inline">--system-prefix-tokens / --user-prefix-tokens / --input-tokens-per-turn</code>）
决定。<code class="inline">--max-context-tokens</code> 必须与模型真实窗口一致，否则压缩触发时机不对。</span></p>
<figure>
  <div class="frame shot">
    <img loading="lazy" src="shots/scenario.png" alt="clawperf scenario report from a real Ascend 910B3 run">
  </div>
  <figcaption><span class="en">A real multi-turn run on an Ascend 910B3: TTFT and decode throughput as each session's context grows.</span><span class="zh">昇腾 910B3 上的真实多轮运行：会话上下文增长时的 TTFT 与解码吞吐。</span></figcaption>
</figure>
""",

"hitrate": """
<h3 id="mode-hitrate">hitrate</h3>
<p class="sub en">Controlled prefix-cache experiment: prefill known prefixes, then measure the real
cache hit rate and the speedup it buys.</p>
<p class="sub zh">受控前缀缓存实验：先注入已知前缀，再测量真实缓存命中率及其带来的加速比。</p>
<div class="grid c2">
  <div class="card">
    <p class="en"><b>Answers:</b> is prefix caching actually working, and how much does it help?
    The measured hit rate is read from the server's own Prometheus counters
    (<code class="inline">prefix_cache_hits_total</code> / <code class="inline">queries_total</code>),
    not inferred from prompt construction.</p>
    <p class="zh"><b>回答的问题：</b>前缀缓存真的生效了吗？收益多大？命中率直接读服务端 Prometheus
    计数器（<code class="inline">prefix_cache_hits_total</code> / <code class="inline">queries_total</code>），
    不是从提示词构造推断出来的。</p>
  </div>
  <div class="card">
    <p class="en"><b>Output:</b> TARGET vs MEASURED hit rate, theoretical ceiling
    <code class="inline">1/(1-hit_rate)</code> vs actual speedup, plus a per-engine breakdown.</p>
    <p class="zh"><b>输出：</b>目标 vs 实测命中率、理论上限 <code class="inline">1/(1-hit_rate)</code>
    与实测加速比，以及逐引擎明细。</p>
  </div>
</div>
<pre><code>clawperf --mode hitrate \\
  --endpoint http://localhost:8000/v1 --model qwen3 \\
  --num-requests 200 --input-len 8192 --hit-rate 0.7 --prefix-num 4 \\
  --output-len 128 --concurrency 8 \\
  --metrics-endpoint http://localhost:8000/metrics --reset-cache \\
  --output results_hitrate.json</code></pre>
<p class="note"><span class="en"><code class="inline">--hit-rate 0.7</code> and
<code class="inline">--prefix-len 5734</code> are two ways to say the same thing (they are mutually
exclusive); <code class="inline">--prefix-num</code> controls how many <i>distinct</i> prefixes are
in play, which is what makes a multi-tenant workload realistic.</span>
<span class="zh"><code class="inline">--hit-rate 0.7</code> 与 <code class="inline">--prefix-len 5734</code>
是同一件事的两种写法（二者互斥）；<code class="inline">--prefix-num</code> 控制有多少个<b>不同</b>前缀，
这正是多租户场景真实感的来源。</span></p>
<figure>
  <div class="frame shot">
    <img loading="lazy" src="shots/hitrate.png" alt="clawperf hitrate report from a real run">
  </div>
  <figcaption><span class="en">TARGET vs MEASURED, the theoretical ceiling against the speedup actually observed, and a per-engine breakdown.</span><span class="zh">目标 vs 实测、理论上限与真实观测到的加速比，以及逐引擎明细。</span></figcaption>
</figure>
""",

"slo": """
<h3 id="mode-slo">slo</h3>
<p class="sub en">Concurrency sweep: raise the load step by step and report the largest number of users
that still meets every latency constraint.</p>
<p class="sub zh">并发扫描：逐步加压，报告仍能满足全部时延约束的最大用户数。</p>
<div class="grid c2">
  <div class="card">
    <p class="en"><b>Answers:</b> "how many concurrent users can this deployment serve at
    <code class="inline">ttft.p99 ≤ 1.5s</code>?" — the capacity number you put in a plan, with the
    binding constraint named.</p>
    <p class="zh"><b>回答的问题：</b>「在 <code class="inline">ttft.p99 ≤ 1.5s</code> 下这套部署能支撑多少并发？」
    —— 可以直接写进方案的容量数字，并指出是哪条约束先被打破。</p>
  </div>
  <div class="card">
    <p class="en"><b>Output:</b> a capacity curve (one column per constraint) plus
    <i>Max sustained users</i>. Steps that overrun <code class="inline">--slo-step-timeout-s</code>
    are reported as TIMEOUT and fail.</p>
    <p class="zh"><b>输出：</b>容量曲线（每条约束一列）与「最大可支撑用户数」。超时（
    <code class="inline">--slo-step-timeout-s</code>）的步会标记为 TIMEOUT 并判定不达标。</p>
  </div>
</div>
<pre><code><span class="c"># shell-safe: ':' means '&lt;='</span>
clawperf --mode slo \\
  --endpoint http://localhost:8000/v1 --model qwen3-32b \\
  --slo ttft.p99:1500 --slo tpot.avg:30 --slo e2e.max:30000 \\
  --slo-min-users 1 --slo-max-users 200 --slo-step-strategy geometric \\
  --slo-step-turns 5 --slo-error-rate 0.01 \\
  --output results_slo.json</code></pre>
<pre><code>| Users | ttft.p99 | tpot.avg |   e2e.max | Error | SLO |
|     1 |  228.2ms |    8.6ms |  8887.7ms |  0.0% |  ✓  |
|     4 |  624.2ms |   14.7ms | 15471.1ms |  0.0% |  ✓  |
|     6 |  945.1ms |   20.9ms | 22360.6ms |  0.0% |  ✗  |
SLO: ttft.p99&lt;=1500ms, tpot.avg&lt;=30ms, e2e.max&lt;=30000ms
Max sustained users: 5</code></pre>
<figure>
  <div class="frame shot">
    <img loading="lazy" src="shots/slo.png" alt="clawperf slo report from a real Ascend 910B3 sweep: capacity curve and max sustained users">
  </div>
  <figcaption><span class="en">A real sweep: one column per constraint and the answer — 5 users, bound by <code class="inline">e2e.max</code> rather than TTFT.</span><span class="zh">真机扫描：每条约束一列与最终答案 —— 5 个用户，瓶颈是 <code class="inline">e2e.max</code> 而非 TTFT。</span></figcaption>
</figure>
""",

"agent": """
<h3 id="mode-agent">agent</h3>
<p class="sub en">Real agent-at-work performance: the model under test actually runs coding tasks —
reading files, editing, running shell commands — through tool calls.</p>
<p class="sub zh">真实 Agent 工作负载：被测模型通过工具调用真正执行编码任务 —— 读文件、改代码、跑命令。</p>
<div class="grid c2">
  <div class="card">
    <p class="en"><b>Answers:</b> how does the server behave under the *shape* of agent traffic
    (bursty tool loops, long growing histories) rather than a synthetic prompt pattern?</p>
    <p class="zh"><b>回答的问题：</b>在 Agent 流量的<b>形态</b>下（突发的工具循环、不断增长的长历史），
    服务端表现如何？而不是合成提示词模式。</p>
  </div>
  <div class="card">
    <p class="en"><b>Needs</b> an OpenAI-compatible endpoint with tool calling enabled
    (vLLM: <code class="inline">--enable-auto-tool-choice --tool-call-parser qwen3_xml</code>).</p>
    <p class="zh"><b>依赖</b>开启工具调用的 OpenAI 兼容端点（vLLM：
    <code class="inline">--enable-auto-tool-choice --tool-call-parser qwen3_xml</code>）。</p>
  </div>
</div>
<pre><code>clawperf --mode agent \\
  --endpoint http://localhost:8000/v1 --model qwen3-32b \\
  --agent-tasks 8 --agent-max-steps 12 --agent-max-tokens 512 \\
  --agent-shell-timeout 30 \\
  --output results_agent.json</code></pre>
<figure>
  <div class="frame shot">
    <img loading="lazy" src="shots/agent.png" alt="clawperf agent report from a real run">
  </div>
  <figcaption><span class="en">A real agent run: completion rate, steps and tokens per task, and the latency verdict.</span><span class="zh">真机 agent 运行：任务完成率、每个任务的步数与 token，以及时延结论。</span></figcaption>
</figure>
""",

"trace": """
<h3 id="mode-trace">trace</h3>
<p class="sub en">KV-cache analysis from a production trace, plus optional real replay of the trace's
requests against your endpoint.</p>
<p class="sub zh">基于生产 trace 的 KV 缓存分析，并可选择把 trace 中的请求真实回放到你的端点。</p>
<div class="grid c2">
  <div class="card">
    <p class="en"><b>Two halves.</b> (1) <i>Simulation</i>: replay the trace's block hashes through a
    simulated LRU/FIFO cache to get hit rate, evictions and the hit-rate-vs-budget curve —
    no endpoint needed. (2) <i>Real replay</i>: if the trace carries messages, send them to
    <code class="inline">--endpoint</code> to measure TTFT/TPOT for that exact workload.</p>
    <p class="zh"><b>两半功能。</b>（1）<i>模拟</i>：把 trace 的 block hash 送进模拟的 LRU/FIFO 缓存，
    得到命中率、驱逐次数与「命中率-预算」曲线 —— 不需要端点。（2）<i>真实回放</i>：若 trace 带 messages，
    则把它们发到 <code class="inline">--endpoint</code>，测出该真实负载下的 TTFT/TPOT。</p>
  </div>
  <div class="card">
    <p class="en"><b>Budget.</b> <code class="inline">--cache-budget-tokens</code> or
    <code class="inline">--cache-budget-gb</code> (+<code class="inline">--kv-bytes-per-token</code>);
    <code class="inline">--budget-sweep</code> scans levels to find where returns flatten.</p>
    <p class="zh"><b>预算。</b><code class="inline">--cache-budget-tokens</code> 或
    <code class="inline">--cache-budget-gb</code>（配合 <code class="inline">--kv-bytes-per-token</code>）；
    <code class="inline">--budget-sweep</code> 扫描多个预算档位，找出收益拐点。</p>
  </div>
</div>
<pre><code><span class="c"># simulation only</span>
clawperf --mode trace --trace-file trace.jsonl.gz --budget-sweep --eviction-policy lru

<span class="c"># simulation + real replay (clamped to the model window)</span>
clawperf --mode trace --trace-file trace.jsonl.gz \\
  --endpoint http://localhost:8000/v1 --model qwen3 --tokenizer /mnt/model/Qwen3-32B \\
  --cache-budget-gb 40 --kv-bytes-per-token 2.0 --model-context-length 32768 \\
  --trace-users 4 --output results_trace.json</code></pre>
<figure>
  <div class="frame shot">
    <img loading="lazy" src="shots/trace.png" alt="clawperf trace report: hit rate versus cache budget">
  </div>
  <figcaption><span class="en">Hit rate against cache budget over a real trace — where more cache stops buying anything.</span><span class="zh">真实 trace 下命中率随缓存容量的变化 —— 加到多少就不再划算。</span></figcaption>
</figure>
""",

"record": """
<h3 id="mode-record">record</h3>
<p class="sub en">A recording proxy: point a real agent (Claude Code, any OpenAI/Anthropic client) at
it, work normally, and every request/response is written to JSONL.</p>
<p class="sub zh">录制代理：把真实 Agent（Claude Code 或任意 OpenAI/Anthropic 客户端）指向它，正常工作，
所有请求/响应写入 JSONL。</p>
<pre><code>clawperf --mode record --proxy-port 9090 \\
  --upstream-endpoint https://api.deepseek.com/v1 --upstream-api openai \\
  --recording session.jsonl
<span class="c"># then point your agent at http://localhost:9090/v1</span></code></pre>
<p class="note"><span class="en">Anthropic clients are accepted too
(<code class="inline">/v1/messages</code>) and translated to OpenAI on the fly. The file is appended
across restarts, and you are told how many prior entries were kept.</span>
<span class="zh">也接受 Anthropic 客户端（<code class="inline">/v1/messages</code>），并实时翻译为 OpenAI 协议。
文件跨重启追加，并会提示保留了多少条历史记录。</span></p>
""",

"replay": """
<h3 id="mode-replay">replay</h3>
<p class="sub en">Replay a recording against any endpoint, preserving multi-turn history.</p>
<p class="sub zh">把录制内容回放到任意端点，并保持多轮历史。</p>
<div class="grid c2">
  <div class="card">
    <p class="en"><b><code class="inline">--history-mode live</code></b> (default, recommended):
    the server's actual response becomes the next turn's history, so the KV-cache prefix lines up
    with what really happened.</p>
    <p class="zh"><b><code class="inline">--history-mode live</code></b>（默认，推荐）：把服务端真实返回
    作为下一轮历史，使 KV 缓存前缀与真实情况对齐。</p>
  </div>
  <div class="card">
    <p class="en"><b><code class="inline">verbatim</code></b>: send each recorded entry's messages
    exactly as recorded — useful for A/B comparing two servers on identical input.</p>
    <p class="zh"><b><code class="inline">verbatim</code></b>：原样发送每条录制记录的 messages ——
    适合在两个服务端之间做同输入的 A/B 对比。</p>
  </div>
</div>
<pre><code>clawperf --mode replay --recording session.jsonl \\
  --endpoint http://localhost:8000/v1 --model qwen3-32b \\
  --history-mode live --concurrency 4 --output results_replay.json</code></pre>
<figure>
  <div class="frame shot">
    <img loading="lazy" src="shots/replay.png" alt="clawperf replay report from a recorded session">
  </div>
  <figcaption><span class="en">A recorded session replayed with live history: the same latency statistics as any other mode, plus a verdict.</span><span class="zh">按 live 历史回放的录制会话：与其他模式一致的时延统计与结论。</span></figcaption>
</figure>
""",
}


def build_html() -> str:
    i18n = json.loads(I18N.read_text(encoding="utf-8")) if I18N.is_file() else {}
    groups = collect_groups()
    by_title = {title: rows for title, rows in groups}
    toc = [
        ("modes", "Modes", "模式"),
        ("profiles", "Context profiles & suites", "上下文档位与套件"),
        ("pacing", "Pacing & concurrency", "节奏与并发"),
        ("metrics", "Metrics & PD disaggregation", "指标与 PD 分离"),
        ("slo-syntax", "SLO constraint syntax", "SLO 约束语法"),
        ("params", "All parameters", "全部参数"),
        ("env", "Env vars & config file", "环境变量与配置文件"),
        ("exit", "Output & exit codes", "产物与退出码"),
        ("trouble", "Troubleshooting", "故障排查"),
    ]
    toc_html = "".join(
        f'<a href="#{i}">{both(en_t, zh_t)}</a>' for i, en_t, zh_t in toc
    )

    mode_html = "\n".join(mode_section(k) for k in MODE_ORDER)

    # ── parameter groups ──
    global_groups = ["Mode", "Context Profiles & Suites", "User Configuration",
                     "Context Configuration", "Run Configuration", "API Configuration",
                     "System Metrics", "Output", "Configuration Files"]
    parts = []
    for title in global_groups:
        if title in by_title:
            anchor = "opt-" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            parts.append(render_group(title, by_title[title], i18n, anchor))
    for mode in MODE_ORDER:
        gtitle = MODE_GROUP.get(mode)
        if gtitle and gtitle in by_title:
            anchor = f"opt-{mode}"
            parts.append(
                f'<h4 id="{anchor}" class="mode-params">'
                + both(f"{mode} mode options", f"{mode} 模式参数")
                + "</h4>"
            )
            parts.append(render_options_table(by_title[gtitle], i18n))
    params_html = "\n".join(parts)

    total_opts = sum(len(rows) for _, rows in groups)
    total_flags = sum(len(r["opts"]) for _, rows in groups for r in rows)

    rendered = fill_template(TEMPLATE)
    return rendered.format(
        toc=toc_html,
        modes=mode_html,
        profiles=profiles_table(),
        suites=suites_table(),
        params=params_html,
        total_opts=total_opts,
        total_flags=total_flags,
        repo=REPO,
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ClawPerf — Reference: modes, context profiles and every parameter</title>
<meta name="description" content="Complete ClawPerf reference: all seven modes with examples, context profiles (fresh/short/medium/long/full/xl/xxl) and suites, SLO constraint syntax, and every CLI parameter with its default.">
<link rel="canonical" href="https://ucm-system.github.io/ClawPerf/reference.html">
<meta property="og:type" content="website">
<meta property="og:title" content="ClawPerf — Reference: modes, context profiles and every parameter">
<meta property="og:description" content="All seven modes with worked examples, the seven context profiles, the four suites, SLO syntax and all {total_opts} documented parameters.">
<meta property="og:url" content="https://ucm-system.github.io/ClawPerf/reference.html">
<meta name="theme-color" content="#0f172a">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%230f172a'/%3E%3Cg fill='%2338bdf8'%3E%3Crect x='7' y='17' width='4' height='8' rx='1'/%3E%3Crect x='14' y='12' width='4' height='13' rx='1'/%3E%3Crect x='21' y='7' width='4' height='18' rx='1'/%3E%3C/g%3E%3C/svg%3E">
<style>
  :root {{
    --bg: #ffffff; --bg-soft: #f8fafc; --card: #ffffff; --border: #e2e8f0;
    --text: #0f172a; --text-soft: #475569; --text-muted: #64748b;
    --accent: #0284c7; --accent-soft: #e0f2fe; --green: #15803d; --green-soft: #dcfce7;
    --amber: #b45309; --amber-soft: #fef3c7; --code-bg: #0f172a; --code-text: #e2e8f0;
    --shadow: 0 1px 2px rgba(15, 23, 42, .06), 0 8px 24px rgba(15, 23, 42, .06);
  }}
  html[data-theme="dark"] {{
    --bg: #0b1220; --bg-soft: #0f172a; --card: #111c33; --border: #1e293b;
    --text: #e8eef8; --text-soft: #b6c2d4; --text-muted: #8b9ab1;
    --accent: #38bdf8; --accent-soft: #0b2942; --green: #4ade80; --green-soft: #0d2a1c;
    --amber: #fbbf24; --amber-soft: #33260a; --code-bg: #060b16; --code-text: #dbe6f5;
    --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 10px 30px rgba(0, 0, 0, .35);
  }}
  @media (prefers-color-scheme: dark) {{
    html[data-theme="auto"] {{
      --bg: #0b1220; --bg-soft: #0f172a; --card: #111c33; --border: #1e293b;
      --text: #e8eef8; --text-soft: #b6c2d4; --text-muted: #8b9ab1;
      --accent: #38bdf8; --accent-soft: #0b2942; --green: #4ade80; --green-soft: #0d2a1c;
      --amber: #fbbf24; --amber-soft: #33260a; --code-bg: #060b16; --code-text: #dbe6f5;
      --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 10px 30px rgba(0, 0, 0, .35);
    }}
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; scroll-padding-top: 80px; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', -apple-system,
                 BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    line-height: 1.65; -webkit-font-smoothing: antialiased;
  }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 0 20px; }}
  html[data-lang="en"] .zh {{ display: none; }}
  html[data-lang="zh"] .en {{ display: none; }}
  html[data-lang="zh"] body {{ line-height: 1.8; }}

  header.top {{
    position: sticky; top: 0; z-index: 20; background: var(--bg);
    background: color-mix(in srgb, var(--bg) 88%, transparent);
    backdrop-filter: blur(8px); border-bottom: 1px solid var(--border);
  }}
  .top-inner {{ display: flex; align-items: center; gap: 16px; padding: 12px 0; }}
  .brand {{ display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 17px; color: var(--text); }}
  .brand:hover {{ text-decoration: none; }}
  nav.links {{ display: flex; gap: 18px; margin-left: auto; flex-wrap: wrap; }}
  nav.links a {{ color: var(--text-soft); font-size: 14px; }}
  nav.links a.here {{ color: var(--accent); font-weight: 600; }}
  .toggles {{ display: flex; gap: 8px; }}
  button.toggle {{
    font: inherit; font-size: 13px; color: var(--text-soft); background: var(--bg-soft);
    border: 1px solid var(--border); border-radius: 8px; padding: 5px 10px; cursor: pointer;
  }}
  button.toggle:hover {{ border-color: var(--accent); color: var(--accent); }}

  .hero {{ padding: 44px 0 8px; }}
  .hero h1 {{ font-size: clamp(26px, 4vw, 38px); line-height: 1.2; margin: 0 0 10px; letter-spacing: -.02em; }}
  .hero p {{ color: var(--text-soft); max-width: 780px; margin: 0 0 18px; }}
  .toc {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 8px; }}
  .toc a {{
    font-size: 13px; color: var(--text-soft); border: 1px solid var(--border);
    background: var(--bg-soft); border-radius: 999px; padding: 4px 12px;
  }}
  .toc a:hover {{ border-color: var(--accent); color: var(--accent); text-decoration: none; }}

  section {{ padding: 34px 0; border-top: 1px solid var(--border); }}
  section > .wrap > h2 {{ font-size: clamp(26px, 3.4vw, 34px); line-height: 1.2; margin: 0 0 8px; letter-spacing: -.02em; }}
  h3 {{ font-size: 22px; margin: 30px 0 8px; letter-spacing: -.01em; }}
  h3:first-child {{ margin-top: 0; }}
  h4.mode-params {{ font-size: 16px; margin: 26px 0 4px; color: var(--text-soft); }}
  p.sub {{ color: var(--text-muted); margin: 0 0 14px; max-width: 820px; }}
  p.note {{ font-size: 14px; color: var(--text-soft); background: var(--bg-soft);
            border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }}
  .tag-pill {{ font-size: 12px; color: var(--accent); background: var(--accent-soft);
               border-radius: 999px; padding: 2px 10px; vertical-align: middle; }}
  .muted {{ color: var(--text-muted); }}

  .grid {{ display: grid; gap: 16px; }}
  .grid.c2 {{ grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px;
           padding: 16px 18px; box-shadow: var(--shadow); }}
  .card p {{ margin: 0 0 8px; color: var(--text-soft); font-size: 14.5px; }}
  .card p:last-child {{ margin-bottom: 0; }}

  table {{ width: 100%; border-collapse: collapse; font-size: 14.5px; }}
  th, td {{ text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }}
  th {{ color: var(--text-muted); font-weight: 600; font-size: 12.5px; text-transform: uppercase; letter-spacing: .04em; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  .tbl-scroll {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 14px;
                 background: var(--card); box-shadow: var(--shadow); margin-bottom: 8px; }}
  table.params td.opt-cell {{ white-space: nowrap; }}
  table.params td.def-cell {{ white-space: nowrap; color: var(--text-muted); }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  code, kbd {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 13px; }}
  code.inline {{ background: var(--bg-soft); border: 1px solid var(--border); border-radius: 6px; padding: 1px 6px; }}
  code.opt {{ color: var(--text); font-weight: 600; }}
  .meta {{ font-size: 12.5px; color: var(--text-muted); margin-top: 4px; }}
  pre {{
    margin: 0 0 12px; background: var(--code-bg); color: var(--code-text); border-radius: 14px;
    padding: 16px 18px; overflow-x: auto; font-size: 13px; line-height: 1.6; border: 1px solid var(--border);
  }}
  pre code {{ color: inherit; }}
  pre .c {{ color: #7dd3fc; }}
  pre .m {{ color: #86efac; }}
  figure {{ margin: 20px 0 0; }}
  figure .frame {{
    background: #0b1220; border: 1px solid var(--border); border-radius: 14px; padding: 0;
    overflow: auto; max-height: 620px;
  }}
  figure img {{ display: block; width: auto; max-width: 100%; height: auto; margin: 0 auto; }}
  figcaption {{ color: var(--text-muted); font-size: 13px; margin: 10px 0 18px; text-align: center; }}
  footer {{ border-top: 1px solid var(--border); padding: 28px 0 48px; color: var(--text-muted); font-size: 14px; }}
  @media (max-width: 720px) {{ nav.links {{ display: none; }} }}
</style>
</head>
<body>

<header class="top">
  <div class="wrap top-inner">
    <a class="brand" href="index.html">
      <svg width="24" height="24" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="7" fill="#0f172a"/>
        <g fill="#38bdf8">
          <rect x="7" y="17" width="4" height="8" rx="1"/>
          <rect x="14" y="12" width="4" height="13" rx="1"/>
          <rect x="21" y="7" width="4" height="18" rx="1"/>
        </g>
      </svg>
      ClawPerf
    </a>
    <nav class="links">
      <a href="index.html">{modes_nav}</a>
      <a href="index.html#results">{results_nav}</a>
      <a href="index.html#start">{start_nav}</a>
      <a href="reference.html" class="here">{ref_nav}</a>
      <a href="https://github.com/ucm-system/ClawPerf">GitHub</a>
    </nav>
    <div class="toggles">
      <button class="toggle" id="lang-btn" type="button" aria-label="Switch language">中文</button>
      <button class="toggle" id="theme-btn" type="button" aria-label="Switch theme">◐</button>
    </div>
  </div>
</header>

<div class="hero wrap">
  <h1>{title}</h1>
  <p>{lead}</p>
  <div class="toc">{toc}</div>
</div>

<section id="modes">
  <div class="wrap">
    <h2>{modes_h}</h2>
    <p class="sub">{modes_sub}</p>
    {modes}
  </div>
</section>

<section id="profiles">
  <div class="wrap">
    <h2>{profiles_h}</h2>
    <p class="sub">{profiles_sub}</p>
    {profiles}
    <h3>{profiles_which_h}</h3>
    <div class="grid c2">
      <div class="card">
        <p class="en"><b>Start here.</b> <code class="inline">fresh</code> for a smoke test,
        <code class="inline">medium</code> for a typical coding session, <code class="inline">long</code>
        / <code class="inline">full</code> for the tail of real sessions. <code class="inline">xl</code>
        and <code class="inline">xxl</code> are prefill stress tests — a single request can dominate the
        step, so use them on purpose.</p>
        <p class="zh"><b>怎么选。</b>冒烟测试用 <code class="inline">fresh</code>；典型编码会话用
        <code class="inline">medium</code>；真实会话尾部用 <code class="inline">long</code> /
        <code class="inline">full</code>。<code class="inline">xl</code> 与 <code class="inline">xxl</code>
        属于预填充压力测试 —— 单个请求就可能主导整个步，请按需使用。</p>
      </div>
      <div class="card">
        <p class="en"><b>One profile per run.</b> <code class="inline">--context-profile</code> sets a
        single size; to sweep sizes use <code class="inline">--suite</code>, which runs the
        (users × profiles) cross-product in sequence. <code class="inline">--model-context-length</code>
        skips any profile that cannot fit the model's window.</p>
        <p class="zh"><b>一次一个档位。</b><code class="inline">--context-profile</code> 只设一个档位；
        想扫描多个档位请用 <code class="inline">--suite</code>，它会按序跑完（用户 × 档位）的笛卡尔积。
        <code class="inline">--model-context-length</code> 会跳过放不进模型窗口的档位。</p>
      </div>
    </div>
    <pre><code><span class="c"># one profile</span>
clawperf --mode scenario --context-profile medium --num-users 8 ...

<span class="c"># sweep profiles × users</span>
clawperf --mode scenario --suite full --model-context-length 32768 ...

<span class="c"># raw token counts instead of a named profile</span>
clawperf --mode scenario --system-prefix-tokens 28000 \\
  --user-prefix-tokens 10000 --input-tokens-per-turn 5000 --output-tokens-per-turn 1000 ...</code></pre>
    <h3>{suites_h}</h3>
    <p class="sub">{suites_sub}</p>
    {suites}
  </div>
</section>

<section id="pacing">
  <div class="wrap">
    <h2>{pacing_h}</h2>
    <p class="sub">{pacing_sub}</p>
    <div class="tbl-scroll"><table>
      <thead><tr><th>{p_knob}</th><th>{p_ctrl}</th><th>{p_sem}</th></tr></thead>
      <tbody>
        <tr><td><code class="inline">--user-arrival burst|steady:&lt;s&gt;|poisson:&lt;λ&gt;</code></td>
            <td>{p_r1c}</td><td>{p_r1s}</td></tr>
        <tr><td><code class="inline">--concurrency N</code></td>
            <td>{p_r2c}</td><td>{p_r2s}</td></tr>
        <tr><td><code class="inline">--request-rate R</code></td>
            <td>{p_r3c}</td><td>{p_r3s}</td></tr>
        <tr><td><code class="inline">--trace-users N</code></td>
            <td>{p_r4c}</td><td>{p_r4s}</td></tr>
      </tbody>
    </table></div>
    <pre><code><span class="c"># open loop: 40 requests arriving at 2 req/s, no in-flight cap</span>
clawperf --mode hitrate --endpoint http://localhost:8000/v1 --model qwen3 \\
  --num-requests 40 --input-len 4096 --hit-rate 0.5 --request-rate 2</code></pre>
  </div>
</section>

<section id="metrics">
  <div class="wrap">
    <h2>{metrics_h}</h2>
    <p class="sub">{metrics_sub}</p>
    <pre><code>clawperf --mode scenario --endpoint http://lb:9000/v1 --model qwen3 \\
  --metrics-endpoint prefill=http://10.0.0.1:9101/metrics \\
  --metrics-endpoint decode=http://10.0.0.2:9102/metrics \\
  --reset-cache</code></pre>
    <p class="note">{metrics_note}</p>
  </div>
</section>

<section id="slo-syntax">
  <div class="wrap">
    <h2>{slo_h}</h2>
    <p class="sub">{slo_sub}</p>
    <div class="tbl-scroll"><table>
      <thead><tr><th>{s_col1}</th><th>{s_col2}</th><th>{s_col3}</th></tr></thead>
      <tbody>
        <tr><td><code class="inline">ttft.p99:1500</code></td><td><code class="inline">ttft.p99 &lt;= 1500ms</code></td><td>{s_shellsafe}</td></tr>
        <tr><td><code class="inline">tpot.avg=30</code></td><td><code class="inline">tpot.avg &lt;= 30ms</code></td><td>{s_shellsafe}</td></tr>
        <tr><td><code class="inline">'ttft.p99&lt;=1500'</code></td><td><code class="inline">ttft.p99 &lt;= 1500ms</code></td><td>{s_quoted}</td></tr>
        <tr><td><code class="inline">ttft.p99:ge:1500</code></td><td><code class="inline">ttft.p99 &gt;= 1500ms</code></td><td>{s_ge}</td></tr>
        <tr><td><code class="inline">'a&lt;=1,b&lt;=2'</code></td><td>{s_multi}</td><td>{s_multi_note}</td></tr>
      </tbody>
    </table></div>
    <figure>
      <div class="frame shot">
        <img loading="lazy" src="shots/shell-safety.png" alt="bash rejecting an unquoted --slo ttft.p99<=10000, next to the shell-safe spelling and ClawPerf's diagnostic for a bare metric">
      </div>
      <figcaption>{shots_cap3}</figcaption>
    </figure>
    <div class="grid c2">
      <div class="card">
        <p class="en"><b>Metrics:</b> <code class="inline">ttft</code> (time to first token),
        <code class="inline">tpot</code> (time per output token), <code class="inline">e2e</code>
        (end-to-end latency).</p>
        <p class="zh"><b>指标：</b><code class="inline">ttft</code>（首 token 时延）、
        <code class="inline">tpot</code>（每输出 token 时延）、<code class="inline">e2e</code>（端到端时延）。</p>
      </div>
      <div class="card">
        <p class="en"><b>Aggregates:</b> <code class="inline">avg</code>, <code class="inline">min</code>,
        <code class="inline">max</code>, and any percentile <code class="inline">p25 p50 p75 p90 p95 p99
        p99.9</code>. Several constraints AND together; the run stops the sweep at the first level that
        breaks any of them.</p>
        <p class="zh"><b>统计量：</b><code class="inline">avg</code>、<code class="inline">min</code>、
        <code class="inline">max</code>，以及任意分位 <code class="inline">p25 p50 p75 p90 p95 p99
        p99.9</code>。多条约束为「与」关系；一旦某一级打破了任意一条，扫描即在此停止。</p>
      </div>
    </div>
  </div>
</section>

<section id="params">
  <div class="wrap">
    <h2>{params_h}</h2>
    <p class="sub">{params_sub}</p>
    {params}
  </div>
</section>

<section id="env">
  <div class="wrap">
    <h2>{env_h}</h2>
    <p class="sub">{env_sub}</p>
    <div class="tbl-scroll"><table>
      <thead><tr><th>{env_c1}</th><th>{env_c2}</th></tr></thead>
      <tbody>
        <tr><td><code class="inline">CLAWPERF_ENDPOINT</code></td><td><code class="inline">--endpoint</code></td></tr>
        <tr><td><code class="inline">CLAWPERF_MODEL</code></td><td><code class="inline">--model</code></td></tr>
        <tr><td><code class="inline">CLAWPERF_API_KEY</code></td><td><code class="inline">--api-key</code></td></tr>
        <tr><td><code class="inline">CLAWPERF_OUTPUT</code></td><td><code class="inline">--output</code></td></tr>
        <tr><td><code class="inline">CLAWPERF_HISTORY</code></td><td><code class="inline">--history</code> (<code class="inline">''</code> disables)</td></tr>
        <tr><td><code class="inline">CLAWPERF_UPSTREAM_ENDPOINT</code></td><td><code class="inline">--upstream-endpoint</code></td></tr>
        <tr><td><code class="inline">CLAWPERF_TOKENIZER_BACKEND</code></td><td><code class="inline">transformers</code> | <code class="inline">modelscope</code> (force one)</td></tr>
        <tr><td><code class="inline">CLAWPERF_&lt;FIELD&gt;</code></td><td>{env_any}</td></tr>
      </tbody>
    </table></div>
    <p class="sub">{env_order}</p>
    <pre><code><span class="c"># clawperf.yaml</span>
mode: scenario
endpoint: http://localhost:8000/v1
model: qwen3-32b
context_profile: medium
num_users: 8
max_turns: 20
slo_constraints: ["ttft.p99&lt;=1500", "tpot.avg&lt;=30"]

<span class="c"># CLI &gt; env &gt; YAML &gt; defaults</span>
clawperf --config clawperf.yaml --num-users 16</code></pre>
  </div>
</section>

<section id="exit">
  <div class="wrap">
    <h2>{exit_h}</h2>
    <p class="sub">{exit_sub}</p>
    <div class="tbl-scroll"><table>
      <thead><tr><th>{exit_c1}</th><th>{exit_c2}</th></tr></thead>
      <tbody>
        <tr><td><code class="inline">0</code></td><td>{exit_0}</td></tr>
        <tr><td><code class="inline">1</code></td><td>{exit_1}</td></tr>
        <tr><td><code class="inline">2</code></td><td>{exit_2}</td></tr>
        <tr><td><code class="inline">3</code></td><td>{exit_130}</td></tr>
      </tbody>
    </table></div>
    <p class="sub">{exit_artifacts}</p>
  </div>
</section>

<section id="trouble">
  <div class="wrap">
    <h2>{trouble_h}</h2>
    <p class="sub">{trouble_sub}</p>
    <div class="tbl-scroll"><table>
      <thead><tr><th>{t_c1}</th><th>{t_c2}</th></tr></thead>
      <tbody>
        <tr><td><code class="inline">bash: =10000: No such file or directory</code></td><td>{t_r1}</td></tr>
        <tr><td><code class="inline">Tokenizer path '...' does not exist</code></td><td>{t_r2}</td></tr>
        <tr><td><code class="inline">Pre-flight: ... Connection reset by peer</code></td><td>{t_r3}</td></tr>
        <tr><td><code class="inline">UnicodeEncodeError</code> on Windows</td><td>{t_r4}</td></tr>
      </tbody>
    </table></div>
    <p class="sub">{trouble_more}</p>
  </div>
</section>

<footer>
  <div class="wrap">
    <p>{footer_text}</p>
  </div>
</footer>

<script>
(function () {{
  var root = document.documentElement;
  var store = {{
    get: function (k) {{ try {{ return localStorage.getItem(k); }} catch (e) {{ return null; }} }},
    set: function (k, v) {{ try {{ localStorage.setItem(k, v); }} catch (e) {{}} }}
  }};
  var savedTheme = store.get('clawperf-theme');
  var mq = window.matchMedia('(prefers-color-scheme: dark)');
  function applyTheme() {{
    var t = root.getAttribute('data-theme');
    var dark = t === 'dark' || (t === 'auto' && mq.matches);
    root.setAttribute('data-theme', dark ? 'dark' : 'light');
    root.setAttribute('data-theme-choice', t);
  }}
  root.setAttribute('data-theme', savedTheme || 'auto');
  applyTheme();
  if (mq.addEventListener) {{ mq.addEventListener('change', function () {{ if (root.getAttribute('data-theme-choice') === 'auto') applyTheme(); }}); }}

  var savedLang = store.get('clawperf-lang');
  var lang = savedLang || ((navigator.language || '').toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en');
  function applyLang() {{
    root.setAttribute('data-lang', lang);
    root.setAttribute('lang', lang === 'zh' ? 'zh-CN' : 'en');
    var btn = document.getElementById('lang-btn');
    if (btn) {{ btn.textContent = lang === 'zh' ? 'English' : '中文'; }}
  }}
  applyLang();
  document.getElementById('lang-btn').addEventListener('click', function () {{
    lang = lang === 'zh' ? 'en' : 'zh';
    store.set('clawperf-lang', lang);
    applyLang();
  }});
  document.getElementById('theme-btn').addEventListener('click', function () {{
    var cur = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    store.set('clawperf-theme', cur);
    root.setAttribute('data-theme', cur);
    root.setAttribute('data-theme-choice', cur);
    applyTheme();
  }});
}})();
</script>
</body>
</html>
"""


def fill_template(body: str) -> str:
    """Inject the bilingual strings into TEMPLATE (kept out of the big literal)."""
    strings = {
        "modes_nav": both("Modes", "模式"),
        "results_nav": both("Results", "实测结果"),
        "start_nav": both("Quick start", "快速开始"),
        "ref_nav": both("Reference", "完整参考"),
        "title": both("Reference", "完整参考"),
        "lead": both(
            f"Every mode, every context profile and all {_counts()[0]} parameters "
            f"({_counts()[1]} flags) — generated from the code, so it always matches "
            f"<code class=\"inline\">clawperf --help</code>.",
            f"全部模式、全部上下文档位，以及全部 {_counts()[0]} 个参数（{_counts()[1]} 个 flag）—— "
            f"由代码自动生成，永远与 <code class=\"inline\">clawperf --help</code> 一致。"),
        "modes_h": both("Modes", "模式"),
        "modes_sub": both(
            "Seven modes, each answering a different question. Every example below is runnable "
            "as-is against a local vLLM/SGLang endpoint.",
            "七种模式，各自回答不同的问题。下面每个示例都可以直接对着本地 vLLM/SGLang 端点运行。"),
        "profiles_h": both("Context profiles", "上下文档位"),
        "profiles_sub": both(
            "A profile is a named context size — the human-friendly way to say "
            "\"a typical coding session\" instead of typing token counts. It sets three numbers:",
            "档位就是「命名的上下文大小」—— 用「典型编码会话」这样的说法代替手写 token 数。它一次性设定三个数字："),
        "profiles_which_h": both("Which one should I use?", "该用哪个？"),
        "suites_h": both("Suites", "套件"),
        "suites_sub": both(
            "A suite runs several (users × profile) scenarios in sequence and writes one result "
            "file per scenario (<code class=\"inline\">&lt;output&gt;_&lt;profile&gt;_&lt;users&gt;u.json</code>).",
            "套件会按序跑多个（用户 × 档位）场景，每个场景写一份结果文件"
            "（<code class=\"inline\">&lt;output&gt;_&lt;档位&gt;_&lt;用户数&gt;u.json</code>）。"),
        "pacing_h": both("Pacing &amp; concurrency", "节奏与并发"),
        "pacing_sub": both(
            "Four knobs that are easy to confuse. The important distinction: a closed loop can never "
            "overload a server (the server throttles the load), an open loop can.",
            "四个容易混淆的旋钮。关键区别：闭环永远压不垮服务端（节奏由服务端决定），开环可以。"),
        "p_knob": both("Knob", "参数"),
        "p_ctrl": both("Controls", "控制对象"),
        "p_sem": both("Semantics", "语义"),
        "p_r1c": both("when each <b>session</b> joins", "每个<b>会话</b>何时加入"),
        "p_r1s": both("users then run their turns back-to-back",
                      "加入后各自连续跑自己的轮次"),
        "p_r2c": both("<b>closed-loop</b> in-flight request cap (hitrate / replay / trace)",
                      "<b>闭环</b>在途请求上限（hitrate / replay / trace）"),
        "p_r2s": both("the next request starts as soon as one finishes",
                      "上一个请求返回后立即发下一个"),
        "p_r3c": both("<b>open-loop</b> issue rate in req/s (Poisson)",
                      "<b>开环</b>发送速率（req/s，泊松到达）"),
        "p_r3s": both("requests are released on schedule regardless of completions",
                      "按计划发送，与是否完成无关"),
        "p_r4c": both("session-level concurrency for trace replay",
                      "trace 回放的会话级并发"),
        "p_r4s": both("turns inside one session stay ordered",
                      "同一会话内的轮次保持有序"),
        "metrics_h": both("Metrics &amp; PD disaggregation", "指标采集与 PD 分离"),
        "metrics_sub": both(
            "Pass one <code class=\"inline\">/metrics</code> per instance. Counters are summed into a "
            "fleet-wide view, ratio gauges are averaged, and the per-engine table gains one row per "
            "instance (engine ids are namespaced by endpoint).",
            "每个实例各传一个 <code class=\"inline\">/metrics</code>。计数器求和成全局视图，比率类指标取均值，"
            "逐引擎表按实例分行（引擎 id 以端点做命名空间）。"),
        "metrics_note": both(
            "Labels are optional (<code class=\"inline\">name=url</code>; default is host:port) and "
            "<code class=\"inline\">--metrics-endpoint</code> is repeatable or comma-separated. "
            "<code class=\"inline\">--reset-cache</code> resets every instance.",
            "标签可选（<code class=\"inline\">名称=url</code>，默认 host:port）；"
            "<code class=\"inline\">--metrics-endpoint</code> 可重复或用逗号分隔。"
            "<code class=\"inline\">--reset-cache</code> 会逐个重置所有实例。"),
        "slo_h": both("SLO constraint syntax", "SLO 约束语法"),
        "slo_sub": both(
            "<code class=\"inline\">&lt;metric&gt;.&lt;agg&gt;&lt;sep&gt;&lt;ms&gt;</code> — "
            "repeat <code class=\"inline\">--slo</code> to AND several constraints together. "
            "<b>In a shell, quote <code class=\"inline\">&lt;=</code> or use a separator without "
            "<code class=\"inline\">&lt;</code>/<code class=\"inline\">&gt;</code></b>, because those "
            "characters are redirections.",
            "<code class=\"inline\">&lt;指标&gt;.&lt;统计量&gt;&lt;分隔符&gt;&lt;毫秒&gt;</code> —— "
            "重复 <code class=\"inline\">--slo</code> 可「与」多个约束。"
            "<b>在 shell 中要么给 <code class=\"inline\">&lt;=</code> 加引号，要么改用不含 "
            "<code class=\"inline\">&lt;</code>/<code class=\"inline\">&gt;</code> 的分隔符</b>，"
            "因为这两个字符是重定向符号。"),
        "s_col1": both("Write", "写法"),
        "s_col2": both("Means", "含义"),
        "s_col3": both("Notes", "说明"),
        "s_shellsafe": both("shell-safe (no quoting)", "免引号"),
        "s_quoted": both("must be quoted in bash/zsh", "在 bash/zsh 中必须加引号"),
        "s_ge": both("the only shell-safe way to write &gt;=", "唯一免引号的 &gt;= 写法"),
        "s_multi": both("ttft.p99 &lt;= 1ms AND tpot.avg &lt;= 2ms", "ttft.p99 &lt;= 1ms 且 tpot.avg &lt;= 2ms"),
        "s_multi_note": both("one quoted argument, several constraints", "一个引号参数写多条约束"),
        "params_h": both("All parameters", "全部参数"),
        "params_sub": both(
            "Generated from <code class=\"inline\">clawperf --help</code> — every option, its default "
            "and its accepted values. Mode-specific groups are listed under the mode they belong to.",
            "由 <code class=\"inline\">clawperf --help</code> 自动生成 —— 每个参数、默认值与可选值。"
            "各模式专属参数列在对应模式之下。"),
        "shots_cap3": both(
            "The shell-quoting trap: unquoted <code class=\"inline\">&lt;=</code> is a redirection to bash, "
            "so <code class=\"inline\">--slo ttft.p99:10000</code> exists.",
            "shell 引号陷阱：不加引号的 <code class=\"inline\">&lt;=</code> 对 bash 来说是重定向，"
            "所以才有了 <code class=\"inline\">--slo ttft.p99:10000</code> 这种写法。"),
        "shots_more": both(
            "More captures — hit rate, trace budget sweep, multi-turn scenario — are on the "
            "<a href=\"index.html#shots\">overview page</a>.",
            "更多截图（命中率、trace 预算扫描、多轮场景）见<a href=\"index.html#shots\">项目总览页</a>。"),
        "env_h": both("Environment variables &amp; config file", "环境变量与配置文件"),        "env_sub": both(
            "Precedence: <b>CLI &gt; environment &gt; YAML (<code class=\"inline\">--config</code>) "
            "&gt; defaults</b>. Every config field has a <code class=\"inline\">CLAWPERF_*</code> "
            "counterpart, upper-cased.",
            "优先级：<b>CLI &gt; 环境变量 &gt; YAML（<code class=\"inline\">--config</code>）&gt; 默认值</b>。"
            "每个配置字段都有对应的大写 <code class=\"inline\">CLAWPERF_*</code> 变量。"),
        "env_c1": both("Variable", "变量"),
        "env_c2": both("Equivalent to", "等价于"),
        "env_any": both("any field: <code class=\"inline\">CLAWPERF_NUM_USERS</code>, "
                        "<code class=\"inline\">CLAWPERF_CONTEXT_PROFILE</code>, "
                        "<code class=\"inline\">CLAWPERF_SLO_TTFT_MS</code>, …",
                        "任意字段：<code class=\"inline\">CLAWPERF_NUM_USERS</code>、"
                        "<code class=\"inline\">CLAWPERF_CONTEXT_PROFILE</code>、"
                        "<code class=\"inline\">CLAWPERF_SLO_TTFT_MS</code> 等"),
        "env_order": both(
            "An explicitly passed flag always wins — even when its value equals the default.",
            "显式传入的 flag 永远优先 —— 即使其取值恰好等于默认值。"),
        "exit_h": both("Output &amp; exit codes", "产物与退出码"),
        "exit_sub": both(
            "Every run writes a JSON result plus a Markdown report next to it "
            "(<code class=\"inline\">report.json</code> → <code class=\"inline\">report.md</code>).",
            "每次运行都会写一份 JSON 结果，并在旁边生成 Markdown 报告"
            "（<code class=\"inline\">report.json</code> → <code class=\"inline\">report.md</code>）。"),
        "exit_c1": both("Code", "退出码"),
        "exit_c2": both("Meaning", "含义"),
        "exit_0": both("the benchmark ran; results written", "基准跑完并写出结果"),
        "exit_1": both("configuration or pre-flight error (no benchmark ran)",
                       "配置或预检错误（未开始跑基准）"),
        "exit_2": both("the benchmark ran but <b>every</b> request failed (CI gate)",
                       "基准跑了但<b>全部</b>请求失败（CI 门禁）"),
        "exit_130": both("interrupted (Ctrl+C); partial results are written before exiting",
                         "被中断（Ctrl+C）；退出前会写出部分结果"),        "exit_artifacts": both(
            "Also written: the Markdown report, and one JSONL line per run in the history file "
            "(<code class=\"inline\">--history</code>, default <code class=\"inline\">clawperf_history.jsonl</code>). "
            "Regenerate a report from any result with <code class=\"inline\">clawperf report results.json</code>, "
            "or diff two runs with <code class=\"inline\">clawperf compare a.json b.json</code>.",
            "另外还会写：Markdown 报告，以及每次运行一行 JSONL 的历史文件"
            "（<code class=\"inline\">--history</code>，默认 <code class=\"inline\">clawperf_history.jsonl</code>）。"
            "用 <code class=\"inline\">clawperf report results.json</code> 可从任意结果重新生成报告，"
            "用 <code class=\"inline\">clawperf compare a.json b.json</code> 可对比两次运行。"),
        "trouble_h": both("Troubleshooting", "故障排查"),
        "trouble_sub": both("The four failures users hit most often.",
                            "用户最常遇到的四类问题。"),
        "t_c1": both("Symptom", "现象"),
        "t_c2": both("Fix", "解决"),
        "t_r1": both("the shell ate the <code class=\"inline\">&lt;</code> in "
                     "<code class=\"inline\">--slo ttft.p99&lt;=10000</code>. Use "
                     "<code class=\"inline\">--slo ttft.p99:10000</code> or quote the spec.",
                     "shell 吃掉了 <code class=\"inline\">--slo ttft.p99&lt;=10000</code> 中的 "
                     "<code class=\"inline\">&lt;</code>。改用 "
                     "<code class=\"inline\">--slo ttft.p99:10000</code>，或给参数加引号。"),
        "t_r2": both("the path is not visible inside the container — the error lists the parent "
                     "directory; mount it with <code class=\"inline\">-v /mnt/model:/mnt/model:ro</code>.",
                     "容器内看不到该路径 —— 报错会列出父目录内容；用 "
                     "<code class=\"inline\">-v /mnt/model:/mnt/model:ro</code> 挂载。"),
        "t_r3": both("the server reset the tiny probe (often while still loading weights). "
                     "Transient errors are retried 3× with backoff; add "
                     "<code class=\"inline\">--no-preflight</code> to skip the probe entirely.",
                     "服务端重置了这个极小探针（常见于仍在加载权重）。传输类错误会自动退避重试 3 次；"
                     "加 <code class=\"inline\">--no-preflight</code> 可完全跳过探针。"),
        "t_r4": both("the CLI forces UTF-8 stdio; if a third-party tool still fails, set "
                     "<code class=\"inline\">PYTHONIOENCODING=utf-8</code>.",
                     "CLI 已强制 UTF-8 stdio；若第三方工具仍报错，设置 "
                     "<code class=\"inline\">PYTHONIOENCODING=utf-8</code>。"),
        "trouble_more": both(
            "More detail (including the tokenizer backend selection) is in the "
            f"<a href=\"{REPO}#troubleshooting\">README</a> and the "
            f"<a href=\"{REPO}/blob/main/docs/E2E_TEST_REPORT.md\">E2E test report</a>.",
            "更多细节（含 tokenizer 后端选择）见 "
            f"<a href=\"{REPO}#troubleshooting\">README</a> 与 "
            f"<a href=\"{REPO}/blob/main/docs/E2E_TEST_REPORT.md\">端到端测试报告</a>。"),
        "footer_text": both(
            f"ClawPerf — Apache-2.0 · <a href=\"index.html\">overview</a> · "
            f"<a href=\"{REPO}\">GitHub</a> · built on EvalScope perf. "
            f"This page is generated by <code class=\"inline\">scripts/gen_reference.py</code>.",
            f"ClawPerf — Apache-2.0 · <a href=\"index.html\">项目总览</a> · "
            f"<a href=\"{REPO}\">GitHub</a> · 构建于 EvalScope perf。"
            f"本页由 <code class=\"inline\">scripts/gen_reference.py</code> 生成。"),
    }
    out = body
    for key, value in strings.items():
        out = out.replace("{" + key + "}", value)
    return out


_COUNT_CACHE: list = []


def _counts() -> tuple:
    if not _COUNT_CACHE:
        groups = collect_groups()
        _COUNT_CACHE.append(sum(len(rows) for _, rows in groups))
        _COUNT_CACHE.append(sum(len(r["opts"]) for _, rows in groups for r in rows))
    return _COUNT_CACHE[0], _COUNT_CACHE[1]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 when docs/reference.html is out of date")
    args = ap.parse_args(argv[1:])

    html_out = build_html()

    if args.check:
        if not OUT.is_file():
            print(f"FAIL: {OUT} does not exist — run python scripts/gen_reference.py")
            return 1
        current = OUT.read_text(encoding="utf-8")
        if current != html_out:
            print("FAIL: docs/reference.html is out of date — run "
                  "python scripts/gen_reference.py")
            return 1
        print(f"reference up to date ({len(html_out):,} bytes)")
        return 0

    OUT.write_text(html_out, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(html_out):,} bytes, "
          f"{_counts()[0]} parameters / {_counts()[1]} flags)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
