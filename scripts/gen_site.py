#!/usr/bin/env python3
"""Generate the MkDocs (Material) sources for the ClawPerf documentation site.

One page per mode, one file per language. Everything that can drift is derived:

  * parameters  -> clawperf.cli.build_parser()     (never drifts from --help)
  * profiles    -> clawperf.context_profiles       (the real numbers)
  * output      -> docs/samples.json               (captured by gen_samples.py)
  * prose       -> this file, written in Markdown, in both languages

Emitted into docs/ (the MkDocs docs_dir), zh mirroring en:

  index.{en,zh}.md            modes/scenario.{en,zh}.md
  quickstart.{en,zh}.md       modes/hitrate.{en,zh}.md
  configuration.{en,zh}.md    modes/slo.{en,zh}.md
  reference.{en,zh}.md        modes/agent.{en,zh}.md
                              modes/trace.{en,zh}.md
                              modes/record-replay.{en,zh}.md

Usage:
  python scripts/gen_site.py            # write the Markdown
  python scripts/gen_site.py --check    # fail if any file is out of date
"""

from __future__ import annotations

import argparse
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
SAMPLES = DOCS / "samples.json"
I18N = DOCS / "i18n" / "params_zh.json"
REPO = "https://github.com/ucm-system/ClawPerf"
SITE = "https://ucm-system.github.io/ClawPerf"
LANGS = ("en", "zh")


# ── Markdown building blocks ─────────────────────────────────────────────────

def fence(code: str, lang: str = "bash", title: str | None = None) -> str:
    """A fenced block with an optional title bar (Material adds the copy button)."""
    head = f"```{lang}"
    if title:
        head += f' title="{title}"'
    return f"{head}\n{code.rstrip()}\n```"


def indent(text: str, spaces: int = 4) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else "" for line in text.split("\n"))


def adm(kind: str, body: str, title: str | None = None) -> str:
    head = f"!!! {kind}"
    if title:
        head += f' "{title}"'
    return f"{head}\n\n{indent(body)}"


def tabs(items: list) -> str:
    """Material content tabs: [(label, body), ...]."""
    return "\n\n".join(f'=== "{label}"\n\n{indent(body)}' for label, body in items)


def table(headers: list, rows: list) -> str:
    def cell(value: str) -> str:
        # pymdownx.emoji turns any :word: into a twemoji, and the CLI help text
        # documents the shell-safe form as "--slo ttft.p99:ge:1500" — which would
        # render as the Georgian flag and corrupt the syntax. Escape it.
        value = re.sub(r":([a-z0-9_+-]{2,30}):", r"\\:\1:", value)
        return value.replace("|", "\\|").replace("\n", "<br>").strip()

    lines = ["| " + " | ".join(cell(h) for h in headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(cell(c) for c in row) + " |")
    return "\n".join(lines)


def cards(items: list) -> str:
    """Material grid cards: [(icon, title, body), ...]."""
    body = ['<div class="grid cards" markdown>', ""]
    for icon, title, text in items:
        body += [f"-   :material-{icon}:{{ .lg .middle }} {title}", "", "    ---", "", f"    {text}", ""]
    body.append("</div>")
    return "\n".join(body)


def image(path: str, caption: str) -> str:
    """A standalone image; Material promotes the alt text to a figure caption."""
    return f"![{caption}]({path})"


def page(rel: str, lang: str, base: str = "") -> str:
    """Relative link to another page in the same language.

    Markdown links are resolved against the linking file's own directory, so a
    page under modes/ passes base="../".
    """
    stem, _, anchor = rel.partition("#")
    suffix = "" if stem == "E2E_TEST_REPORT" else f".{lang}"
    link = f"{base}{stem}{suffix}.md"
    return f"{link}#{anchor}" if anchor else link


def sample_block(key: str, title: str | None = None) -> str:
    data = SAMPLES_DATA["samples"][key]
    return fence(data["output"], "console", title or data["command"])


# ── parameters, profiles and suites ──────────────────────────────────────────

def _help_text(action) -> str:
    return (action.help or "").strip().replace("%%", "%")


def collect_groups() -> list:
    parser = build_parser()
    groups = []
    for group in parser._action_groups:
        actions = [a for a in group._group_actions if a.option_strings]
        if not actions or group.title == "options":
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
            rows.append(row)
        groups.append((group.title, rows))
    return groups


def default_text(row: dict) -> str:
    value = row["default"]
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None or value == "":
        acts = set(row["actions"])
        if "_StoreTrueAction" in acts:
            return "off"
        if "_StoreFalseAction" in acts:
            return "on"
        return "—"
    return str(value)


def option_text(row: dict) -> str:
    is_flag = "_StoreTrueAction" in row["actions"] or "_StoreFalseAction" in row["actions"]
    parts = []
    for opt in row["opts"]:
        parts.append(f"`{opt}`" if is_flag
                     else f"`{opt} <{row['metavar'] or row['dest'].upper()}>`")
    return "<br>".join(parts)


def options_rows(rows: list, lang: str, i18n: dict) -> list:
    out = []
    for row in rows:
        if lang == "zh" and i18n.get(row["dest"]):
            desc = i18n[row["dest"]]
        else:
            desc = "<br>".join(row["helps"]) or "—"
        if row["choices"]:
            choices = ", ".join(f"`{c}`" for c in row["choices"])
            label = "可选值" if lang == "zh" else "choices"
            desc += f"<br>**{label}:** {choices}"
        out.append([option_text(row), f"`{default_text(row)}`", desc])
    return out


def profiles_rows() -> list:
    out = []
    for name in PROFILE_ORDER:
        p = CONTEXT_PROFILES[name]
        base = p["system_prefix_tokens"] + p["user_prefix_tokens"] + p["input_tokens_per_turn"]
        out.append([f"`{name}`", f"{p['system_prefix_tokens']:,}", f"{p['user_prefix_tokens']:,}",
                    f"{p['input_tokens_per_turn']:,}", f"**{base:,}**", f"~{round(base / 1000)}K"])
    return out


def suites_rows() -> list:
    out = []
    for name, suite in SUITES.items():
        spec = suite["profiles"]
        if spec == "realistic":
            shown = " → ".join(f"`{p}`" for p in REALISTIC_PROFILES)
            count = len(REALISTIC_PROFILES)
        elif isinstance(spec, str):
            shown = f"`{spec}`"
            count = 1
        else:
            shown = " + ".join(f"`{p}`" for p in spec)
            count = len(spec)
        out.append([f"`{name}`", ", ".join(str(u) for u in suite["users"]), shown,
                    str(suite["max_turns"]), str(suite["output_tokens_per_turn"]),
                    str(count * len(suite["users"]))])
    return out


# ── mode content ─────────────────────────────────────────────────────────────

MODES = [
    {
        "slug": "scenario",
        "name": "scenario",
        "icon": "account-group",
        "tag": {"en": "The core agentic-load simulator", "zh": "核心 Agent 负载模拟器"},
        "why": {
            "en": "A coding agent does not send one prompt — it grows a conversation, reuses the same "
                  "system prefix every turn, and several sessions run at once. A single-shot benchmark "
                  "cannot see the prefill that accumulates turn by turn, so it reports a TTFT your "
                  "users will never get. **This mode models the conversation.**",
            "zh": "编码 Agent 不会只发一次请求 —— 它让会话不断增长、每轮复用同一段系统前缀，并且多个会话并发。"
                  "单次请求压测看不到逐轮累积的预填充量，于是给出一个用户永远拿不到的 TTFT。"
                  "**这个模式直接对「会话」建模。**",
        },
        "diagram": ("assets/workload.svg",
                    {"en": "Each turn reuses everything the previous turn already prefilled: the system "
                           "prefix, the user prefix and the conversation history. Only the newest input "
                           "is cold-prefilled.",
                     "zh": "每一轮都复用了上一轮已预填充的内容：系统前缀、用户前缀与会话历史；"
                           "只有最新输入需要冷预填充。"}),
        "command": ["clawperf --mode scenario \\",
                    "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\",
                    "  --tokenizer /mnt/model/Qwen3-0.6B \\",
                    "  --context-profile medium \\",
                    "  --num-users 8 --max-turns 20 --user-arrival poisson:2 \\",
                    "  --metrics-endpoint http://localhost:8000/metrics --reset-cache \\",
                    "  --output results_scenario.json"],
        "params": [
            ("--context-profile",
             "Named context size: `fresh` 7K → `xxl` 392K. Sets the system prefix, per-user prefix and "
             "per-turn input at once.",
             "命名的上下文大小：`fresh` 7K → `xxl` 392K，一次性设定系统前缀、用户前缀与每轮输入。"),
            ("--num-users", "Concurrent sessions.", "并发会话数。"),
            ("--max-turns", "Turns per session; history accumulates across them.",
             "每个会话的轮数；历史在这些轮之间累积。"),
            ("--user-arrival", "When sessions join: `burst`, `steady:<s>`, `poisson:<lambda>`.",
             "会话加入时机：`burst`、`steady:<秒>`、`poisson:<lambda>`。"),
            ("--max-context-tokens",
             "Where append-mode compaction triggers — set it to the model's real window.",
             "追加式压缩的触发阈值 —— 设为模型真实窗口。"),
            ("--suite", "Sweep several (users × profile) combinations in one command.",
             "一条命令扫完多组（并发 × 档位）。"),
        ],
        "sample": "scenario",
        "read": {
            "en": ["**TTFT** should grow with context: compare the first turns with the last ones.",
                   "**Decode throughput** shows whether batching still holds up as sessions multiply.",
                   "**Compactions** above zero means a session hit the window and its history was "
                   "folded — expected on long runs, not an error.",
                   "**Failed requests** must stay at zero; a single 400 usually means the context no "
                   "longer fits."],
            "zh": ["**TTFT** 应随上下文增长：把最初的几轮和最后的几轮对比。",
                   "**解码吞吐**反映会话变多时批处理是否还撑得住。",
                   "**Compactions** 大于 0 表示某个会话触及窗口、历史被折叠 —— 长跑时属正常，不是错误。",
                   "**失败请求**必须为 0；一旦出现 400，通常是上下文已经放不下了。"],
        },
    },
    {
        "slug": "hitrate",
        "name": "hitrate",
        "icon": "database",
        "tag": {"en": "Is the prefix cache actually working?", "zh": "前缀缓存到底有没有生效？"},
        "why": {
            "en": "Prefix caching is the single biggest lever on agent latency, and it is usually "
                  "assumed rather than measured. This mode builds a workload with a **known** shared "
                  "fraction, prefills it, then reads the real hit rate out of the server's own "
                  "Prometheus counters — so “we enabled prefix caching” becomes a number you can put "
                  "in a review.",
            "zh": "前缀缓存是 Agent 时延上最大的一根杠杆，但通常只是「假设生效」而没有被测量。"
                  "这个模式构造一个**已知**共享比例的负载，先预填充，再从服务端自己的 Prometheus 计数器读出真实命中率 —— "
                  "于是「我们开了前缀缓存」变成一个可以写进评审的数字。",
        },
        "diagram": ("assets/hitrate.svg",
                    {"en": "The hit rate is never inferred from the prompt shape: it is read back from "
                           "the server's counters as a start/end delta, so target and measurement stay "
                           "independent.",
                     "zh": "命中率不从提示词形状推断：而是从服务端计数器的起止差值读回来，"
                           "因此「目标」与「测量」相互独立。"}),
        "command": ["clawperf --mode hitrate \\",
                    "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\",
                    "  --tokenizer /mnt/model/Qwen3-0.6B \\",
                    "  --num-requests 200 --input-len 8192 --hit-rate 0.7 --prefix-num 4 \\",
                    "  --output-len 128 --concurrency 8 \\",
                    "  --metrics-endpoint http://localhost:8000/metrics --reset-cache \\",
                    "  --output results_hitrate.json"],
        "params": [
            ("--hit-rate",
             "Target shared fraction 0..1; derives the prefix length. Mutually exclusive with "
             "`--prefix-len`.",
             "目标共享比例 0..1，用于反推前缀长度；与 `--prefix-len` 互斥。"),
            ("--input-len", "Total prompt length = shared prefix + boundary + unique suffix.",
             "提示词总长度 = 共享前缀 + 边界 + 各自独有的后缀。"),
            ("--prefix-num",
             "How many *distinct* prefixes are in play — this is what makes it multi-tenant.",
             "有多少个*不同*前缀 —— 这正是多租户感的来源。"),
            ("--num-requests", "Measure-phase request count.", "测量阶段的请求数。"),
            ("--no-prefill", "Skip the prefill phase to measure cold-cache behaviour.",
             "跳过预填充阶段，测冷缓存表现。"),
            ("--reset-cache", "Evict the cache first so residual traffic does not inflate the result.",
             "先清空缓存，避免残余流量抬高结果。"),
        ],
        "sample": "hitrate",
        "live_sample": "live-hitrate",
        "read": {
            "en": ["**TARGET vs MEASURED** is the headline: they should be within a point or two. A "
                   "large gap means the prompts are not sharing what you think they share.",
                   "**Speedup** is the real payoff — the theoretical ceiling is `1/(1-hit)`, and the "
                   "report prints both.",
                   "**Per-engine rows** show which instance served the reuse; in PD setups the prefill "
                   "instance usually carries it."],
            "zh": ["**目标 vs 实测**是核心结论：两者应在一两个点以内。差距过大说明提示词的共享方式与你的预期不符。",
                   "**加速比**才是真正的收益 —— 理论上限是 `1/(1-命中率)`，报告会同时给出两者。",
                   "**逐引擎行**说明复用发生在哪个实例；PD 部署中通常是 prefill 实例。"],
        },
    },
    {
        "slug": "slo",
        "name": "slo",
        "icon": "speedometer",
        "tag": {"en": "Turn latency budgets into a capacity number", "zh": "把时延预算变成容量数字"},
        "why": {
            "en": "“How many users can this box serve?” is the question every capacity plan needs, and "
                  "it is not answered by a single load level. This mode raises concurrency step by "
                  "step, evaluates **every** constraint at each level, and stops at the first one that "
                  "breaks — naming which constraint broke it.",
            "zh": "「这台机器能支撑多少用户」是每个容量规划都要回答的问题，而单个负载档位答不了。"
                  "这个模式逐级提高并发，在每一级评估**全部**约束，并在第一个被打破的档位停下 —— "
                  "并指出是哪条约束先破的。",
        },
        "diagram": ("assets/slo.svg",
                    {"en": "Every level is judged against all constraints at once, so the reported "
                           "capacity is the level that survived all of them — and the failing level "
                           "tells you which one is binding.",
                     "zh": "每一档都要同时满足全部约束，因此给出的容量是「全都扛住了」的那一档；"
                           "失败的那一档则告诉你是哪条约束先到极限。"}),
        "command": ["clawperf --mode slo \\",
                    "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\",
                    "  --tokenizer /mnt/model/Qwen3-0.6B \\",
                    "  --slo ttft.p99:1500 --slo tpot.avg:30 --slo e2e.max:30000 \\",
                    "  --slo-min-users 1 --slo-max-users 200 --slo-step-strategy geometric \\",
                    "  --slo-step-turns 5 --slo-error-rate 0.01 \\",
                    "  --output results_slo.json"],
        "params": [
            ("--slo",
             "Repeatable constraint `<metric>.<agg><sep><ms>`; all constraints AND together.",
             "可重复的约束 `<指标>.<统计量><分隔符><毫秒>`；多条之间为「与」关系。"),
            ("--slo-min-users", "Lowest concurrency level the sweep starts from.", "扫描的起始并发用户数。"),
            ("--slo-max-users", "Highest level the sweep may reach.", "扫描可达到的最大并发用户数。"),
            ("--slo-step-strategy", "`geometric` doubles each step; `linear` walks one level at a time.",
             "`geometric` 每步翻倍；`linear` 逐级递增。"),
            ("--slo-step-turns",
             "Measured turns per user at each level (plus `--slo-step-warmup-turns`).",
             "每一级每个用户参与测量的轮数（另有 `--slo-step-warmup-turns` 预热轮）。"),
            ("--slo-error-rate", "Extra pass condition on the error fraction.", "额外的错误率达标条件。"),
            ("--slo-step-timeout-s",
             "Wall-clock budget per level; an overrun counts as TIMEOUT and fails.",
             "每级的墙钟预算；超时记为 TIMEOUT 并判定不达标。"),
        ],
        "sample": "slo",
        "read": {
            "en": ["**One column per constraint** — the report never hides a constraint you asked for.",
                   "**Max sustained users** is the number to quote; the next level up is where it breaks.",
                   "Look at *which* column turned red: capacity is usually bound by `e2e.max` long "
                   "before TTFT suffers.",
                   "**TIMEOUT** rows mean the level could not finish inside `--slo-step-timeout-s` — "
                   "raise it for very long contexts."],
            "zh": ["**每条约束一列** —— 报告不会隐藏你要求的任何一条约束。",
                   "**最大可支撑用户数**就是要引用的数字；再上一档就是它开始崩的地方。",
                   "注意*哪一列*变红：容量往往在 TTFT 变差之前很久就被 `e2e.max` 卡住。",
                   "**TIMEOUT** 行表示该档没能在 `--slo-step-timeout-s` 内跑完 —— 超长上下文时可以调大。"],
        },
    },
    {
        "slug": "agent",
        "name": "agent",
        "icon": "robot",
        "tag": {"en": "Let the model actually work", "zh": "让模型真的干活"},
        "why": {
            "en": "Synthetic prompts are a guess at what agents send. In this mode the model under test "
                  "really calls functions — reading files, editing them, running shell commands — so "
                  "the traffic has the shape of agent work: bursty tool loops, long growing histories, "
                  "and a task that either completes or does not.",
            "zh": "合成提示词只是对 Agent 流量的猜测。这个模式让被测模型真的调用工具 —— 读文件、改代码、执行 shell —— "
                  "于是流量具备 Agent 工作的形态：突发的工具循环、不断增长的长历史，"
                  "以及「任务完成或没完成」这个结果。",
        },
        "diagram": ("assets/agent.svg",
                    {"en": "The model calls tools, reads the results back, and loops until the task is "
                           "done or the step budget runs out — with the context growing on every "
                           "iteration.",
                     "zh": "模型调用工具、读回结果、循环直到任务完成或步数预算耗尽 —— 每一轮上下文都在增长。"}),
        "command": ["clawperf --mode agent \\",
                    "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\",
                    "  --tokenizer /mnt/model/Qwen3-0.6B \\",
                    "  --agent-tasks 8 --agent-max-steps 12 --agent-max-tokens 512 \\",
                    "  --agent-shell-timeout 30 \\",
                    "  --output results_agent.json"],
        "params": [
            ("--agent-tasks", "How many coding tasks run concurrently.", "并发运行的编码任务数。"),
            ("--agent-max-steps", "Tool-calling steps allowed per task before it is cut off.",
             "每个任务在被截断前允许的工具调用步数。"),
            ("--agent-max-tokens", "Generated tokens per model call inside a task.",
             "任务内每次模型调用的生成 token 上限。"),
            ("--agent-shell-timeout", "Seconds a single shell command may take.",
             "单条 shell 命令允许的最长秒数。"),
            ("--agent-task-file", "Bring your own tasks instead of the built-in presets.",
             "用自定义任务替代内置任务集。"),
            ("--agent-workdir", "Base directory for the per-task workspaces.",
             "每个任务工作区的根目录。"),
        ],
        "sample": "agent",
        "note": {"en": "Needs tool calling on the endpoint. For vLLM that means "
                       "`--enable-auto-tool-choice --tool-call-parser qwen3_xml` (the parser name "
                       "depends on the model family).",
                 "zh": "需要端点开启工具调用。vLLM 需要 "
                       "`--enable-auto-tool-choice --tool-call-parser qwen3_xml`（解析器名称随模型系列而定）。"},
        "read": {
            "en": ["**Task completion** is the first thing to read: a fast run that never finishes the "
                   "task is not a fast server.",
                   "**Steps and tokens per task** are the real cost of agent work — they decide your "
                   "token budget, not the prompt length.",
                   "**TTFT per step** shows whether tool-loop latency is dominated by the server or by "
                   "the tools."],
            "zh": ["**任务完成率**是第一眼要看的：跑得快但任务从没做完，不代表服务快。",
                   "**每个任务的步数与 token**才是 Agent 工作的真实成本 —— 决定预算的是它们，不是提示词长度。",
                   "**每步 TTFT** 说明工具循环的时延到底由服务端还是由工具主导。"],
        },
    },
    {
        "slug": "trace",
        "name": "trace",
        "icon": "magnify",
        "tag": {"en": "Use your own traffic as the workload", "zh": "用你自己的流量当负载"},
        "why": {
            "en": "Every simulated workload is a guess about your traffic; a production trace is not. "
                  "This mode replays a real trace's block hashes through a simulated cache to measure "
                  "achievable reuse and the hit-rate-vs-budget curve — no endpoint needed — and can "
                  "then send the trace's actual requests to your endpoint to measure what that "
                  "workload really costs.",
            "zh": "任何模拟负载都是对你流量的猜测，而生产 trace 不是。"
                  "这个模式把真实 trace 的 block hash 送进模拟缓存，测出可达复用率与「命中率-预算」曲线（不需要端点）；"
                  "随后还能把 trace 里的真实请求发到你的端点，测出这份负载的真实代价。",
        },
        "diagram": ("assets/trace.svg",
                    {"en": "Two paths over the same trace: a pure simulation of the KV cache (no "
                           "endpoint), and an optional real replay of the trace's requests against your "
                           "server.",
                     "zh": "同一份 trace 上的两条路径：纯 KV 缓存模拟（不需要端点），"
                           "以及可选的、把 trace 请求真实回放到你的服务端。"}),
        "command": ["# simulation only — no endpoint needed",
                    "clawperf --mode trace --trace-file trace.jsonl.gz \\",
                    "  --budget-sweep --eviction-policy lru",
                    "",
                    "# simulation + real replay, clamped to the model window",
                    "clawperf --mode trace --trace-file trace.jsonl.gz \\",
                    "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\",
                    "  --tokenizer /mnt/model/Qwen3-0.6B \\",
                    "  --cache-budget-gb 40 --kv-bytes-per-token 2.0 \\",
                    "  --model-context-length 32768 --trace-users 4 \\",
                    "  --output results_trace.json"],
        "params": [
            ("--trace-file",
             "kvcache.ai JSONL (`hash_ids`, `input_length`, optional `block_size`), gzipped or plain, "
             "or `-` for stdin.",
             "kvcache.ai 格式 JSONL（`hash_ids`、`input_length`、可选 `block_size`），可 gzip，"
             "或用 `-` 从标准输入读。"),
            ("--budget-sweep", "Scan several cache sizes to find where returns flatten.",
             "扫描多个缓存容量档位，找出收益拐点。"),
            ("--cache-budget-tokens", "Fixed budget in tokens.", "按 token 指定固定预算。"),
            ("--cache-budget-gb", "Fixed budget in GB, via `--kv-bytes-per-token`.",
             "按 GB 指定固定预算，配合 `--kv-bytes-per-token` 换算。"),
            ("--eviction-policy", "`lru` or `fifo`.", "`lru` 或 `fifo`。"),
            ("--trace-users", "Session-level concurrency when the trace carries user/session ids.",
             "trace 带用户/会话标识时的会话级并发。"),
            ("--model-context-length",
             "Clamps replay output length; requests that cannot fit are skipped with a reason.",
             "裁剪回放的输出长度；放不下的请求会带原因跳过。"),
        ],
        "sample": "trace",
        "read": {
            "en": ["**Hit rate vs budget** is the sizing answer: pick the budget just before the curve "
                   "flattens.",
                   "**Evictions** tell you the cache is thrashing rather than simply too small.",
                   "On real replay, **context overflow** entries are skipped on purpose — they are "
                   "physical impossibilities, not server failures."],
            "zh": ["**命中率-预算曲线**就是定容答案：选曲线刚好变平之前的那个预算。",
                   "**驱逐次数**说明缓存是在颠簸，而不只是容量不够。",
                   "真实回放中 **context overflow** 是主动跳过的 —— 那是物理上放不下，不是服务端故障。"],
        },
    },
    {
        "slug": "record-replay",
        "name": "record & replay",
        "icon": "record-rec",
        "tag": {"en": "Capture once, replay anywhere", "zh": "录一次，随处回放"},
        "why": {
            "en": "The most convincing benchmark is your own session. Point a real agent (Claude Code, "
                  "any OpenAI or Anthropic client) at the recording proxy while you work; afterwards you "
                  "can replay that exact session against any endpoint — before and after a config "
                  "change, or between two vendors — with the KV-cache prefix aligned the way it was "
                  "live.",
            "zh": "最有说服力的基准就是你自己的会话。工作时把真实 Agent"
                  "（Claude Code 或任意 OpenAI/Anthropic 客户端）指向录制代理，之后就能把这段会话原样回放到任意端点 —— "
                  "改配置前后对比、两家供应商对比 —— 并且 KV 缓存前缀与当时一致。",
        },
        "diagram": ("assets/record-replay.svg",
                    {"en": "The proxy sits between the agent and the upstream model and writes every "
                           "exchange to JSONL; the replay side then feeds that recording to any "
                           "endpoint.",
                     "zh": "代理位于 Agent 与上游模型之间，把每一次交互写入 JSONL；"
                           "回放侧再把这份录制喂给任意端点。"}),
        "command": ["# terminal 1 — record (accepts /v1/chat/completions and /v1/messages)",
                    "clawperf --mode record --proxy-port 9090 \\",
                    "  --upstream-endpoint https://api.example.com/v1 --upstream-api openai \\",
                    "  --recording session.jsonl",
                    "# ... point your agent at http://localhost:9090/v1, work, then Ctrl+C",
                    "",
                    "# terminal 2 — replay it against any endpoint",
                    "clawperf --mode replay --recording session.jsonl \\",
                    "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\",
                    "  --tokenizer /mnt/model/Qwen3-0.6B \\",
                    "  --history-mode live --concurrency 4 \\",
                    "  --output results_replay.json"],
        "params": [
            ("--recording",
             "The JSONL file to write (record) or read (replay). Appends across restarts and tells you "
             "what it kept.",
             "写入（record）或读取（replay）的 JSONL 文件；跨重启追加，并提示保留了多少历史。"),
            ("--upstream-endpoint", "Where the proxy forwards to.", "代理转发到哪里。"),
            ("--upstream-api", "`openai`, `anthropic` or `auto` — Anthropic is translated on the fly.",
             "`openai`、`anthropic` 或 `auto` —— Anthropic 会被实时翻译。"),
            ("--history-mode",
             "`live` feeds real responses into the next turn (prefix-aligned); `verbatim` replays "
             "recorded messages as-is for A/B.",
             "`live` 把真实返回作为下一轮历史（前缀对齐）；`verbatim` 原样回放录制内容，适合 A/B。"),
            ("--concurrency", "In-flight requests during replay.", "回放时的在途请求数。"),
        ],
        "sample": "replay",
        "read": {
            "en": ["**live** is what you want for capacity work: the server's own responses become the "
                   "next turn's history, so the prefixes line up exactly as they did in production.",
                   "Use **verbatim** when comparing two servers on identical input — same bytes, "
                   "different server.",
                   "The verdict uses the same thresholds as every other mode, so two reports diff "
                   "cleanly."],
            "zh": ["做容量评估要用 **live**：服务端真实返回成为下一轮历史，前缀与生产环境完全一致。",
                   "比较两台服务端处理同样输入时用 **verbatim** —— 同样的字节，不同的服务端。",
                   "结论阈值与其他模式一致，因此两份报告可以直接对比。"],
        },
    },
]

SAMPLE_NOTES_ZH = {
    "slo": "真机 vLLM-Ascend 910B3 SLO 扫描（Qwen3-0.6B，32K 窗口）。",
    "scenario": "同一台机器上的真实多轮长上下文运行。",
    "hitrate": "真实的前缀缓存命中率测量。",
    "trace": "真实 trace 上的 KV 缓存预算扫描。",
    "agent": "真实的工具调用 Agent 运行。",
    "replay": "按 live 历史回放的录制会话。",
    "live-run": "实跑：解析后的配置、预检探针、进度与总体指标。",
    "live-hitrate": "hitrate 模式全流程。",
    "live-tables": "实跑后的汇总表与逐引擎指标。",
    "live-hitrate-tables": "hitrate 实跑的逐引擎命中率表。",
    "shell-safety": "shell 引号陷阱，以及裸指标名传到 ClawPerf 时的诊断。",
}


def sample_note(key: str, lang: str) -> str:
    return SAMPLE_NOTES_ZH[key] if lang == "zh" else SAMPLES_DATA["samples"][key]["note"]


# ── pages ────────────────────────────────────────────────────────────────────

def page_index(lang: str) -> str:
    L = lang
    mode_cards = [(m["icon"], f"**[{m['name']}]({page('modes/' + m['slug'], L)})**", m["tag"][L])
                  for m in MODES]
    first_run = "\n".join([
        "clawperf --mode scenario \\",
        "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\",
        "  --tokenizer /mnt/model/Qwen3-0.6B \\",
        "  --context-profile medium --num-users 8 --max-turns 20 \\",
        "  --metrics-endpoint http://localhost:8000/metrics \\",
        "  --output results.json",
    ])
    if L == "en":
        intro = ("Benchmark LLM serving under **real agent workloads** — multi-turn, long-context, "
                 "prefix-cache-heavy traffic. Seven modes, one CLI, built on "
                 "[EvalScope](https://github.com/modelscope/evalscope).")
        bullets = ["**7 modes** — each answers a different question; the cards below map them.",
                   "**4 backends** — vLLM · SGLang · MindIE · vllm-ascend, with per-backend metric mapping.",
                   "**amd64 + arm64** — native multi-arch images, plus a mock server so CI needs no GPU."]
        first, first_body = "First run", (
            "The default mode is `scenario`: N users holding independent conversations that grow turn "
            "by turn. Point `--tokenizer` at a local directory — it is loaded strictly offline.")
        pick, pick_body = "Pick the question you need answered", (
            "Every mode writes a JSON result plus a Markdown report with a verdict. Each one has its "
            "own page: why it exists, a diagram, the command, the parameters and a real run.")
        runner = "One runner, seven workloads"
        measured = "Measured, not claimed"
        measured_body = (f"From the end-to-end run in "
                         f"[docs/E2E_TEST_REPORT.md]({REPO}/blob/main/docs/E2E_TEST_REPORT.md): "
                         f"vLLM-Ascend v0.23.0, Qwen3-0.6B, one Ascend 910B3.")
        sweep = "A real SLO sweep on real hardware"
        quick, ref = "Quick start", "Full reference"
        stat_cards = [
            ("check-circle-outline", "**Hit rate is verifiable**",
             "**49.90%** measured against a **50.00%** target — 40 requests, 2 distinct prefixes, "
             "concurrency 4."),
            ("chart-line", "**Real traces reuse a lot**",
             "**90.42%** prefix-reuse ceiling over 34 real Claude Code requests; replay of the fitting "
             "requests succeeded **29/29**."),
            ("numeric", "**Capacity is a number**",
             "**5 users** sustained under `ttft.p99<=1500ms`, `tpot.avg<=30ms`, `e2e.max<=20s`."),
        ]
    else:
        intro = ("面向 **真实 Agent 负载**的 LLM 推理服务性能基准 —— 多轮对话、长上下文、前缀缓存密集的流量。"
                 "七种模式，一个 CLI，构建在 "
                 "[EvalScope](https://github.com/modelscope/evalscope) 之上。")
        bullets = ["**7 种模式** —— 每种回答一个不同的问题，见下方卡片。",
                   "**4 种后端** —— vLLM · SGLang · MindIE · vllm-ascend，指标映射按后端区分。",
                   "**amd64 + arm64** —— 原生双架构镜像，另带 mock server，CI 无需 GPU。"]
        first, first_body = "首次运行", (
            "默认模式是 `scenario`：N 个用户各自进行不断增长的多轮会话。把 `--tokenizer` 指向本地目录 —— "
            "它会严格离线加载。")
        pick, pick_body = "按你要回答的问题选模式", (
            "每种模式都会产出 JSON 结果与带结论的 Markdown 报告。每种模式一个页面：为什么做、示意图、命令、"
            "参数与一次真实运行。")
        runner = "一个 Runner，七种负载"
        measured = "实测数据，而非宣传"
        measured_body = (f"数据来自 "
                         f"[docs/E2E_TEST_REPORT.md]({REPO}/blob/main/docs/E2E_TEST_REPORT.md) "
                         f"的端到端测试：vLLM-Ascend v0.23.0 + Qwen3-0.6B，单张昇腾 910B3。")
        sweep = "一次真机 SLO 扫描"
        quick, ref = "快速开始", "完整参考"
        stat_cards = [
            ("check-circle-outline", "**命中率可验证**",
             "目标 **50.00%**，实测 **49.90%** —— 40 个请求、2 个不同前缀、并发 4。"),
            ("chart-line", "**真实 trace 复用率很高**",
             "34 个真实 Claude Code 请求的复用上限 **90.42%**；可容纳的请求回放 **29/29** 成功。"),
            ("numeric", "**容量是一个确定的数**",
             "在 `ttft.p99<=1500ms`、`tpot.avg<=30ms`、`e2e.max<=20s` 下可稳定支撑 **5 个用户**。"),
        ]

    return "\n".join([
        "# ClawPerf",
        "",
        intro,
        "",
        "\n".join(f"- {b}" for b in bullets),
        "",
        f"[{quick} :material-arrow-right:]({page('quickstart', L)}){{ .md-button .md-button--primary }} "
        f"[{ref} :material-book-open-variant:]({page('reference', L)}){{ .md-button }} "
        f"[GitHub :fontawesome-brands-github:]({REPO}){{ .md-button }}",
        "",
        f"## {first}",
        "",
        first_body,
        "",
        fence(first_run, "bash", "bash"),
        "",
        f"## {pick}",
        "",
        pick_body,
        "",
        cards(mode_cards),
        "",
        f"## {runner}",
        "",
        image("assets/pipeline.svg",
              "ClawPerf pipeline: the workload modes drive a runner that sends requests to a serving "
              "backend and polls its metrics"),
        "",
        f"## {measured}",
        "",
        measured_body,
        "",
        cards(stat_cards),
        "",
        f"### {sweep}",
        "",
        sample_note("slo", L),
        "",
        sample_block("slo"),
    ]) + "\n"


def page_quickstart(lang: str) -> str:
    L = lang
    if L == "en":
        title = "# From zero to a benchmark in one command"
        lead = ("The default mode is `scenario`: N users holding independent conversations that grow "
                "turn by turn. You need a running OpenAI-compatible endpoint and a tokenizer directory.")
        h_install, h_first, h_output, h_nogpu, h_exit = ("Install", "First run", "Reading the output",
                                                         "No GPU at hand?", "Exit codes")
        tokenizer_title = "Point --tokenizer at a local directory"
        run_note = ("**Point `--tokenizer` at a local directory.** It is loaded strictly offline (no "
                    "hub lookup, no download) and drives exact token counting, context clamping and "
                    "content generation. Use the same directory your server loaded the model from — or "
                    "the image's bundled `/app/tokenizers/qwen3-0.6b` to sanity-check the setup.")
        output_body = ("A live run against the bundled mock server (no GPU needed) — everything below "
                       "the banner uses the same code path as a real endpoint.")
        nums, artifacts = "The four numbers that matter", "Two artifacts per run"
        nums_body = ("**TTFT** — time to first token. **TPOT** — per output token. **E2E** — full "
                     "request latency. **Hit rate** — read from the server's Prometheus counters, never "
                     "inferred.")
        artifacts_body = ("`results.json` (config + per-user/per-turn detail + metrics) and `results.md` "
                          "(verdict, findings, ASCII charts). Regenerate the report with "
                          "`clawperf report results.json`.")
        mock_body = ("Ship the mock server instead: it has a real trie prefix cache and vLLM-style "
                     "`/metrics`, so every mode works end to end.")
        trouble = ("The full troubleshooting table — tokenizer paths, the SLO shell trap, the pre-flight "
                   "probe — lives in the [reference]({ref}#trouble).")
        nxt = "Next: the modes, in depth"
        exit_rows = [
            ["`0`", "the benchmark ran; results written"],
            ["`1`", "configuration or pre-flight error (no benchmark ran)"],
            ["`2`", "the benchmark ran but **every** request failed (CI gate)"],
            ["`3`", "interrupted (Ctrl+C); partial results are written"],
        ]
        headers = ["Code", "Meaning"]
    else:
        title = "# 一条命令跑起第一个基准"
        lead = ("默认模式是 `scenario`：N 个用户各自进行不断增长的多轮会话。只需要一个正在运行的 OpenAI 兼容端点"
                "和一个 tokenizer 目录。")
        h_install, h_first, h_output, h_nogpu, h_exit = ("安装", "首次运行", "怎么读输出",
                                                         "手边没有 GPU？", "退出码")
        tokenizer_title = "把 --tokenizer 指向本地目录"
        run_note = ("**把 `--tokenizer` 指向本地目录。**它会严格离线加载（不查 hub、不下载），并负责精确分词、"
                    "上下文裁剪与内容生成。指向服务端加载模型的同一个目录即可 —— 也可以先用镜像内置的 "
                    "`/app/tokenizers/qwen3-0.6b` 验证环境。")
        output_body = "以下是在内置 mock server 上的实跑（无需 GPU）—— 横幅以下走的是与真实端点完全相同的代码路径。"
        nums, artifacts = "四个关键数字", "每次运行两个产物"
        nums_body = ("**TTFT** —— 首 token 时延。**TPOT** —— 每输出 token。**E2E** —— 请求端到端时延。"
                     "**命中率** —— 直接读服务端 Prometheus 计数器，从不推断。")
        artifacts_body = ("`results.json`（配置 + 按用户/按轮明细 + 指标）与 `results.md`（结论、发现、"
                          "ASCII 图表）。可用 `clawperf report results.json` 重新生成报告。")
        mock_body = ("用内置 mock server 替代：它带真实的字典树前缀缓存与 vLLM 风格 `/metrics`，"
                     "所有模式都能跑通。")
        trouble = ("完整的故障排查表（tokenizer 路径、SLO 引号陷阱、预检探针）在"
                   "[完整参考]({ref}#trouble)里。")
        nxt = "下一步：模式详解"
        exit_rows = [
            ["`0`", "基准跑完并写出结果"],
            ["`1`", "配置或预检错误（未开始跑基准）"],
            ["`2`", "基准跑了但**全部**请求失败（CI 门禁）"],
            ["`3`", "被中断（Ctrl+C）；退出前会写出部分结果"],
        ]
        headers = ["退出码", "含义"]

    install = tabs([
        ("pip", fence('pip install "clawperf[agent,record,replay,mock-server]"', "bash")),
        ("container image", fence("docker pull ghcr.io/ucm-system/clawperf:latest", "bash")),
    ])
    first_run = "\n".join([
        "clawperf --mode scenario \\",
        "  --endpoint http://localhost:8000/v1 \\",
        "  --model Qwen3-0.6B \\",
        "  --tokenizer /mnt/model/Qwen3-0.6B \\",
        "  --context-profile medium \\",
        "  --num-users 8 --max-turns 20 \\",
        "  --metrics-endpoint http://localhost:8000/metrics \\",
        "  --output results.json",
    ])
    mock = "\n".join([
        "clawperf-mock-server --port 8000",
        "",
        "# the same command, now pointed at the mock",
        "clawperf --mode scenario --endpoint http://localhost:8000/v1 \\",
        "  --model qwen3-0.6b --tokenizer tokenizers/qwen3-0.6b \\",
        "  --context-profile fresh --num-users 4 --max-turns 4 \\",
        "  --metrics-endpoint http://localhost:8000/metrics --reset-cache",
    ])
    return "\n".join([
        title,
        "",
        lead,
        "",
        f"## {h_install}",
        "",
        install,
        "",
        f"## {h_first}",
        "",
        fence(first_run, "bash", "bash"),
        "",
        adm("note", run_note, tokenizer_title),
        "",
        f"## {h_output}",
        "",
        output_body,
        "",
        sample_block("live-run"),
        "",
        cards([("numeric", f"**{nums}**", nums_body),
               ("file-document-outline", f"**{artifacts}**", artifacts_body)]),
        "",
        f"## {h_nogpu}",
        "",
        mock_body,
        "",
        fence(mock, "bash", "bash"),
        "",
        f"## {h_exit}",
        "",
        table(headers, exit_rows),
        "",
        trouble.format(ref=page("reference", L)),
        "",
        sample_note("shell-safety", L),
        "",
        sample_block("shell-safety"),
        "",
        f"[{nxt} :material-arrow-right:]({page('modes/scenario', L)}){{ .md-button .md-button--primary }}",
    ]) + "\n"


def page_configuration(lang: str) -> str:
    L = lang
    if L == "en":
        title = "# The knobs you will actually touch"
        lead = ("Everything else — all parameters, their defaults and accepted values — is in the "
                "[reference]({ref}#params), generated from `clawperf --help`.")
        h_prof, h_suite, h_pace, h_metrics, h_layers = ("Context profiles", "Suites",
                                                        "Pacing & concurrency", "Metrics endpoints",
                                                        "Env vars & config file")
        prof_body = ("A profile sets the shared system prefix, the per-user prefix and the per-turn "
                     "input at once, so you do not have to invent token counts. Names are "
                     "case-insensitive.")
        prof_note = ("Raw counts still work: `--system-prefix-tokens`, `--user-prefix-tokens`, "
                     "`--input-tokens-per-turn`. A profile simply overrides all three.")
        suite_body = ("A suite runs several (users × profile) scenarios in sequence and writes one "
                      "result file per scenario. `--model-context-length` skips profiles that cannot "
                      "fit the model window.")
        pace_body = ("Four knobs that are easy to confuse. The distinction that matters: a closed loop "
                     "can never overload a server, an open loop can.")
        metrics_body = ("PD-disaggregated and multi-replica services expose one `/metrics` per "
                        "instance. Pass them all: counters are summed into a fleet-wide view, ratio "
                        "gauges averaged, and the per-engine table gains one row per instance.")
        metrics_note = ("Labels are optional (`name=url`; the default is host:port) and the flag is "
                        "repeatable or comma-separated. `--reset-cache` resets every instance.")
        layers_body = ("Precedence: **CLI > environment > YAML (`--config`) > defaults**. Every config "
                       "field has a `CLAWPERF_*` counterpart, upper-cased. An explicitly passed flag "
                       "always wins — even when its value equals the default.")
        engine_h = "Per-engine metric table from a live run"
        ctx_caption = ("How the context is built: shared system prefix, per-user prefix, growing "
                       "history and the newest input")
        arrival_caption = "Arrival patterns: burst, steady and Poisson session arrivals"
        headers = {"prof": ["Profile", "system prefix", "user prefix", "input / turn", "base context",
                            "rounded"],
                   "suite": ["Suite", "users", "profiles", "turns", "out/turn", "runs"],
                   "pace": ["Knob", "Controls", "Semantics"],
                   "env": ["Variable", "Equivalent to"]}
        pace_rows = [
            ["`--user-arrival`", "when each **session** joins",
             "users then run their turns back-to-back"],
            ["`--concurrency`", "**closed loop**: in-flight request cap",
             "the next request starts when one finishes — the server throttles the load"],
            ["`--request-rate`", "**open loop**: issue rate in req/s",
             "released on a Poisson schedule regardless of completions — this one **can** overload a "
             "server"],
            ["`--trace-users`", "session-level concurrency for trace replay",
             "turns inside one session stay ordered"],
        ]
        env_rows = [
            ["`CLAWPERF_ENDPOINT`", "`--endpoint`"],
            ["`CLAWPERF_MODEL`", "`--model`"],
            ["`CLAWPERF_API_KEY`", "`--api-key`"],
            ["`CLAWPERF_OUTPUT`", "`--output`"],
            ["`CLAWPERF_HISTORY`", "`--history` (`''` disables)"],
            ["`CLAWPERF_UPSTREAM_ENDPOINT`", "`--upstream-endpoint`"],
            ["`CLAWPERF_TOKENIZER_BACKEND`", "`transformers` | `modelscope`"],
            ["`CLAWPERF_<FIELD>`", "any field: `CLAWPERF_NUM_USERS`, `CLAWPERF_CONTEXT_PROFILE`, …"],
        ]
        yaml_title = "clawperf.yaml — CLI > env > YAML > defaults"
        precedence = "clawperf --config clawperf.yaml --num-users 16"
    else:
        title = "# 你真正会动的几个旋钮"
        lead = ("其余全部内容 —— 所有参数、默认值与可选值 —— 都在[完整参考]({ref}#params)里，"
                "由 `clawperf --help` 自动生成。")
        h_prof, h_suite, h_pace, h_metrics, h_layers = ("上下文档位", "套件", "节奏与并发", "指标端点",
                                                        "环境变量与配置文件")
        prof_body = ("一个档位同时设定共享系统前缀、每用户前缀与每轮输入三个数字，免去自己拼 token 数。"
                     "档位名大小写不敏感。")
        prof_note = ("也可以直接用原始数字：`--system-prefix-tokens`、`--user-prefix-tokens`、"
                     "`--input-tokens-per-turn`。档位只是把这三个一起覆盖掉。")
        suite_body = ("套件按序跑完（并发 × 档位）的笛卡尔积，每个场景各写一份结果文件。"
                      "`--model-context-length` 会跳过放不进模型窗口的档位。")
        pace_body = "四个容易混淆的旋钮。关键区别：闭环永远压不垮服务端，开环可以。"
        metrics_body = ("PD 分离与多副本服务每个实例各暴露一个 `/metrics`。全部传进来即可："
                        "计数器求和成全局视图、比率类指标取均值、逐引擎表按实例分行。")
        metrics_note = ("标签可选（`名称=url`，默认 host:port）；该参数可重复或用逗号分隔。"
                        "`--reset-cache` 会逐个重置所有实例。")
        layers_body = ("优先级：**CLI > 环境变量 > YAML（`--config`）> 默认值**。每个配置字段都有对应的"
                       "大写 `CLAWPERF_*` 变量。显式传入的 flag 永远优先 —— 即使取值恰好等于默认值。")
        engine_h = "实跑得到的逐引擎指标表"
        ctx_caption = "上下文如何构成：共享系统前缀、用户前缀、不断增长的历史与最新输入"
        arrival_caption = "三种会话到达形态：burst、steady 与 poisson"
        headers = {"prof": ["档位", "系统前缀", "用户前缀", "每轮输入", "基础上下文", "约"],
                   "suite": ["套件", "并发用户", "档位", "轮数", "每轮输出", "场景数"],
                   "pace": ["旋钮", "控制什么", "语义"],
                   "env": ["变量", "等价于"]}
        pace_rows = [
            ["`--user-arrival`", "每个**会话**何时加入", "加入后各自连续跑自己的轮次"],
            ["`--concurrency`", "**闭环**：在途请求上限", "上一个返回才发下一个 —— 节奏由服务端决定"],
            ["`--request-rate`", "**开环**：每秒发送速率",
             "按泊松过程发送，与是否完成无关 —— 只有它会真正压垮服务端"],
            ["`--trace-users`", "trace 回放的会话级并发", "同一会话内的轮次保持有序"],
        ]
        env_rows = [
            ["`CLAWPERF_ENDPOINT`", "`--endpoint`"],
            ["`CLAWPERF_MODEL`", "`--model`"],
            ["`CLAWPERF_API_KEY`", "`--api-key`"],
            ["`CLAWPERF_OUTPUT`", "`--output`"],
            ["`CLAWPERF_HISTORY`", "`--history`（`''` 表示禁用）"],
            ["`CLAWPERF_UPSTREAM_ENDPOINT`", "`--upstream-endpoint`"],
            ["`CLAWPERF_TOKENIZER_BACKEND`", "`transformers` | `modelscope`"],
            ["`CLAWPERF_<FIELD>`", "任意字段：`CLAWPERF_NUM_USERS`、`CLAWPERF_CONTEXT_PROFILE` 等"],
        ]
        yaml_title = "clawperf.yaml —— 优先级 CLI > 环境变量 > YAML > 默认值"
        precedence = "clawperf --config clawperf.yaml --num-users 16"

    suite_cmd = "\n".join([
        "clawperf --mode scenario --context-profile medium --num-users 8 ...",
        "",
        "# sweep profiles x users",
        "clawperf --mode scenario --suite full --model-context-length 32768 ...",
    ])
    metrics_cmd = "\n".join([
        "clawperf --mode scenario \\",
        "  --endpoint http://lb:9000/v1 --model Qwen3-0.6B \\",
        "  --tokenizer /mnt/model/Qwen3-0.6B \\",
        "  --metrics-endpoint prefill=http://10.0.0.1:9101/metrics \\",
        "  --metrics-endpoint decode=http://10.0.0.2:9102/metrics \\",
        "  --reset-cache",
    ])
    yaml_cmd = "\n".join([
        "mode: scenario",
        "endpoint: http://localhost:8000/v1",
        "model: Qwen3-0.6B",
        "tokenizer: /mnt/model/Qwen3-0.6B",
        "context_profile: medium",
        "num_users: 8",
        "max_turns: 20",
        'slo_constraints: ["ttft.p99<=1500", "tpot.avg<=30"]',
    ])
    return "\n".join([
        title,
        "",
        lead.format(ref=page("reference", L)),
        "",
        f"## {h_prof}",
        "",
        prof_body,
        "",
        table(headers["prof"], profiles_rows()),
        "",
        image("assets/context_model.svg", ctx_caption),
        "",
        adm("note", prof_note),
        "",
        f"## {h_suite}",
        "",
        suite_body,
        "",
        table(headers["suite"], suites_rows()),
        "",
        fence(suite_cmd, "bash", "bash"),
        "",
        f"## {h_pace}",
        "",
        pace_body,
        "",
        table(headers["pace"], pace_rows),
        "",
        image("assets/arrival_patterns.svg", arrival_caption),
        "",
        f"## {h_metrics}",
        "",
        metrics_body,
        "",
        fence(metrics_cmd, "bash", "bash"),
        "",
        adm("tip", metrics_note),
        "",
        f"### {engine_h}",
        "",
        sample_note("live-tables", L),
        "",
        sample_block("live-hitrate-tables"),
        "",
        f"## {h_layers}",
        "",
        layers_body,
        "",
        table(headers["env"], env_rows),
        "",
        fence(yaml_cmd, "yaml", yaml_title),
        "",
        fence(precedence, "bash", "bash"),
    ]) + "\n"


def page_mode(mode: dict, lang: str) -> str:
    L = lang
    slug = mode["slug"]
    if L == "en":
        h_why, h_how, h_params, h_out, h_read = ("Why this mode exists", "How to run it",
                                                 "Parameters that matter", "Real output",
                                                 "How to read it")
        full = "The full list, with defaults, is in the [reference]({ref}#params)."
        other = "Other modes"
        param_headers = ["Option", "What it does"]
    else:
        h_why, h_how, h_params, h_out, h_read = ("为什么做这个模式", "怎么用", "关键参数", "真实输出",
                                                 "怎么读结果")
        full = "完整参数列表（含默认值）见[完整参考]({ref}#params)。"
        other = "其他模式"
        param_headers = ["参数", "作用"]

    diagram, caps = mode["diagram"]
    rows = []
    for flag, en_body, zh_body in mode["params"]:
        rows.append([f"`{flag}`", en_body if L == "en" else zh_body])

    parts = [
        f"# {mode['name']}: {mode['tag'][L]}",
        "",
        f"## {h_why}",
        "",
        mode["why"][L],
        "",
        image(f"../{diagram}", caps[L]),
        "",
        f"## {h_how}",
        "",
        fence("\n".join(mode["command"]), "bash", "bash"),
        "",
    ]
    if mode.get("note"):
        parts += [adm("warning", mode["note"][L]), ""]
    parts += [
        f"## {h_params}",
        "",
        table(param_headers, rows),
        "",
        full.format(ref=page("reference", L, "../")),
        "",
        f"## {h_out}",
        "",
        sample_note(mode["sample"], L),
        "",
        sample_block(mode["sample"]),
    ]
    if mode.get("live_sample"):
        parts += ["", sample_note(mode["live_sample"], L), "", sample_block(mode["live_sample"])]
    parts += [
        "",
        f"## {h_read}",
        "",
        "\n".join(f"- {item}" for item in mode["read"][L]),
        "",
        "---",
        "",
        f"**{other}:** " + " · ".join(f"[{m['name']}]({page(m['slug'], L)})"
                                      for m in MODES if m["slug"] != slug),
    ]
    return "\n".join(parts) + "\n"


def page_reference(lang: str) -> str:
    L = lang
    i18n = json.loads(I18N.read_text(encoding="utf-8")) if I18N.is_file() else {}
    groups = collect_groups()
    by_title = {title: rows for title, rows in groups}
    global_groups = ["Mode", "Context Profiles & Suites", "User Configuration",
                     "Context Configuration", "Run Configuration", "API Configuration",
                     "System Metrics", "Output", "Configuration Files"]
    mode_groups = [("hitrate", "Hit-Rate Mode (only with --mode hitrate)"),
                   ("slo", "SLO Mode (only with --mode slo)"),
                   ("agent", "Agent Mode (only with --mode agent)"),
                   ("record", "Record Mode (only with --mode record)"),
                   ("replay", "Replay Mode (only with --mode replay)"),
                   ("trace", "Trace Mode (only with --mode trace)")]
    total = sum(len(rows) for _, rows in groups)
    flags = sum(len(r["opts"]) for _, rows in groups for r in rows)
    headers = ["Option", "Default", "Description"] if L == "en" else ["参数", "默认值", "说明"]

    blocks = []
    for title in global_groups:
        if title in by_title:
            blocks.append(f"### {title}\n\n" + table(headers, options_rows(by_title[title], L, i18n)))
    for mode_name, title in mode_groups:
        if title in by_title:
            blocks.append(f"#### {title} {{#opt-{mode_name}}}\n\n"
                          + table(headers, options_rows(by_title[title], L, i18n)))
    params_html = "\n\n".join(blocks)

    if L == "en":
        title = "# Every parameter, generated from the code"
        lead = (f"This page is generated from `clawperf --help` and the context-profile definitions, so "
                f"it cannot drift from the tool. **{total} parameters / {flags} flags.**")
        h_slo, h_params, h_exit, h_trouble = ("SLO constraint syntax", "All parameters",
                                              "Output & exit codes", "Troubleshooting")
        slo_body = ("The constraint is `<metric>.<agg><sep><ms>` — repeat `--slo` to AND several "
                    "constraints together.")
        slo_rows = [
            ["`ttft.p99:1500`", "`ttft.p99 <= 1500ms`", "shell-safe (no quoting needed)"],
            ["`tpot.avg=30`", "`tpot.avg <= 30ms`", "shell-safe (no quoting needed)"],
            ["`'ttft.p99<=1500'`", "`ttft.p99 <= 1500ms`", "must be quoted in bash/zsh"],
            ["`ttft.p99:ge:1500`", "`ttft.p99 >= 1500ms`", "the only shell-safe way to write `>=`"],
            ["`'a<=1,b<=2'`", "both constraints", "one quoted argument, several constraints"],
        ]
        slo_note = ("In a shell, quote `<=` or use a separator without `<` / `>`, because those "
                    "characters are redirections.")
        metrics_line = ("**Metrics** — `ttft` (time to first token), `tpot` (time per output token), "
                        "`e2e` (end-to-end latency).")
        agg_line = ("**Aggregates** — `avg`, `min`, `max`, and any percentile "
                    "`p25 p50 p75 p90 p95 p99 p99.9`. Several constraints AND together; the sweep "
                    "stops at the first level that breaks any of them.")
        params_body = ("Every option, its default and its accepted values. Mode-specific groups are "
                       "listed after the shared ones.")
        exit_rows = [
            ["`0`", "the benchmark ran; results written"],
            ["`1`", "configuration or pre-flight error (no benchmark ran)"],
            ["`2`", "the benchmark ran but **every** request failed (CI gate)"],
            ["`3`", "interrupted (Ctrl+C); partial results are written"],
        ]
        artifact_line = ("Every run writes a JSON result plus a Markdown report next to it. "
                         "`clawperf report results.json` regenerates the report from any result, and "
                         "`clawperf compare a.json b.json` diffs two runs.")
        trouble_rows = [
            ["`bash: =10000: No such file or directory`",
             "the shell ate the `<` in `--slo ttft.p99<=10000`. Use `--slo ttft.p99:10000` or quote the "
             "spec."],
            ["`Tokenizer path '...' does not exist`",
             "the path is not visible inside the container — the error lists the parent directory; "
             "mount it with `-v /mnt/model:/mnt/model:ro`."],
            ["`Pre-flight: ... Connection reset by peer`",
             "the server reset the tiny probe (often while still loading weights). Transient errors are "
             "retried 3× with backoff; add `--no-preflight` to skip the probe."],
            ["`UnicodeEncodeError` on Windows",
             "the CLI already forces UTF-8 stdio; if a third-party tool still fails, set "
             "`PYTHONIOENCODING=utf-8`."],
        ]
        more = (f"More detail (including tokenizer backend selection) is in the "
                f"[README]({REPO}#troubleshooting) and the "
                f"[E2E test report]({page('E2E_TEST_REPORT', L)}).")
    else:
        title = "# 全部参数，由代码自动生成"
        lead = (f"本页由 `clawperf --help` 与上下文档位定义自动生成，不会与工具脱节。"
                f"共 **{total} 个参数 / {flags} 个 flag。**")
        h_slo, h_params, h_exit, h_trouble = ("SLO 约束语法", "全部参数", "产物与退出码", "故障排查")
        slo_body = "约束写法是 `<指标>.<统计量><分隔符><毫秒>` —— 重复 `--slo` 可「与」多个约束。"
        slo_rows = [
            ["`ttft.p99:1500`", "`ttft.p99 <= 1500ms`", "免引号"],
            ["`tpot.avg=30`", "`tpot.avg <= 30ms`", "免引号"],
            ["`'ttft.p99<=1500'`", "`ttft.p99 <= 1500ms`", "在 bash/zsh 中必须加引号"],
            ["`ttft.p99:ge:1500`", "`ttft.p99 >= 1500ms`", "唯一免引号的 `>=` 写法"],
            ["`'a<=1,b<=2'`", "两条约束", "一个引号参数写多条约束"],
        ]
        slo_note = "在 shell 中要么给 `<=` 加引号，要么改用不含 `<` / `>` 的分隔符，因为它们是重定向符号。"
        metrics_line = "**指标** —— `ttft`（首 token 时延）、`tpot`（每输出 token 时延）、`e2e`（端到端时延）。"
        agg_line = ("**统计量** —— `avg`、`min`、`max`，以及任意分位 `p25 p50 p75 p90 p95 p99 p99.9`。"
                    "多条约束为「与」关系；一旦某一级打破了任意一条，扫描即在此停止。")
        params_body = "每个参数、默认值与可选值。各模式专属参数列在通用参数之后。"
        exit_rows = [
            ["`0`", "基准跑完并写出结果"],
            ["`1`", "配置或预检错误（未开始跑基准）"],
            ["`2`", "基准跑了但**全部**请求失败（CI 门禁）"],
            ["`3`", "被中断（Ctrl+C）；退出前会写出部分结果"],
        ]
        artifact_line = ("每次运行都会写一份 JSON 结果与旁边的 Markdown 报告。"
                         "`clawperf report results.json` 可从任意结果重新生成报告，"
                         "`clawperf compare a.json b.json` 可对比两次运行。")
        trouble_rows = [
            ["`bash: =10000: No such file or directory`",
             "shell 吃掉了 `--slo ttft.p99<=10000` 中的 `<`。改用 `--slo ttft.p99:10000`，"
             "或给参数加引号。"],
            ["`Tokenizer path '...' does not exist`",
             "容器内看不到该路径 —— 报错会列出父目录内容；用 `-v /mnt/model:/mnt/model:ro` 挂载。"],
            ["`Pre-flight: ... Connection reset by peer`",
             "服务端重置了这个极小探针（常见于仍在加载权重）。传输类错误会自动退避重试 3 次；"
             "加 `--no-preflight` 可完全跳过探针。"],
            ["`UnicodeEncodeError` on Windows",
             "CLI 已强制 UTF-8 stdio；若第三方工具仍报错，设置 `PYTHONIOENCODING=utf-8`。"],
        ]
        more = (f"更多细节（含 tokenizer 后端选择）见 [README]({REPO}#troubleshooting) 与 "
                f"[端到端测试报告]({page('E2E_TEST_REPORT', L)})。")

    return "\n".join([
        title,
        "",
        lead,
        "",
        f"## {h_slo}",
        "",
        slo_body,
        "",
        table(["Write", "Means", "Notes"] if L == "en" else ["写法", "含义", "说明"], slo_rows),
        "",
        adm("warning", slo_note),
        "",
        metrics_line,
        "",
        agg_line,
        "",
        sample_note("shell-safety", L),
        "",
        sample_block("shell-safety"),
        "",
        f"## {h_params} {{#params}}",
        "",
        params_body,
        "",
        params_html,
        "",
        f"## {h_exit}",
        "",
        table(["Code", "Meaning"] if L == "en" else ["退出码", "含义"], exit_rows),
        "",
        artifact_line,
        "",
        f"## {h_trouble} {{#trouble}}",
        "",
        table(["Symptom", "Fix"] if L == "en" else ["现象", "解决"], trouble_rows),
        "",
        more,
    ]) + "\n"


# ── driver ───────────────────────────────────────────────────────────────────

SAMPLES_DATA: dict = {}

DESCRIPTIONS = {
    "index": {"en": "ClawPerf benchmarks LLM serving under real agent workloads: seven modes, one CLI.",
              "zh": "ClawPerf —— 面向真实 Agent 负载的 LLM 推理服务性能基准，七种模式，一个 CLI。"},
    "quickstart": {"en": "Install ClawPerf, run the default scenario mode and read the output.",
                   "zh": "安装 ClawPerf、跑起默认的 scenario 模式，并读懂输出。"},
    "configuration": {"en": "Context profiles, suites, pacing knobs and metrics endpoints.",
                      "zh": "上下文档位、套件、施压旋钮与指标端点。"},
    "reference": {"en": "Every ClawPerf parameter, generated from clawperf --help.",
                  "zh": "ClawPerf 全部参数，由 clawperf --help 自动生成。"},
}


def build_pages() -> dict:
    """rel path -> file contents, for every page in every language."""
    out = {}
    for lang in LANGS:
        for name, maker in (("index", page_index), ("quickstart", page_quickstart),
                            ("configuration", page_configuration), ("reference", page_reference)):
            out[f"{name}.{lang}.md"] = (f"---\ndescription: {DESCRIPTIONS[name][lang]}\n---\n\n"
                                        f"{maker(lang)}")
        for mode in MODES:
            desc = f"{mode['tag'][lang]} — ClawPerf {mode['name']} mode."
            out[f"modes/{mode['slug']}.{lang}.md"] = (
                f"---\ndescription: {desc}\n---\n\n{page_mode(mode, lang)}")
    return out


def main(argv: list[str]) -> int:
    global SAMPLES_DATA
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if any page is out of date")
    args = ap.parse_args(argv[1:])

    SAMPLES_DATA = json.loads(SAMPLES.read_text(encoding="utf-8"))
    pages = build_pages()

    if args.check:
        stale = [rel for rel, text in pages.items()
                 if not (DOCS / rel).is_file()
                 or (DOCS / rel).read_text(encoding="utf-8") != text]
        if stale:
            print("FAIL: out of date — run python scripts/gen_site.py: " + ", ".join(stale))
            return 1
        print(f"site sources up to date ({len(pages)} files)")
        return 0

    for rel, text in pages.items():
        path = DOCS / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"  {rel:34s} {len(text):>7,} bytes")
    print(f"wrote {len(pages)} Markdown files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
