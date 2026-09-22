#!/usr/bin/env python3
"""Generate the whole docs site from one place.

Pages (all sharing the same shell, sidebar and theme):

  index.html                 what ClawPerf is, the mode map, where to go next
  quickstart.html            install, first run, how to read the output
  modes/scenario.html        \
  modes/hitrate.html          |
  modes/slo.html              |  one page per mode: why it exists, a diagram,
  modes/agent.html            |  the command, the parameters, a real captured
  modes/trace.html            |  run, and how to read it
  modes/record-replay.html   /
  configuration.html         profiles, suites, pacing, metrics, env & config
  reference.html             every parameter, SLO syntax, exit codes

Sources of truth:
  * parameters  -> clawperf.cli.build_parser()   (never drifts from --help)
  * profiles    -> clawperf.context_profiles     (the real numbers)
  * output      -> docs/samples.json             (captured by gen_samples.py)
  * prose       -> this file (bilingual)

Quoting convention: HTML attributes inside Python strings are single-quoted
(class='inline'), so Python string literals never need a backslash escape.

Usage:
  python scripts/gen_site.py            # write every page
  python scripts/gen_site.py --check    # fail if any page is out of date
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
SAMPLES = DOCS / "samples.json"
I18N = DOCS / "i18n" / "params_zh.json"
REPO = "https://github.com/ucm-system/ClawPerf"
SITE = "https://ucm-system.github.io/ClawPerf"


# ── helpers ──────────────────────────────────────────────────────────────────

def e(text) -> str:
    return html.escape(str(text), quote=False)


def en(s: str) -> str:
    return f"<span class='en'>{s}</span>"


def zh(s: str) -> str:
    return f"<span class='zh'>{s}</span>"


def both(en_text: str, zh_text: str) -> str:
    return en(en_text) + zh(zh_text)


def code(text: str) -> str:
    return f"<code class='inline'>{e(text)}</code>"


def fig(src: str, alt: str, cap_en: str, cap_zh: str) -> str:
    return (
        "<figure class='diagram'>\n"
        f"  <img loading='lazy' src='{src}' alt='{e(alt)}'>\n"
        f"  <figcaption>{both(cap_en, cap_zh)}</figcaption>\n"
        "</figure>"
    )


# ── highlighting for captured output ─────────────────────────────────────────

LINE_CLASSES = [
    (re.compile(r"^\$ "), "cmd"),
    (re.compile(r"^INFO:"), "log"),
    (re.compile(r"^(WARNING|Traceback)"), "warn"),
    (re.compile(r"^\[ClawPerf\]"), "warn"),
    (re.compile(r"(✅|\bPASS\b|\bGOOD\b)"), "ok"),
    (re.compile(r"(❌|\bFAIL\b|\bPOOR\b|error|Error)"), "err"),
    (re.compile(r"^(\||\+[-+]+\+)"), "rule"),
    (re.compile(r"^(#|##)"), "head"),
]


def highlight_terminal(text: str) -> str:
    out = []
    for line in text.split("\n"):
        cls = next((name for pattern, name in LINE_CLASSES if pattern.search(line)), "")
        body = e(line)
        out.append(f"<span class='{cls}'>{body}</span>" if cls else body)
    return "\n".join(out)


def highlight_command(text: str) -> str:
    parts = []
    for token in re.split(r"(\s+)", text):
        if token.startswith("--"):
            parts.append(f"<span class='flag'>{e(token)}</span>")
        elif token.startswith("#"):
            parts.append(f"<span class='cmt'>{e(token)}</span>")
        else:
            parts.append(e(token))
    return "".join(parts)


def sample_block(key: str, head: str | None = None) -> str:
    """A themed, copyable code block holding real captured output."""
    data = SAMPLES_DATA["samples"][key]
    title = head if head is not None else f"$ {data['command']}"
    return (
        "<div class='sample'>\n"
        f"  <div class='sample-head'><span class='sample-title'>{highlight_command(title)}</span>"
        "<button class='copy' type='button' data-copy>Copy</button></div>\n"
        f"  <pre><code>{highlight_terminal(data['output'])}</code></pre>\n"
        "</div>"
    )


def command_block(text: str, label: str = "bash") -> str:
    return (
        "<div class='sample'>\n"
        f"  <div class='sample-head'><span class='sample-title'>{e(label)}</span>"
        "<button class='copy' type='button' data-copy>Copy</button></div>\n"
        f"  <pre><code>{highlight_command(text)}</code></pre>\n"
        "</div>"
    )


# ── shared shell ─────────────────────────────────────────────────────────────

MODE_NAV = [
    ("modes/scenario.html", "scenario"),
    ("modes/hitrate.html", "hitrate"),
    ("modes/slo.html", "slo"),
    ("modes/agent.html", "agent"),
    ("modes/trace.html", "trace"),
    ("modes/record-replay.html", "record &amp; replay"),
]

CSS = """
  :root {
    --bg: #ffffff; --bg-soft: #f8fafc; --card: #ffffff; --border: #e2e8f0;
    --text: #0f172a; --text-soft: #475569; --text-muted: #64748b;
    --accent: #0284c7; --accent-soft: #e0f2fe; --green: #15803d; --green-soft: #dcfce7;
    --amber: #b45309; --amber-soft: #fef3c7; --red: #b91c1c; --red-soft: #fee2e2;
    --code-bg: #0d1524; --code-head: #16233c; --code-text: #dbe6f5;
    --shadow: 0 1px 2px rgba(15, 23, 42, .06), 0 8px 24px rgba(15, 23, 42, .06);
  }
  html[data-theme="dark"] {
    --bg: #0b1220; --bg-soft: #0f172a; --card: #111c33; --border: #1e293b;
    --text: #e8eef8; --text-soft: #b6c2d4; --text-muted: #8b9ab1;
    --accent: #38bdf8; --accent-soft: #0b2942; --green: #4ade80; --green-soft: #0d2a1c;
    --amber: #fbbf24; --amber-soft: #33260a; --red: #f87171; --red-soft: #3b1414;
    --code-bg: #060b16; --code-head: #0e1a2e; --code-text: #dbe6f5;
    --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 10px 30px rgba(0, 0, 0, .35);
  }
  @media (prefers-color-scheme: dark) {
    html[data-theme="auto"] {
      --bg: #0b1220; --bg-soft: #0f172a; --card: #111c33; --border: #1e293b;
      --text: #e8eef8; --text-soft: #b6c2d4; --text-muted: #8b9ab1;
      --accent: #38bdf8; --accent-soft: #0b2942; --green: #4ade80; --green-soft: #0d2a1c;
      --amber: #fbbf24; --amber-soft: #33260a; --red: #f87171; --red-soft: #3b1414;
      --code-bg: #060b16; --code-head: #0e1a2e; --code-text: #dbe6f5;
      --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 10px 30px rgba(0, 0, 0, .35);
    }
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; scroll-padding-top: 84px; }
  body {
    margin: 0; background: var(--bg); color: var(--text); font-size: 16px; line-height: 1.7;
    font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', -apple-system,
                 BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 0 20px; }
  html[data-lang="en"] .zh { display: none; }
  html[data-lang="zh"] .en { display: none; }
  html[data-lang="zh"] body { line-height: 1.85; }

  header.top {
    position: sticky; top: 0; z-index: 20; background: var(--bg);
    background: color-mix(in srgb, var(--bg) 90%, transparent);
    backdrop-filter: blur(8px); border-bottom: 1px solid var(--border);
  }
  .top-inner { display: flex; align-items: center; gap: 18px; padding: 13px 0; }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 17px; color: var(--text); }
  .brand:hover { text-decoration: none; }
  nav.toplinks { display: flex; gap: 18px; margin-left: auto; flex-wrap: wrap; }
  nav.toplinks a { color: var(--text-soft); font-size: 14.5px; }
  nav.toplinks a:hover { color: var(--accent); }
  .toggles { display: flex; gap: 8px; }
  button.toggle {
    font: inherit; font-size: 13px; color: var(--text-soft); background: var(--bg-soft);
    border: 1px solid var(--border); border-radius: 8px; padding: 5px 10px; cursor: pointer;
  }
  button.toggle:hover { border-color: var(--accent); color: var(--accent); }

  /* two-column layout: sticky index + content */
  .layout { display: grid; grid-template-columns: 268px minmax(0, 1fr); gap: 48px;
            max-width: 1320px; margin: 0 auto; padding: 32px 20px 0; align-items: start; }
  .layout > main { min-width: 0; }
  details.toc {
    position: sticky; top: 84px; max-height: calc(100vh - 108px); overflow-y: auto;
    padding: 14px 14px 14px 16px; background: var(--bg-soft);
    border: 1px solid var(--border); border-radius: 14px; font-size: 14.5px;
  }
  details.toc > summary { display: none; cursor: pointer; font-weight: 700; color: var(--text); list-style: none; }
  details.toc > summary::-webkit-details-marker { display: none; }
  details.toc > summary::after { content: " \\25BE"; color: var(--text-muted); }
  nav.toc-nav { display: grid; gap: 2px; }
  nav.toc-nav a { display: block; color: var(--text-soft); padding: 5px 10px; border-radius: 8px;
                  border-left: 2px solid transparent; line-height: 1.45; }
  nav.toc-nav a:hover { color: var(--accent); background: var(--bg); text-decoration: none; }
  nav.toc-nav a.active { color: var(--accent); background: var(--bg); border-left-color: var(--accent); font-weight: 600; }
  nav.toc-nav a.lvl1 { font-weight: 600; color: var(--text); margin-top: 5px; }
  nav.toc-nav a.lvl2 { padding-left: 22px; font-size: 13.5px; }
  nav.toc-nav a.lvl3 { padding-left: 36px; font-size: 13px; color: var(--text-muted); }
  nav.toc-nav .num { color: var(--text-muted); font-variant-numeric: tabular-nums; margin-right: 7px; font-weight: 600; }
  nav.toc-nav .group { display: block; font-weight: 600; color: var(--text); padding: 6px 10px 2px; font-size: 14.5px; }
  nav.toc-nav a.lvl1.active .num, nav.toc-nav a.lvl1:hover .num { color: var(--accent); }
  nav.toc-nav .sep { height: 1px; background: var(--border); margin: 8px 0; }

  h1 { font-size: clamp(32px, 5vw, 46px); line-height: 1.15; letter-spacing: -.025em; margin: 8px 0 14px; }
  h2 { font-size: clamp(24px, 3vw, 31px); line-height: 1.25; letter-spacing: -.02em; margin: 44px 0 10px; }
  h2:first-child { margin-top: 0; }
  h3 { font-size: 20px; margin: 30px 0 8px; letter-spacing: -.01em; }
  h4.mode-params { font-size: 16px; margin: 26px 0 6px; color: var(--text-soft); }
  .eyebrow { font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
             color: var(--accent); margin: 0 0 8px; }
  .lead { font-size: clamp(17px, 2.2vw, 20px); color: var(--text-soft); max-width: 780px; margin: 0 0 22px; }
  p.sub { font-size: 16.5px; color: var(--text-soft); margin: 0 0 18px; max-width: 830px; }
  .why { font-size: 16.5px; color: var(--text-soft); margin: 0 0 18px; max-width: 860px; }
  .label { display: block; font-size: 13px; font-weight: 700; letter-spacing: .08em;
           text-transform: uppercase; color: var(--text-muted); margin: 26px 0 10px; }
  ul.tight { margin: 0 0 16px; padding-left: 22px; color: var(--text-soft); }
  ul.tight li { margin-bottom: 7px; }

  .grid { display: grid; gap: 16px; }
  .grid.c2 { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
  .grid.c3 { grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 14px;
          padding: 18px 20px; box-shadow: var(--shadow); }
  .card h3 { margin: 0 0 8px; font-size: 17px; }
  .card p { margin: 0 0 8px; color: var(--text-soft); font-size: 15px; }
  .card p:last-child { margin-bottom: 0; }
  .card .tag { display: inline-block; font-size: 12px; color: var(--accent);
               background: var(--accent-soft); border-radius: 999px; padding: 2px 10px; margin-bottom: 10px; }
  a.card-link { display: block; color: var(--text); }
  a.card-link:hover { text-decoration: none; border-color: var(--accent); }
  a.card-link b { display: block; font-size: 17px; margin-bottom: 6px; }
  a.card-link span { font-size: 14.5px; color: var(--text-muted); }
  a.card-link code { color: var(--accent); font-size: 16px; }

  /* code blocks */
  .sample { margin: 0 0 18px; border: 1px solid var(--border); border-radius: 14px;
            overflow: hidden; box-shadow: var(--shadow); }
  .sample-head {
    display: flex; align-items: center; gap: 12px; padding: 9px 12px 9px 16px;
    background: var(--code-head); border-bottom: 1px solid var(--border);
  }
  .sample-title {
    flex: 1; min-width: 0; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12.5px; color: #93a4bd; white-space: pre-wrap; word-break: break-word;
  }
  button.copy {
    flex: none; font: inherit; font-size: 12px; color: #b6c2d4; background: transparent;
    border: 1px solid #33455f; border-radius: 7px; padding: 3px 10px; cursor: pointer;
  }
  button.copy:hover { color: #fff; border-color: #64748b; }
  .sample pre {
    margin: 0; padding: 16px 18px; background: var(--code-bg); color: var(--code-text);
    overflow-x: auto; font-size: 13px; line-height: 1.6;
  }
  .sample pre code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; }
  pre .cmd { color: #86efac; }
  pre .log { color: #7dd3fc; }
  pre .warn { color: #fbbf24; }
  pre .ok { color: #4ade80; }
  pre .err { color: #f87171; }
  pre .rule { color: #64748b; }
  pre .head { color: #c4b5fd; }
  pre .flag { color: #7dd3fc; }
  pre .cmt { color: #64748b; }
  code.inline { background: var(--bg-soft); border: 1px solid var(--border); border-radius: 6px;
                padding: 1px 6px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
                font-size: 13.5px; }

  table { width: 100%; border-collapse: collapse; font-size: 15px; }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { color: var(--text-muted); font-weight: 600; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; }
  tbody tr:last-child td { border-bottom: none; }
  .tbl-scroll { overflow-x: auto; border: 1px solid var(--border); border-radius: 14px;
                background: var(--card); box-shadow: var(--shadow); margin-bottom: 16px; }
  table.kv td:first-child { white-space: nowrap; }
  table.kv code { font-weight: 600; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }

  .note { font-size: 15px; color: var(--text-soft); background: var(--bg-soft);
          border: 1px solid var(--border); border-left: 3px solid var(--accent);
          border-radius: 10px; padding: 14px 16px; margin: 0 0 18px; }
  figure.diagram { margin: 24px 0; }
  figure.diagram img { display: block; width: 100%; max-width: 820px; height: auto; margin: 0 auto;
                       background: #fff; border: 1px solid var(--border); border-radius: 14px; padding: 14px; }
  figcaption { color: var(--text-muted); font-size: 13.5px; margin-top: 10px; max-width: 820px; }

  .pill { display: inline-block; font-size: 13.5px; border: 1px solid var(--border); background: var(--bg-soft);
          border-radius: 999px; padding: 4px 12px; margin: 0 6px 6px 0; color: var(--text-soft); }
  .pill:hover { border-color: var(--accent); color: var(--accent); text-decoration: none; }
  .next { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 28px 0 0; }
  .btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 16px; border-radius: 10px;
         font-size: 14.5px; font-weight: 600; border: 1px solid var(--border);
         background: var(--card); color: var(--text); }
  .btn:hover { text-decoration: none; border-color: var(--accent); }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  footer { border-top: 1px solid var(--border); margin-top: 52px; padding: 30px 0 56px;
           color: var(--text-muted); font-size: 14.5px; }
  footer .cols { display: flex; flex-wrap: wrap; gap: 32px; max-width: 1320px; margin: 0 auto; padding: 0 20px; }
  footer h4 { margin: 0 0 8px; font-size: 13px; color: var(--text-soft); text-transform: uppercase; letter-spacing: .04em; }
  footer ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 5px; }
  footer .fine { max-width: 1320px; margin: 24px auto 0; padding: 0 20px; }

  @media (max-width: 1100px) {
    .layout { grid-template-columns: 1fr; gap: 0; padding-top: 20px; }
    details.toc { position: static; max-height: none; margin-bottom: 24px; }
    details.toc > summary { display: block; }
  }
  @media (max-width: 780px) { nav.toplinks { display: none; } }
"""

JS = """
(function () {
  var root = document.documentElement;
  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };

  var savedTheme = store.get('clawperf-theme');
  var mq = window.matchMedia('(prefers-color-scheme: dark)');
  function applyTheme() {
    var t = root.getAttribute('data-theme');
    var dark = t === 'dark' || (t === 'auto' && mq.matches);
    root.setAttribute('data-theme', dark ? 'dark' : 'light');
    root.setAttribute('data-theme-choice', t);
  }
  root.setAttribute('data-theme', savedTheme || 'auto');
  applyTheme();
  if (mq.addEventListener) { mq.addEventListener('change', function () { if (root.getAttribute('data-theme-choice') === 'auto') applyTheme(); }); }

  var savedLang = store.get('clawperf-lang');
  var lang = savedLang || ((navigator.language || '').toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en');
  function applyLang() {
    root.setAttribute('data-lang', lang);
    root.setAttribute('lang', lang === 'zh' ? 'zh-CN' : 'en');
    var btn = document.getElementById('lang-btn');
    if (btn) { btn.textContent = lang === 'zh' ? 'English' : '中文'; }
  }
  applyLang();
  document.getElementById('lang-btn').addEventListener('click', function () {
    lang = lang === 'zh' ? 'en' : 'zh';
    store.set('clawperf-lang', lang);
    applyLang();
  });
  document.getElementById('theme-btn').addEventListener('click', function () {
    var cur = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    store.set('clawperf-theme', cur);
    root.setAttribute('data-theme', cur);
    root.setAttribute('data-theme-choice', cur);
    applyTheme();
  });

  // copy buttons on the captured-output blocks
  document.querySelectorAll('button.copy').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var pre = btn.closest('.sample').querySelector('pre');
      var text = pre ? pre.innerText : '';
      var done = function () {
        var old = btn.textContent;
        btn.textContent = root.getAttribute('data-lang') === 'zh' ? '已复制' : 'Copied';
        setTimeout(function () { btn.textContent = old; }, 1200);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, done);
      } else {
        var r = document.createRange(); r.selectNode(pre);
        window.getSelection().removeAllRanges(); window.getSelection().addRange(r);
        try { document.execCommand('copy'); } catch (err) {}
        window.getSelection().removeAllRanges(); done();
      }
    });
  });

  // left index: always open on wide screens, a disclosure on narrow ones
  var toc = document.getElementById('toc');
  if (toc) {
    var wide = window.matchMedia('(min-width: 1101px)');
    function syncToc() { if (wide.matches) { toc.open = true; } }
    syncToc();
    if (wide.addEventListener) { wide.addEventListener('change', syncToc); }

    var links = Array.prototype.slice.call(toc.querySelectorAll('a[href^="#"]'));
    var targets = links.map(function (a) {
      return document.getElementById(a.getAttribute('href').slice(1));
    }).filter(Boolean);
    if ('IntersectionObserver' in window && targets.length) {
      var visible = {};
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (ev) {
          visible[ev.target.id] = ev.isIntersecting ? ev.intersectionRatio : 0;
        });
        var best = null;
        Object.keys(visible).forEach(function (id) {
          if (visible[id] > 0 && (!best || visible[id] > visible[best])) { best = id; }
        });
        if (best) {
          links.forEach(function (a) {
            a.classList.toggle('active', a.getAttribute('href') === '#' + best);
          });
        }
      }, { rootMargin: '-84px 0px -55% 0px', threshold: [0, 0.15, 0.4, 0.75, 1] });
      targets.forEach(function (t) { observer.observe(t); });
    }
    toc.addEventListener('click', function (ev) {
      if (ev.target.closest && ev.target.closest('a') && !wide.matches) { toc.open = false; }
    });
  }
})();
"""

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='7' fill='%230f172a'/%3E%3Cg fill='%2338bdf8'%3E"
           "%3Crect x='7' y='17' width='4' height='8' rx='1'/%3E%3Crect x='14' y='12' width='4' height='13' rx='1'/%3E"
           "%3Crect x='21' y='7' width='4' height='18' rx='1'/%3E%3C/g%3E%3C/svg%3E")


def sidebar(current: str, sections: list, p: str) -> str:
    rows = []

    def link(href: str, en_t: str, zh_t: str, cls: str, num: str = "") -> str:
        badge = f"<span class='num'>{num}</span>" if num else ""
        return (f"<a class='{cls}' href='{href}'>{badge}"
                f"<span class='en'>{en_t}</span><span class='zh'>{zh_t}</span></a>")

    rows.append(link(f"{p}index.html", "Overview", "总览", "lvl1", "1"))
    rows.append(link(f"{p}quickstart.html", "Quick start", "快速开始", "lvl1", "2"))
    rows.append("<span class='group'><span class='num'>3</span>"
                "<span class='en'>Modes</span><span class='zh'>模式</span></span>")
    for href, name in MODE_NAV:
        rows.append(link(f"{p}{href}", name, name, "lvl3 active" if href == current else "lvl2"))
    rows.append(link(f"{p}configuration.html", "Configuration", "配置", "lvl1", "4"))
    rows.append(link(f"{p}reference.html", "Reference", "完整参考", "lvl1", "5"))
    if sections:
        rows.append("<div class='sep'></div>")
        rows.append(f"<a class='lvl2' href='#{sections[0][0]}'>"
                    "<span class='en'>On this page</span><span class='zh'>本页目录</span></a>")
        for sid, en_t, zh_t in sections:
            rows.append(link(f"#{sid}", en_t, zh_t, "lvl3"))
    rows.append("<div class='sep'></div>")
    rows.append(link(REPO, "GitHub", "GitHub", "lvl2"))
    rows.append(link(f"{p}reference.html#params", "All parameters", "全部参数", "lvl2"))
    rows.append(link(f"{p}reference.html#trouble", "Troubleshooting", "故障排查", "lvl2"))
    return "\n".join(rows)


def shell(current: str, title: str, body: str, sections: list, description: str) -> str:
    canonical = SITE + "/" if current == "index.html" else f"{SITE}/{current}"
    p = "../" if current.startswith("modes/") else ""
    return f"""<!DOCTYPE html>
<html lang='en' data-lang='en' data-theme='auto'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{e(title)} — ClawPerf</title>
<meta name='description' content='{e(description)}'>
<link rel='canonical' href='{canonical}'>
<meta property='og:type' content='website'>
<meta property='og:title' content='{e(title)} — ClawPerf'>
<meta property='og:description' content='{e(description)}'>
<meta property='og:url' content='{canonical}'>
<meta name='theme-color' content='#0f172a'>
<link rel='icon' href='{FAVICON}'>
<style>{CSS}</style>
</head>
<body>

<header class='top'>
  <div class='wrap top-inner'>
    <a class='brand' href='{p}index.html'>
      <svg width='24' height='24' viewBox='0 0 32 32' aria-hidden='true'>
        <rect width='32' height='32' rx='7' fill='#0f172a'/>
        <g fill='#38bdf8'>
          <rect x='7' y='17' width='4' height='8' rx='1'/>
          <rect x='14' y='12' width='4' height='13' rx='1'/>
          <rect x='21' y='7' width='4' height='18' rx='1'/>
        </g>
      </svg>
      ClawPerf
    </a>
    <nav class='toplinks'>
      <a href='{p}quickstart.html'>{both("Quick start", "快速开始")}</a>
      <a href='{p}modes/scenario.html'>{both("Modes", "模式")}</a>
      <a href='{p}configuration.html'>{both("Configuration", "配置")}</a>
      <a href='{p}reference.html'>{both("Reference", "完整参考")}</a>
      <a href='{REPO}'>GitHub</a>
    </nav>
    <div class='toggles'>
      <button class='toggle' id='lang-btn' type='button' aria-label='Switch language'>中文</button>
      <button class='toggle' id='theme-btn' type='button' aria-label='Switch theme'>◐</button>
    </div>
  </div>
</header>

<div class='layout'>
  <details class='toc' id='toc'>
    <summary>{both("Contents", "目录")}</summary>
    <nav class='toc-nav'>
{sidebar(current, sections, p)}
    </nav>
  </details>
  <main>
{body}
  </main>
</div>

<footer>
  <div class='cols'>
    <div>
      <h4>{both("Project", "项目")}</h4>
      <ul>
        <li><a href='{REPO}'>GitHub</a></li>
        <li><a href='{p}reference.html'>{both("Reference: modes &amp; all parameters", "完整参考：模式与全部参数")}</a></li>
        <li><a href='{REPO}/blob/main/README.md'>README (EN)</a></li>
        <li><a href='{REPO}/blob/main/README_CN.md'>README（中文）</a></li>
        <li><a href='{REPO}/blob/main/LICENSE'>Apache-2.0</a></li>
      </ul>
    </div>
    <div>
      <h4>{both("Benchmarks", "基准与报告")}</h4>
      <ul>
        <li><a href='{REPO}/blob/main/docs/E2E_TEST_REPORT.md'>{both("End-to-end test report", "端到端测试报告")}</a></li>
        <li><a href='{REPO}/tree/main/results_e2e'>{both("Raw per-mode results", "各模式原始结果")}</a></li>
        <li><a href='{REPO}/actions/workflows/ci.yml'>{both("CI status", "CI 状态")}</a></li>
      </ul>
    </div>
    <div>
      <h4>{both("Packages", "分发包")}</h4>
      <ul>
        <li><a href='{REPO}/releases'>{both("Releases (wheel · sdist · offline images)", "发行版（wheel · 源码包 · 离线镜像）")}</a></li>
        <li><a href='{REPO}/pkgs/container/clawperf'>{both("Container images", "容器镜像")}</a></li>
        <li><a href='https://pypi.org/project/clawperf/'>PyPI</a></li>
      </ul>
    </div>
  </div>
  <div class='fine'>
    {both("ClawPerf — performance benchmarking for LLM serving backends under real agent workloads.",
          "ClawPerf —— 面向真实 Agent 负载的 LLM 推理服务性能基准工具。")}
  </div>
</footer>

<script>{JS}</script>
</body>
</html>
"""


# ── parameters (from the CLI) ────────────────────────────────────────────────

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
        parts.append(opt if is_flag else f"{opt} &lt;{e(row['metavar'] or row['dest'].upper())}&gt;")
    return "<br>".join(f"<code class='opt'>{p}</code>" for p in parts)


def params_table(rows: list, i18n: dict) -> str:
    out = ["<div class='tbl-scroll'><table class='kv'>",
           "<thead><tr><th>Option</th><th>Default</th><th>Description</th></tr></thead><tbody>"]
    for row in rows:
        helps = row["helps"] or [""]
        help_en = "<br>".join(e(h) for h in helps if h) or "<span class='muted'>—</span>"
        help_zh = i18n.get(row["dest"], "")
        desc = f"<span class='en'>{help_en}</span>"
        if help_zh:
            desc += f"<span class='zh'>{e(help_zh)}</span>"
        choices = ""
        if row["choices"]:
            vals = ", ".join(code(str(c)) for c in row["choices"])
            choices = f"<div class='meta'>{both('choices', '可选值')}: {vals}</div>"
        out.append(
            "<tr>"
            f"<td>{option_text(row)}</td>"
            f"<td><code class='inline'>{e(default_text(row))}</code></td>"
            f"<td>{desc}{choices}</td>"
            "</tr>"
        )
    out.append("</tbody></table></div>")
    return "\n".join(out)


def profiles_table() -> str:
    rows = []
    for name in PROFILE_ORDER:
        p = CONTEXT_PROFILES[name]
        base = p["system_prefix_tokens"] + p["user_prefix_tokens"] + p["input_tokens_per_turn"]
        rows.append(
            "<tr>"
            f"<td><code class='inline'>{name}</code></td>"
            f"<td class='num'>{p['system_prefix_tokens']:,}</td>"
            f"<td class='num'>{p['user_prefix_tokens']:,}</td>"
            f"<td class='num'>{p['input_tokens_per_turn']:,}</td>"
            f"<td class='num'><b>{base:,}</b></td>"
            f"<td class='num'>~{round(base / 1000)}K</td>"
            "</tr>"
        )
    return (
        "<div class='tbl-scroll'><table><thead><tr>"
        f"<th>{both('Profile', '档位')}</th><th class='num'>{both('system prefix', '系统前缀')}</th>"
        f"<th class='num'>{both('user prefix', '用户前缀')}</th>"
        f"<th class='num'>{both('input / turn', '每轮输入')}</th>"
        f"<th class='num'>{both('base context', '基础上下文')}</th>"
        f"<th class='num'>{both('rounded', '约')}</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def suites_table() -> str:
    rows = []
    for name, suite in SUITES.items():
        spec = suite["profiles"]
        if spec == "realistic":
            shown = " → ".join(f"<code class='inline'>{p}</code>" for p in REALISTIC_PROFILES)
            count = len(REALISTIC_PROFILES)
        elif isinstance(spec, str):
            shown = f"<code class='inline'>{spec}</code>"
            count = 1
        else:
            shown = " + ".join(f"<code class='inline'>{p}</code>" for p in spec)
            count = len(spec)
        rows.append(
            "<tr>"
            f"<td><code class='inline'>{name}</code></td>"
            f"<td class='num'>{', '.join(str(u) for u in suite['users'])}</td>"
            f"<td>{shown}</td>"
            f"<td class='num'>{suite['max_turns']}</td>"
            f"<td class='num'>{suite['output_tokens_per_turn']}</td>"
            f"<td class='num'>{count * len(suite['users'])}</td>"
            "</tr>"
        )
    return (
        "<div class='tbl-scroll'><table><thead><tr>"
        f"<th>{both('Suite', '套件')}</th><th class='num'>{both('users', '并发用户')}</th>"
        f"<th>{both('profiles', '档位')}</th><th class='num'>{both('turns', '轮数')}</th>"
        f"<th class='num'>{both('out/turn', '每轮输出')}</th>"
        f"<th class='num'>{both('runs', '场景数')}</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


# ── mode pages ───────────────────────────────────────────────────────────────

C = "<code class='inline'>"
CE = "</code>"


def _c(text: str) -> str:
    return C + text + CE


MODES = [
    {
        "slug": "scenario",
        "name": "scenario",
        "tag_en": "The core agentic-load simulator",
        "tag_zh": "核心 Agent 负载模拟器",
        "why_en": "<b>Why:</b> a coding agent does not send one prompt — it grows a conversation, "
                  "reuses the same system prefix every turn, and several sessions run at once. A "
                  "single-shot benchmark cannot see the prefill that accumulates turn by turn, so it "
                  "reports a TTFT your users will never get. This mode models the conversation.",
        "why_zh": "<b>为什么做：</b>编码 Agent 不会只发一次请求 —— 它让会话不断增长、每轮复用同一段系统前缀，"
                  "并且多个会话并发。单次请求压测看不到逐轮累积的预填充量，于是给出一个用户永远拿不到的 TTFT。"
                  "这个模式直接对「会话」建模。",
        "diagram": ("assets/workload.svg",
                    "Each turn reuses everything the previous turn already prefilled: the system prefix, "
                    "the user prefix and the conversation history. Only the newest input is cold-prefilled.",
                    "每一轮都复用了上一轮已预填充的内容：系统前缀、用户前缀与会话历史；只有最新输入需要冷预填充。"),
        "command": "clawperf --mode scenario \\\n"
                   "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\\n"
                   "  --tokenizer /mnt/model/Qwen3-0.6B \\\n"
                   "  --context-profile medium \\\n"
                   "  --num-users 8 --max-turns 20 --user-arrival poisson:2 \\\n"
                   "  --metrics-endpoint http://localhost:8000/metrics --reset-cache \\\n"
                   "  --output results_scenario.json",
        "params": [
            ("--context-profile",
             f"Named context size: {_c('fresh')} 7K → {_c('xxl')} 392K. Sets the system prefix, "
             "per-user prefix and per-turn input at once.",
             f"命名的上下文大小：{_c('fresh')} 7K → {_c('xxl')} 392K，一次性设定系统前缀、用户前缀与每轮输入。"),
            ("--num-users", "Concurrent sessions.", "并发会话数。"),
            ("--max-turns", "Turns per session; history accumulates across them.",
             "每个会话的轮数；历史在这些轮之间累积。"),
            ("--user-arrival",
             f"When sessions join: {_c('burst')}, {_c('steady:&lt;s&gt;')}, {_c('poisson:&lt;λ&gt;')}.",
             f"会话加入时机：{_c('burst')}、{_c('steady:&lt;秒&gt;')}、{_c('poisson:&lt;λ&gt;')}。"),
            ("--max-context-tokens",
             "Where append-mode compaction triggers — set it to the model's real window.",
             "追加式压缩的触发阈值 —— 设为模型真实窗口。"),
            ("--suite", "Sweep several (users × profile) combinations in one command.",
             "一条命令扫完多组（并发 × 档位）。"),
        ],
        "sample": "scenario",
        "read_en": [
            "<b>TTFT</b> should grow with context: compare the first turns with the last ones.",
            "<b>Decode throughput</b> shows whether batching still holds up as sessions multiply.",
            "<b>Compactions</b> above zero means a session hit the window and its history was folded — expected on long runs.",
            "<b>Failed requests</b> must stay at zero; a single 400 usually means the context no longer fits.",
        ],
        "read_zh": [
            "<b>TTFT</b> 应随上下文增长：把最初的几轮和最后的几轮对比。",
            "<b>解码吞吐</b>反映会话变多时批处理是否还撑得住。",
            "<b>Compactions</b> 大于 0 表示某个会话触及窗口、历史被折叠 —— 长跑时属正常。",
            "<b>失败请求</b>必须为 0；一旦出现 400，通常是上下文已经放不下了。",
        ],
    },
    {
        "slug": "hitrate",
        "name": "hitrate",
        "tag_en": "Is the prefix cache actually working?",
        "tag_zh": "前缀缓存到底有没有生效？",
        "why_en": "<b>Why:</b> prefix caching is the single biggest lever on agent latency, and it is "
                  "usually assumed rather than measured. This mode builds a workload with a "
                  "<em>known</em> shared fraction, prefills it, then reads the real hit rate out of the "
                  "server's own Prometheus counters — so “we enabled prefix caching” becomes a number "
                  "you can put in a review.",
        "why_zh": "<b>为什么做：</b>前缀缓存是 Agent 时延上最大的一根杠杆，但通常只是「假设生效」而没有被测量。"
                  "这个模式构造一个<em>已知</em>共享比例的负载，先预填充，再从服务端自己的 Prometheus 计数器读出真实命中率 —— "
                  "于是「我们开了前缀缓存」变成一个可以写进评审的数字。",
        "diagram": ("assets/hitrate.svg",
                    "The hit rate is never inferred from the prompt shape: it is read back from the "
                    "server's counters as a start/end delta, so target and measurement stay independent.",
                    "命中率不从提示词形状推断：而是从服务端计数器的起止差值读回来，因此「目标」与「测量」相互独立。"),
        "command": "clawperf --mode hitrate \\\n"
                   "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\\n"
                   "  --tokenizer /mnt/model/Qwen3-0.6B \\\n"
                   "  --num-requests 200 --input-len 8192 --hit-rate 0.7 --prefix-num 4 \\\n"
                   "  --output-len 128 --concurrency 8 \\\n"
                   "  --metrics-endpoint http://localhost:8000/metrics --reset-cache \\\n"
                   "  --output results_hitrate.json",
        "params": [
            ("--hit-rate",
             f"Target shared fraction 0..1; derives the prefix length. Mutually exclusive with {_c('--prefix-len')}.",
             f"目标共享比例 0..1，用于反推前缀长度；与 {_c('--prefix-len')} 互斥。"),
            ("--input-len", "Total prompt length = shared prefix + boundary + unique suffix.",
             "提示词总长度 = 共享前缀 + 边界 + 各自独有的后缀。"),
            ("--prefix-num",
             "How many <em>distinct</em> prefixes are in play — this is what makes it multi-tenant.",
             "有多少个<em>不同</em>前缀 —— 这正是多租户感的来源。"),
            ("--num-requests", "Measure-phase request count.", "测量阶段的请求数。"),
            ("--no-prefill", "Skip the prefill phase to measure cold-cache behaviour.",
             "跳过预填充阶段，测冷缓存表现。"),
            ("--reset-cache", "Evict the cache first so residual traffic does not inflate the result.",
             "先清空缓存，避免残余流量抬高结果。"),
        ],
        "sample": "hitrate",
        "read_en": [
            "<b>TARGET vs MEASURED</b> is the headline: they should be within a point or two. A large gap means the prompts are not sharing what you think they share.",
            f"<b>Speedup</b> is the real payoff — the theoretical ceiling is {_c('1/(1-hit)')}, and the report prints both.",
            "<b>Per-engine rows</b> show which instance served the reuse; in PD setups the prefill instance usually carries it.",
        ],
        "read_zh": [
            "<b>目标 vs 实测</b>是核心结论：两者应在一两个点以内。差距过大说明提示词的共享方式与你的预期不符。",
            f"<b>加速比</b>才是真正的收益 —— 理论上限是 {_c('1/(1-命中率)')}，报告会同时给出两者。",
            "<b>逐引擎行</b>说明复用发生在哪个实例；PD 部署中通常是 prefill 实例。",
        ],
    },
    {
        "slug": "slo",
        "name": "slo",
        "tag_en": "Turn latency budgets into a capacity number",
        "tag_zh": "把时延预算变成容量数字",
        "why_en": "<b>Why:</b> “how many users can this box serve?” is the question every capacity plan "
                  "needs, and it is not answered by a single load level. This mode raises concurrency "
                  "step by step, evaluates <em>every</em> constraint at each level, and stops at the "
                  "first one that breaks — naming which constraint broke it.",
        "why_zh": "<b>为什么做：</b>「这台机器能支撑多少用户」是每个容量规划都要回答的问题，而单个负载档位答不了。"
                  "这个模式逐级提高并发，在每一级评估<em>全部</em>约束，并在第一个被打破的档位停下 —— 并指出是哪条约束先破的。",
        "diagram": ("assets/slo.svg",
                    "Every level is judged against all constraints at once, so the reported capacity is "
                    "the level that survived all of them — and the failing level tells you which one is binding.",
                    "每一档都要同时满足全部约束，因此给出的容量是「全都扛住了」的那一档；"
                    "失败的那一档则告诉你是哪条约束先到极限。"),
        "command": "clawperf --mode slo \\\n"
                   "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\\n"
                   "  --tokenizer /mnt/model/Qwen3-0.6B \\\n"
                   "  --slo ttft.p99:1500 --slo tpot.avg:30 --slo e2e.max:30000 \\\n"
                   "  --slo-min-users 1 --slo-max-users 200 --slo-step-strategy geometric \\\n"
                   "  --slo-step-turns 5 --slo-error-rate 0.01 \\\n"
                   "  --output results_slo.json",
        "params": [
            ("--slo",
             f"Repeatable constraint {_c('&lt;metric&gt;.&lt;agg&gt;&lt;sep&gt;&lt;ms&gt;')}; all constraints AND together.",
             f"可重复的约束 {_c('&lt;指标&gt;.&lt;统计量&gt;&lt;分隔符&gt;&lt;毫秒&gt;')}；多条之间为「与」关系。"),
            ("--slo-min-users", "Lowest concurrency level the sweep starts from.", "扫描的起始并发用户数。"),
            ("--slo-max-users", "Highest level the sweep may reach.", "扫描可达到的最大并发用户数。"),
            ("--slo-step-strategy",
             f"{_c('geometric')} doubles each step; {_c('linear')} walks one level at a time.",
             f"{_c('geometric')} 每步翻倍；{_c('linear')} 逐级递增。"),
            ("--slo-step-turns",
             f"Measured turns per user at each level (plus {_c('--slo-step-warmup-turns')}).",
             f"每一级每个用户参与测量的轮数（另有 {_c('--slo-step-warmup-turns')} 预热轮）。"),
            ("--slo-error-rate", "Extra pass condition on the error fraction.", "额外的错误率达标条件。"),
            ("--slo-step-timeout-s",
             "Wall-clock budget per level; an overrun counts as TIMEOUT and fails.",
             "每级的墙钟预算；超时记为 TIMEOUT 并判定不达标。"),
        ],
        "sample": "slo",
        "read_en": [
            "<b>One column per constraint</b> — the report never hides a constraint you asked for.",
            "<b>Max sustained users</b> is the number to quote; the next level up is where it breaks.",
            f"Look at <em>which</em> column turned red: capacity is usually bound by {_c('e2e.max')} long before TTFT suffers.",
            f"<b>TIMEOUT</b> rows mean the level could not finish inside {_c('--slo-step-timeout-s')} — raise it for very long contexts.",
        ],
        "read_zh": [
            "<b>每条约束一列</b> —— 报告不会隐藏你要求的任何一条约束。",
            "<b>最大可支撑用户数</b>就是要引用的数字；再上一档就是它开始崩的地方。",
            f"注意<em>哪一列</em>变红：容量往往在 TTFT 变差之前很久就被 {_c('e2e.max')} 卡住。",
            f"<b>TIMEOUT</b> 行表示该档没能在 {_c('--slo-step-timeout-s')} 内跑完 —— 超长上下文时可以调大。",
        ],
    },
    {
        "slug": "agent",
        "name": "agent",
        "tag_en": "Let the model actually work",
        "tag_zh": "让模型真的干活",
        "why_en": "<b>Why:</b> synthetic prompts are a guess at what agents send. In this mode the model "
                  "under test really calls functions — reading files, editing them, running shell "
                  "commands — so the traffic has the shape of agent work: bursty tool loops, long growing "
                  "histories, and a task that either completes or does not.",
        "why_zh": "<b>为什么做：</b>合成提示词只是对 Agent 流量的猜测。这个模式让被测模型真的调用工具 —— "
                  "读文件、改代码、执行 shell —— 于是流量具备 Agent 工作的形态：突发的工具循环、不断增长的长历史，"
                  "以及「任务完成或没完成」这个结果。",
        "diagram": ("assets/agent.svg",
                    "The model calls tools, reads the results back, and loops until the task is done or the "
                    "step budget runs out — with the context growing on every iteration.",
                    "模型调用工具、读回结果、循环直到任务完成或步数预算耗尽 —— 每一轮上下文都在增长。"),
        "command": "clawperf --mode agent \\\n"
                   "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\\n"
                   "  --tokenizer /mnt/model/Qwen3-0.6B \\\n"
                   "  --agent-tasks 8 --agent-max-steps 12 --agent-max-tokens 512 \\\n"
                   "  --agent-shell-timeout 30 \\\n"
                   "  --output results_agent.json",
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
        "read_en": [
            "<b>Task completion</b> is the first thing to read: a fast run that never finishes the task is not a fast server.",
            "<b>Steps and tokens per task</b> are the real cost of agent work — they decide your token budget, not the prompt length.",
            "<b>TTFT per step</b> shows whether tool-loop latency is dominated by the server or by the tools.",
        ],
        "read_zh": [
            "<b>任务完成率</b>是第一眼要看的：跑得快但任务从没做完，不代表服务快。",
            "<b>每个任务的步数与 token</b>才是 Agent 工作的真实成本 —— 决定预算的是它们，不是提示词长度。",
            "<b>每步 TTFT</b> 说明工具循环的时延到底由服务端还是由工具主导。",
        ],
        "note_en": "Needs tool calling on the endpoint. For vLLM that means "
                   + _c("--enable-auto-tool-choice --tool-call-parser qwen3_xml")
                   + " (the parser name depends on the model family).",
        "note_zh": "需要端点开启工具调用。vLLM 需要 "
                   + _c("--enable-auto-tool-choice --tool-call-parser qwen3_xml")
                   + "（解析器名称随模型系列而定）。",
    },
    {
        "slug": "trace",
        "name": "trace",
        "tag_en": "Use your own traffic as the workload",
        "tag_zh": "用你自己的流量当负载",
        "why_en": "<b>Why:</b> every simulated workload is a guess about your traffic; a production trace "
                  "is not. This mode replays a real trace's block hashes through a simulated cache to "
                  "measure achievable reuse and the hit-rate-vs-budget curve — no endpoint needed — and "
                  "can then send the trace's actual requests to your endpoint to measure what that "
                  "workload really costs.",
        "why_zh": "<b>为什么做：</b>任何模拟负载都是对你流量的猜测，而生产 trace 不是。"
                  "这个模式把真实 trace 的 block hash 送进模拟缓存，测出可达复用率与「命中率-预算」曲线（不需要端点）；"
                  "随后还能把 trace 里的真实请求发到你的端点，测出这份负载的真实代价。",
        "diagram": ("assets/trace.svg",
                    "Two paths over the same trace: a pure simulation of the KV cache (no endpoint), and "
                    "an optional real replay of the trace's requests against your server.",
                    "同一份 trace 上的两条路径：纯 KV 缓存模拟（不需要端点），以及可选的、把 trace 请求真实回放到你的服务端。"),
        "command": "# simulation only — no endpoint needed\n"
                   "clawperf --mode trace --trace-file trace.jsonl.gz \\\n"
                   "  --budget-sweep --eviction-policy lru\n"
                   "\n"
                   "# simulation + real replay, clamped to the model window\n"
                   "clawperf --mode trace --trace-file trace.jsonl.gz \\\n"
                   "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\\n"
                   "  --tokenizer /mnt/model/Qwen3-0.6B \\\n"
                   "  --cache-budget-gb 40 --kv-bytes-per-token 2.0 \\\n"
                   "  --model-context-length 32768 --trace-users 4 \\\n"
                   "  --output results_trace.json",
        "params": [
            ("--trace-file",
             f"kvcache.ai JSONL ({_c('{hash_ids, input_length, block_size?}')}), optionally gzipped, or {_c('-')} for stdin.",
             f"kvcache.ai 格式 JSONL（{_c('{hash_ids, input_length, block_size?}')}），可 gzip，或用 {_c('-')} 从标准输入读。"),
            ("--budget-sweep", "Scan several cache sizes to find where returns flatten.",
             "扫描多个缓存容量档位，找出收益拐点。"),
            ("--cache-budget-tokens", "Fixed budget in tokens.", "按 token 指定固定预算。"),
            ("--cache-budget-gb", f"Fixed budget in GB, via {_c('--kv-bytes-per-token')}.",
             f"按 GB 指定固定预算，配合 {_c('--kv-bytes-per-token')} 换算。"),
            ("--eviction-policy", f"{_c('lru')} or {_c('fifo')}.", f"{_c('lru')} 或 {_c('fifo')}。"),
            ("--trace-users", "Session-level concurrency when the trace carries user/session ids.",
             "trace 带用户/会话标识时的会话级并发。"),
            ("--model-context-length",
             "Clamps replay output length; requests that cannot fit are skipped with a reason.",
             "裁剪回放的输出长度；放不下的请求会带原因跳过。"),
        ],
        "sample": "trace",
        "read_en": [
            "<b>Hit rate vs budget</b> is the sizing answer: pick the budget just before the curve flattens.",
            "<b>Evictions</b> tell you the cache is thrashing rather than simply too small.",
            "On real replay, <b>context overflow</b> entries are skipped on purpose — physical impossibilities, not server failures.",
        ],
        "read_zh": [
            "<b>命中率-预算曲线</b>就是定容答案：选曲线刚好变平之前的那个预算。",
            "<b>驱逐次数</b>说明缓存是在颠簸，而不只是容量不够。",
            "真实回放中 <b>context overflow</b> 是主动跳过的 —— 那是物理上放不下，不是服务端故障。",
        ],
    },
    {
        "slug": "record-replay",
        "name": "record &amp; replay",
        "tag_en": "Capture once, replay anywhere",
        "tag_zh": "录一次，随处回放",
        "why_en": "<b>Why:</b> the most convincing benchmark is your own session. Point a real agent "
                  "(Claude Code, any OpenAI or Anthropic client) at the recording proxy while you work; "
                  "afterwards you can replay that exact session against any endpoint — before and after a "
                  "config change, or between two vendors — with the KV-cache prefix aligned the way it "
                  "was live.",
        "why_zh": "<b>为什么做：</b>最有说服力的基准就是你自己的会话。工作时把真实 Agent"
                  "（Claude Code 或任意 OpenAI/Anthropic 客户端）指向录制代理，之后就能把这段会话原样回放到任意端点 —— "
                  "改配置前后对比、两家供应商对比 —— 并且 KV 缓存前缀与当时一致。",
        "diagram": ("assets/record-replay.svg",
                    "The proxy sits between the agent and the upstream model and writes every exchange to "
                    "JSONL; the replay side then feeds that recording to any endpoint.",
                    "代理位于 Agent 与上游模型之间，把每一次交互写入 JSONL；回放侧再把这份录制喂给任意端点。"),
        "command": "# terminal 1 — record (accepts /v1/chat/completions and /v1/messages)\n"
                   "clawperf --mode record --proxy-port 9090 \\\n"
                   "  --upstream-endpoint https://api.example.com/v1 --upstream-api openai \\\n"
                   "  --recording session.jsonl\n"
                   "# ... point your agent at http://localhost:9090/v1, work, then Ctrl+C\n"
                   "\n"
                   "# terminal 2 — replay it against any endpoint\n"
                   "clawperf --mode replay --recording session.jsonl \\\n"
                   "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\\n"
                   "  --tokenizer /mnt/model/Qwen3-0.6B \\\n"
                   "  --history-mode live --concurrency 4 \\\n"
                   "  --output results_replay.json",
        "params": [
            ("--recording",
             "The JSONL file to write (record) or read (replay). Appends across restarts and tells you what it kept.",
             "写入（record）或读取（replay）的 JSONL 文件；跨重启追加，并提示保留了多少历史。"),
            ("--upstream-endpoint", "Where the proxy forwards to.", "代理转发到哪里。"),
            ("--upstream-api",
             f"{_c('openai')}, {_c('anthropic')} or {_c('auto')} — Anthropic is translated on the fly.",
             f"{_c('openai')}、{_c('anthropic')} 或 {_c('auto')} —— Anthropic 会被实时翻译。"),
            ("--history-mode",
             f"{_c('live')} feeds real responses into the next turn (prefix-aligned); "
             f"{_c('verbatim')} replays recorded messages as-is for A/B.",
             f"{_c('live')} 把真实返回作为下一轮历史（前缀对齐）；{_c('verbatim')} 原样回放录制内容，适合 A/B。"),
            ("--concurrency", "In-flight requests during replay.", "回放时的在途请求数。"),
        ],
        "sample": "replay",
        "read_en": [
            "<b>live</b> is what you want for capacity work: the server's own responses become the next turn's history, so prefixes line up exactly as they did in production.",
            "Use <b>verbatim</b> when comparing two servers on identical input — same bytes, different server.",
            "The verdict uses the same thresholds as every other mode, so two reports diff cleanly.",
        ],
        "read_zh": [
            "做容量评估要用 <b>live</b>：服务端真实返回成为下一轮历史，前缀与生产环境完全一致。",
            "比较两台服务端处理同样输入时用 <b>verbatim</b> —— 同样的字节，不同的服务端。",
            "结论阈值与其他模式一致，因此两份报告可以直接对比。",
        ],
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
    "shell-safety": "shell 引号陷阱，以及裸指标名传到 ClawPerf 时的诊断。",
}


def mode_page(mode: dict) -> tuple:
    sections = [("why", "Why this mode", "为什么做"),
                ("how", "How to run it", "怎么用"),
                ("params", "Parameters", "关键参数"),
                ("output", "Real output", "真实输出"),
                ("read", "How to read it", "怎么读结果")]
    diagram, cap_en, cap_zh = mode["diagram"]
    diagram = f"../{diagram}"  # mode pages live in modes/, the figures in assets/
    rows = "".join(
        f"<tr><td><code class='inline'>{e(flag)}</code></td>"
        f"<td><span class='en'>{en_txt}</span><span class='zh'>{zh_txt}</span></td></tr>"
        for flag, en_txt, zh_txt in mode["params"]
    )
    reads = "".join(
        f"<li><span class='en'>{x}</span><span class='zh'>{y}</span></li>"
        for x, y in zip(mode["read_en"], mode["read_zh"])
    )
    others = "".join(
        f"<a class='pill' href='{m['slug']}.html'>{m['name']}</a>"
        for m in MODES if m["slug"] != mode["slug"]
    )
    note = ""
    if mode.get("note_en"):
        note = f"<p class='note'>{both(mode['note_en'], mode['note_zh'])}</p>"
    sample_note = both(SAMPLES_DATA["samples"][mode["sample"]]["note"], SAMPLE_NOTES_ZH[mode["sample"]])
    body = f"""<div class='wrap' style='padding-top:34px'>
  <p class='eyebrow'>{both("Mode", "模式")} · {mode['name']}</p>
  <h1>{mode['name']}: {both(mode['tag_en'], mode['tag_zh'])}</h1>
  <p class='lead'>{both("What this mode answers, how to run it, and what the output tells you.", "这个模式回答什么、怎么用、以及输出该怎么读。")}</p>

  <h2 id='why'>{both("Why this mode exists", "为什么做这个模式")}</h2>
  <p class='why'>{both(mode['why_en'], mode['why_zh'])}</p>
  {fig(diagram, mode['tag_en'], cap_en, cap_zh)}

  <h2 id='how'>{both("How to run it", "怎么用")}</h2>
  {command_block(mode['command'])}
  {note}

  <h2 id='params'>{both("Parameters that matter", "关键参数")}</h2>
  <div class='tbl-scroll'><table class='kv'><tbody>{rows}</tbody></table></div>
  <p class='sub'>{both("The full list, with defaults, is in the", "完整参数列表（含默认值）见")} <a href='../reference.html#params'>{both("reference", "完整参考")}</a>.</p>

  <h2 id='output'>{both("Real output", "真实输出")}</h2>
  <p class='sub'>{sample_note}</p>
  {sample_block(mode['sample'])}

  <h2 id='read'>{both("How to read it", "怎么读结果")}</h2>
  <ul class='tight'>{reads}</ul>

  <div class='next'><span class='label' style='margin:0'>{both("Other modes", "其他模式")}</span>{others}</div>
</div>"""
    return f"modes/{mode['slug']}.html", f"{mode['name']} — {mode['tag_en']}", sections, body


# ── pages ────────────────────────────────────────────────────────────────────

def page_index() -> tuple:
    samples = SAMPLES_DATA["samples"]
    cards = "".join(
        f"<a class='card card-link' href='modes/{m['slug']}.html'>"
        f"<b><code>{m['name']}</code></b>"
        f"<span class='en'>{m['tag_en']}</span><span class='zh'>{m['tag_zh']}</span></a>"
        for m in MODES
    )
    e2e = f"{REPO}/blob/main/docs/E2E_TEST_REPORT.md"
    first_cmd = ("clawperf --mode scenario \\\n"
                 "  --endpoint http://localhost:8000/v1 --model Qwen3-0.6B \\\n"
                 "  --tokenizer /mnt/model/Qwen3-0.6B \\\n"
                 "  --context-profile medium --num-users 8 --max-turns 20 \\\n"
                 "  --metrics-endpoint http://localhost:8000/metrics \\\n"
                 "  --output results.json")
    body = f"""<div class='wrap' style='padding-top:34px'>
  <p class='eyebrow'>{both("LLM serving benchmarks", "LLM 推理服务基准")}</p>
  <h1>ClawPerf</h1>
  <p class='lead'>{both("Benchmark LLM serving under <b>real agent workloads</b> — multi-turn, long-context, prefix-cache-heavy traffic. Seven modes, one CLI, built on <a href='https://github.com/modelscope/evalscope'>EvalScope</a>.",
                        "面向 <b>真实 Agent 负载</b>的 LLM 推理服务性能基准 —— 多轮对话、长上下文、前缀缓存密集的流量。七种模式，一个 CLI，构建在 <a href='https://github.com/modelscope/evalscope'>EvalScope</a> 之上。")}</p>
  <div class='next'>
    <a class='btn primary' href='quickstart.html'>{both("Quick start", "快速开始")}</a>
    <a class='btn' href='reference.html'>{both("Full reference", "完整参考")}</a>
    <a class='btn' href='{REPO}'>GitHub</a>
    <a class='btn' href='{REPO}/releases'>{both("Releases &amp; images", "发行版与镜像")}</a>
  </div>
</div>

<div class='wrap' style='margin-top:36px'>
  <h2>{both("First run", "首次运行")}</h2>
  <p class='sub'>{both(f"The default mode is {_c('scenario')}: N users holding independent conversations that grow turn by turn. Point {_c('--tokenizer')} at a local directory — it is loaded strictly offline.",
                       f"默认模式是 {_c('scenario')}：N 个用户各自进行不断增长的多轮会话。把 {_c('--tokenizer')} 指向本地目录 —— 它会严格离线加载。")}</p>
  {command_block(first_cmd)}
  <div class='next'>
    <a class='btn primary' href='quickstart.html'>{both("Quick start", "快速开始")}</a>
    <a class='btn' href='configuration.html'>{both("Context profiles &amp; knobs", "档位与旋钮")}</a>
  </div>
</div>

<div class='wrap' style='margin-top:36px'>
  <div class='grid c3'>
    <div class='card'><h3>{both("7 modes", "7 种模式")}</h3>
      <p>{both("Each answers a different question — see the map below.", "每种回答一个不同的问题 —— 见下方模式地图。")}</p></div>
    <div class='card'><h3>{both("4 backends", "4 种后端")}</h3>
      <p>{both("vLLM · SGLang · MindIE · vllm-ascend, with per-backend metric mapping.", "vLLM · SGLang · MindIE · vllm-ascend，指标映射按后端区分。")}</p></div>
    <div class='card'><h3>amd64 + arm64</h3>
      <p>{both("Native multi-arch images, plus a mock server so CI needs no GPU.", "原生双架构镜像，另带 mock server，CI 无需 GPU。")}</p></div>
  </div>
</div>

<div class='wrap' style='margin-top:36px'>
  <h2>{both("Pick the question you need answered", "按你要回答的问题选模式")}</h2>
  <p class='sub'>{both("Every mode writes a JSON result plus a Markdown report with a verdict. Each one has its own page: why it exists, a diagram, the command, the parameters and a real run.",
                       "每种模式都会产出 JSON 结果与带结论的 Markdown 报告。每种模式一个页面：为什么做、示意图、命令、参数与一次真实运行。")}</p>
  <div class='grid c2'>{cards}</div>
</div>

<div class='wrap' style='margin-top:36px'>
  <h2>{both("One runner, seven workloads", "一个 Runner，七种负载")}</h2>
  {fig("assets/pipeline.svg",
       "ClawPerf pipeline: the workload modes drive a runner that sends requests to a serving backend and polls its metrics",
       "The same runner drives every mode: it generates the workload, sends it, polls the backend's Prometheus endpoint and writes the JSON result plus the Markdown verdict.",
       "所有模式共用同一个 Runner：生成负载、发送请求、抓取后端的 Prometheus 指标，并写出 JSON 结果与 Markdown 结论。")}
</div>

<div class='wrap' style='margin-top:36px'>
  <h2>{both("Measured, not claimed", "实测数据，而非宣传")}</h2>
  <p class='sub'>{both(f"From the end-to-end run in <a href='{e2e}'>docs/E2E_TEST_REPORT.md</a>: vLLM-Ascend v0.23.0, Qwen3-0.6B, one Ascend 910B3.",
                       f"数据来自 <a href='{e2e}'>docs/E2E_TEST_REPORT.md</a> 的端到端测试：vLLM-Ascend v0.23.0 + Qwen3-0.6B，单张昇腾 910B3。")}</p>
  <div class='grid c3'>
    <div class='card'><h3>{both("Hit rate is verifiable", "命中率可验证")}</h3>
      <p>{both("<b>49.90%</b> measured against a <b>50.00%</b> target — 40 requests, 2 distinct prefixes, concurrency 4.", "目标 <b>50.00%</b>，实测 <b>49.90%</b> —— 40 个请求、2 个不同前缀、并发 4。")}</p></div>
    <div class='card'><h3>{both("Real traces reuse a lot", "真实 trace 复用率很高")}</h3>
      <p>{both("<b>90.42%</b> prefix-reuse ceiling over 34 real Claude Code requests; replay of the fitting requests succeeded <b>29/29</b>.", "34 个真实 Claude Code 请求的复用上限 <b>90.42%</b>；可容纳的请求回放 <b>29/29</b> 成功。")}</p></div>
    <div class='card'><h3>{both("Capacity is a number", "容量是一个确定的数")}</h3>
      <p>{both(f"<b>5 users</b> sustained under {_c('ttft.p99≤1500ms')}, {_c('tpot.avg≤30ms')}, {_c('e2e.max≤20s')}.",
               f"在 {_c('ttft.p99≤1500ms')}、{_c('tpot.avg≤30ms')}、{_c('e2e.max≤20s')} 下可稳定支撑 <b>5 个用户</b>。")}</p></div>
  </div>
  <h3>{both("A real SLO sweep", "一次真机 SLO 扫描")}</h3>
  <p class='sub'>{both(samples['slo']['note'], SAMPLE_NOTES_ZH['slo'])}</p>
  {sample_block("slo")}
</div>"""
    return "index.html", "LLM serving benchmarks under real agent workloads", [], body


def page_quickstart() -> tuple:
    sections = [("install", "Install", "安装"),
                ("first-run", "First run", "首次运行"),
                ("output", "Reading the output", "怎么读输出"),
                ("nogpu", "No GPU? Mock server", "没有 GPU？"),
                ("exit", "Exit codes", "退出码")]
    install = ('# pip (the extras pull in the agent, record/replay and mock-server bits)\n'
               'pip install "clawperf[agent,record,replay,mock-server]"\n'
               '\n'
               '# or the container image — it bundles examples/ and a local tokenizer\n'
               'docker pull ghcr.io/ucm-system/clawperf:latest')
    first_run = ("clawperf --mode scenario \\\n"
                 "  --endpoint http://localhost:8000/v1 \\\n"
                 "  --model Qwen3-0.6B \\\n"
                 "  --tokenizer /mnt/model/Qwen3-0.6B \\\n"
                 "  --context-profile medium \\\n"
                 "  --num-users 8 --max-turns 20 \\\n"
                 "  --metrics-endpoint http://localhost:8000/metrics \\\n"
                 "  --output results.json")
    mock = ("# terminal 1\n"
            "clawperf-mock-server --port 8000\n"
            "\n"
            "# terminal 2 — the same command, now pointed at the mock\n"
            "clawperf --mode scenario --endpoint http://localhost:8000/v1 \\\n"
            "  --model qwen3-0.6b --tokenizer tokenizers/qwen3-0.6b \\\n"
            "  --context-profile fresh --num-users 4 --max-turns 4 \\\n"
            "  --metrics-endpoint http://localhost:8000/metrics --reset-cache")
    tokenizer_note = both(
        f"<b>Point {_c('--tokenizer')} at a local directory.</b> It is loaded strictly offline (no hub "
        f"lookup, no download) and drives exact token counting, context clamping and content generation. "
        f"Use the same directory your server loaded the model from — or the image's bundled "
        f"{_c('/app/tokenizers/qwen3-0.6b')} to sanity-check the setup.",
        f"<b>把 {_c('--tokenizer')} 指向本地目录。</b>它会严格离线加载（不查 hub、不下载），并负责精确分词、"
        f"上下文裁剪与内容生成。指向服务端加载模型的同一个目录即可 —— 也可以先用镜像内置的 "
        f"{_c('/app/tokenizers/qwen3-0.6b')} 验证环境。")
    body = f"""<div class='wrap' style='padding-top:34px'>
  <p class='eyebrow'>{both("Quick start", "快速开始")}</p>
  <h1>{both("From zero to a benchmark in one command", "一条命令跑起第一个基准")}</h1>
  <p class='lead'>{both(f"The default mode is {_c('scenario')}: N users holding independent conversations that grow turn by turn. You need a running OpenAI-compatible endpoint and a tokenizer directory.",
                        f"默认模式是 {_c('scenario')}：N 个用户各自进行不断增长的多轮会话。只需要一个正在运行的 OpenAI 兼容端点和一个 tokenizer 目录。")}</p>

  <h2 id='install'>{both("Install", "安装")}</h2>
  {command_block(install, "shell")}

  <h2 id='first-run'>{both("First run", "首次运行")}</h2>
  {command_block(first_run)}
  <p class='note'>{tokenizer_note}</p>

  <h2 id='output'>{both("Reading the output", "怎么读输出")}</h2>
  <p class='sub'>{both("A live run against the bundled mock server (no GPU needed) — everything below the banner uses the same code path as a real endpoint.",
                       "以下是在内置 mock server 上的实跑（无需 GPU）—— 横幅以下走的是与真实端点完全相同的代码路径。")}</p>
  {sample_block("live-run")}
  <div class='grid c2'>
    <div class='card'><h3>{both("The four numbers that matter", "四个关键数字")}</h3>
      <p>{both("<b>TTFT</b> — time to first token. <b>TPOT</b> — per output token. <b>E2E</b> — full request latency. <b>Hit rate</b> — read from the server's Prometheus counters, never inferred.",
               "<b>TTFT</b> —— 首 token 时延。<b>TPOT</b> —— 每输出 token。<b>E2E</b> —— 请求端到端时延。<b>命中率</b> —— 直接读服务端 Prometheus 计数器，从不推断。")}</p></div>
    <div class='card'><h3>{both("Two artifacts per run", "每次运行两个产物")}</h3>
      <p>{both(f"{_c('results.json')} (config + per-user/per-turn detail + metrics) and {_c('results.md')} (verdict, findings, ASCII charts). Regenerate the report with {_c('clawperf report results.json')}.",
               f"{_c('results.json')}（配置 + 按用户/按轮明细 + 指标）与 {_c('results.md')}（结论、发现、ASCII 图表）。可用 {_c('clawperf report results.json')} 重新生成报告。")}</p></div>
  </div>

  <h2 id='nogpu'>{both("No GPU at hand?", "手边没有 GPU？")}</h2>
  <p class='sub'>{both(f"Ship the mock server instead: it has a real trie prefix cache and vLLM-style {_c('/metrics')}, so every mode works end to end.",
                       f"用内置 mock server 替代：它带真实的字典树前缀缓存与 vLLM 风格 {_c('/metrics')}，所有模式都能跑通。")}</p>
  {command_block(mock)}

  <h2 id='exit'>{both("Exit codes &amp; troubleshooting", "退出码与故障排查")}</h2>
  <div class='tbl-scroll'><table>
    <thead><tr><th>{both("Code", "退出码")}</th><th>{both("Meaning", "含义")}</th></tr></thead>
    <tbody>
      <tr><td><code class='inline'>0</code></td><td>{both("the benchmark ran; results written", "基准跑完并写出结果")}</td></tr>
      <tr><td><code class='inline'>1</code></td><td>{both("configuration or pre-flight error (no benchmark ran)", "配置或预检错误（未开始跑基准）")}</td></tr>
      <tr><td><code class='inline'>2</code></td><td>{both("the benchmark ran but <b>every</b> request failed (CI gate)", "基准跑了但<b>全部</b>请求失败（CI 门禁）")}</td></tr>
      <tr><td><code class='inline'>3</code></td><td>{both("interrupted (Ctrl+C); partial results are written", "被中断（Ctrl+C）；退出前会写出部分结果")}</td></tr>
    </tbody>
  </table></div>
  <p class='sub'>{both("The full troubleshooting table — tokenizer paths, the SLO shell trap, the pre-flight probe — lives in the <a href='reference.html#trouble'>reference</a>.",
                       "完整的故障排查表（tokenizer 路径、SLO 引号陷阱、预检探针）在<a href='reference.html#trouble'>完整参考</a>里。")}</p>
  {sample_block("shell-safety")}
  <div class='next'>
    <a class='btn primary' href='modes/scenario.html'>{both("Next: the modes, in depth", "下一步：模式详解")}</a>
  </div>
</div>"""
    return "quickstart.html", "Quick start", sections, body


def page_configuration() -> tuple:
    sections = [("profiles", "Context profiles", "上下文档位"),
                ("suites", "Suites", "套件"),
                ("pacing", "Pacing &amp; concurrency", "节奏与并发"),
                ("metrics", "Metrics endpoints", "指标端点"),
                ("layers", "Env vars &amp; config file", "环境变量与配置文件")]
    suite_cmd = ("# one profile\n"
                 "clawperf --mode scenario --context-profile medium --num-users 8 ...\n"
                 "\n"
                 "# sweep profiles x users\n"
                 "clawperf --mode scenario --suite full --model-context-length 32768 ...")
    metrics_cmd = ("clawperf --mode scenario \\\n"
                   "  --endpoint http://lb:9000/v1 --model Qwen3-0.6B \\\n"
                   "  --tokenizer /mnt/model/Qwen3-0.6B \\\n"
                   "  --metrics-endpoint prefill=http://10.0.0.1:9101/metrics \\\n"
                   "  --metrics-endpoint decode=http://10.0.0.2:9102/metrics \\\n"
                   "  --reset-cache")
    yaml_cmd = ("# clawperf.yaml\n"
                "mode: scenario\n"
                "endpoint: http://localhost:8000/v1\n"
                "model: Qwen3-0.6B\n"
                "tokenizer: /mnt/model/Qwen3-0.6B\n"
                "context_profile: medium\n"
                "num_users: 8\n"
                "max_turns: 20\n"
                "slo_constraints: [\"ttft.p99<=1500\", \"tpot.avg<=30\"]\n"
                "\n"
                "# CLI > env > YAML > defaults\n"
                "clawperf --config clawperf.yaml --num-users 16")
    body = f"""<div class='wrap' style='padding-top:34px'>
  <p class='eyebrow'>{both("Configuration", "配置")}</p>
  <h1>{both("The knobs you will actually touch", "你真正会动的几个旋钮")}</h1>
  <p class='lead'>{both(f"Everything else — all parameters, their defaults and accepted values — is in the <a href='reference.html#params'>reference</a>, generated from {_c('clawperf --help')}.",
                        f"其余全部内容 —— 所有参数、默认值与可选值 —— 都在<a href='reference.html#params'>完整参考</a>里，由 {_c('clawperf --help')} 自动生成。")}</p>

  <h2 id='profiles'>{both("Context profiles", "上下文档位")}</h2>
  <p class='sub'>{both("A profile sets the shared system prefix, the per-user prefix and the per-turn input at once, so you do not have to invent token counts. Names are case-insensitive.",
                       "一个档位同时设定共享系统前缀、每用户前缀与每轮输入三个数字，免去自己拼 token 数。档位名大小写不敏感。")}</p>
  {profiles_table()}
  {fig("assets/context_model.svg",
       "How the context is built: shared system prefix, per-user prefix, growing history and the newest input",
       "The context is not one blob: the shared system prefix is what every session reuses, the per-user prefix makes sessions distinct, and only the newest input is always cold.",
       "上下文不是一整块：共享系统前缀是所有会话复用的部分，用户前缀让会话彼此不同，而只有最新输入永远是冷的。")}
  <p class='note'>{both(f"Raw counts still work: {_c('--system-prefix-tokens')}, {_c('--user-prefix-tokens')}, {_c('--input-tokens-per-turn')}. A profile simply overrides all three.",
                       f"也可以直接用原始数字：{_c('--system-prefix-tokens')}、{_c('--user-prefix-tokens')}、{_c('--input-tokens-per-turn')}。档位只是把这三个一起覆盖掉。")}</p>

  <h2 id='suites'>{both("Suites", "套件")}</h2>
  <p class='sub'>{both(f"A suite runs several (users × profile) scenarios in sequence and writes one result file per scenario. {_c('--model-context-length')} skips profiles that cannot fit the model window.",
                       f"套件按序跑完（并发 × 档位）的笛卡尔积，每个场景各写一份结果文件。{_c('--model-context-length')} 会跳过放不进模型窗口的档位。")}</p>
  {suites_table()}
  {command_block(suite_cmd)}

  <h2 id='pacing'>{both("Pacing &amp; concurrency", "节奏与并发")}</h2>
  <p class='sub'>{both("Four knobs that are easy to confuse. The distinction that matters: a closed loop can never overload a server, an open loop can.",
                       "四个容易混淆的旋钮。关键区别：闭环永远压不垮服务端，开环可以。")}</p>
  <div class='tbl-scroll'><table>
    <thead><tr><th>{both("Knob", "旋钮")}</th><th>{both("Controls", "控制什么")}</th><th>{both("Semantics", "语义")}</th></tr></thead>
    <tbody>
      <tr><td><code class='inline'>--user-arrival</code></td>
          <td>{both("when each <b>session</b> joins", "每个<b>会话</b>何时加入")}</td>
          <td>{both("users then run their turns back-to-back", "加入后各自连续跑自己的轮次")}</td></tr>
      <tr><td><code class='inline'>--concurrency</code></td>
          <td>{both("<b>closed loop</b>: in-flight request cap", "<b>闭环</b>：在途请求上限")}</td>
          <td>{both("the next request starts when one finishes — the server throttles the load", "上一个返回才发下一个 —— 节奏由服务端决定")}</td></tr>
      <tr><td><code class='inline'>--request-rate</code></td>
          <td>{both("<b>open loop</b>: issue rate in req/s", "<b>开环</b>：每秒发送速率")}</td>
          <td>{both("released on a Poisson schedule regardless of completions — this one <b>can</b> overload a server", "按泊松过程发送，与是否完成无关 —— 只有它会真正压垮服务端")}</td></tr>
      <tr><td><code class='inline'>--trace-users</code></td>
          <td>{both("session-level concurrency for trace replay", "trace 回放的会话级并发")}</td>
          <td>{both("turns inside one session stay ordered", "同一会话内的轮次保持有序")}</td></tr>
    </tbody>
  </table></div>
  {fig("assets/arrival_patterns.svg",
       "Arrival patterns: burst, steady and Poisson session arrivals",
       "Sessions can join all at once, at a fixed interval, or on a Poisson process — the same three shapes real traffic takes.",
       "会话可以一次性全部加入、按固定间隔加入，或按泊松过程加入 —— 真实流量也是这三种形态。")}

  <h2 id='metrics'>{both("Metrics endpoints", "指标端点")}</h2>
  <p class='sub'>{both(f"PD-disaggregated and multi-replica services expose one {_c('/metrics')} per instance. Pass them all: counters are summed into a fleet-wide view, ratio gauges averaged, and the per-engine table gains one row per instance.",
                       f"PD 分离与多副本服务每个实例各暴露一个 {_c('/metrics')}。全部传进来即可：计数器求和成全局视图、比率类指标取均值、逐引擎表按实例分行。")}</p>
  {command_block(metrics_cmd)}
  <p class='sub'>{both(f"Labels are optional ({_c('name=url')}; the default is host:port) and the flag is repeatable or comma-separated. {_c('--reset-cache')} resets every instance.",
                       f"标签可选（{_c('名称=url')}，默认 host:port）；该参数可重复或用逗号分隔。{_c('--reset-cache')} 会逐个重置所有实例。")}</p>

  <h2 id='layers'>{both("Env vars &amp; config file", "环境变量与配置文件")}</h2>
  <p class='sub'>{both(f"Precedence: <b>CLI &gt; environment &gt; YAML ({_c('--config')}) &gt; defaults</b>. Every config field has a {_c('CLAWPERF_*')} counterpart, upper-cased. An explicitly passed flag always wins — even when its value equals the default.",
                       f"优先级：<b>CLI &gt; 环境变量 &gt; YAML（{_c('--config')}）&gt; 默认值</b>。每个配置字段都有对应的大写 {_c('CLAWPERF_*')} 变量。显式传入的 flag 永远优先 —— 即使取值恰好等于默认值。")}</p>
  <div class='tbl-scroll'><table>
    <thead><tr><th>{both("Variable", "变量")}</th><th>{both("Equivalent to", "等价于")}</th></tr></thead>
    <tbody>
      <tr><td><code class='inline'>CLAWPERF_ENDPOINT</code></td><td><code class='inline'>--endpoint</code></td></tr>
      <tr><td><code class='inline'>CLAWPERF_MODEL</code></td><td><code class='inline'>--model</code></td></tr>
      <tr><td><code class='inline'>CLAWPERF_API_KEY</code></td><td><code class='inline'>--api-key</code></td></tr>
      <tr><td><code class='inline'>CLAWPERF_OUTPUT</code></td><td><code class='inline'>--output</code></td></tr>
      <tr><td><code class='inline'>CLAWPERF_HISTORY</code></td><td><code class='inline'>--history</code> (<code class='inline'>''</code> disables)</td></tr>
      <tr><td><code class='inline'>CLAWPERF_UPSTREAM_ENDPOINT</code></td><td><code class='inline'>--upstream-endpoint</code></td></tr>
      <tr><td><code class='inline'>CLAWPERF_TOKENIZER_BACKEND</code></td><td><code class='inline'>transformers</code> | <code class='inline'>modelscope</code></td></tr>
      <tr><td><code class='inline'>CLAWPERF_&lt;FIELD&gt;</code></td>
          <td>{both(f"any field: {_c('CLAWPERF_NUM_USERS')}, {_c('CLAWPERF_CONTEXT_PROFILE')}, …",
                   f"任意字段：{_c('CLAWPERF_NUM_USERS')}、{_c('CLAWPERF_CONTEXT_PROFILE')} 等")}</td></tr>
    </tbody>
  </table></div>
  {command_block(yaml_cmd)}
</div>"""
    return "configuration.html", "Configuration", sections, body


def page_reference() -> tuple:
    i18n = json.loads(I18N.read_text(encoding="utf-8")) if I18N.is_file() else {}
    groups = collect_groups()
    by_title = {title: rows for title, rows in groups}
    sections = [("slo-syntax", "SLO constraint syntax", "SLO 约束语法"),
                ("params", "All parameters", "全部参数"),
                ("exit", "Output &amp; exit codes", "产物与退出码"),
                ("trouble", "Troubleshooting", "故障排查")]
    global_groups = ["Mode", "Context Profiles & Suites", "User Configuration",
                     "Context Configuration", "Run Configuration", "API Configuration",
                     "System Metrics", "Output", "Configuration Files"]
    mode_groups = [("hitrate", "Hit-Rate Mode (only with --mode hitrate)"),
                   ("slo", "SLO Mode (only with --mode slo)"),
                   ("agent", "Agent Mode (only with --mode agent)"),
                   ("record", "Record Mode (only with --mode record)"),
                   ("replay", "Replay Mode (only with --mode replay)"),
                   ("trace", "Trace Mode (only with --mode trace)")]
    parts = []
    for title in global_groups:
        if title in by_title:
            parts.append(f"<h3>{e(title)}</h3>")
            parts.append(params_table(by_title[title], i18n))
    for mode, title in mode_groups:
        if title in by_title:
            parts.append(f"<h4 class='mode-params' id='opt-{mode}'>{e(title)}</h4>")
            parts.append(params_table(by_title[title], i18n))
    params_html = "\n".join(parts)
    total = sum(len(rows) for _, rows in groups)
    flags = sum(len(r["opts"]) for _, rows in groups for r in rows)
    trouble_rows = [
        ("bash: =10000: No such file or directory",
         f"the shell ate the {_c('&lt;')} in {_c('--slo ttft.p99&lt;=10000')}. Use {_c('--slo ttft.p99:10000')} or quote the spec.",
         f"shell 吃掉了 {_c('--slo ttft.p99&lt;=10000')} 中的 {_c('&lt;')}。改用 {_c('--slo ttft.p99:10000')}，或给参数加引号。"),
        ("Tokenizer path '...' does not exist",
         f"the path is not visible inside the container — the error lists the parent directory; mount it with {_c('-v /mnt/model:/mnt/model:ro')}.",
         f"容器内看不到该路径 —— 报错会列出父目录内容；用 {_c('-v /mnt/model:/mnt/model:ro')} 挂载。"),
        ("Pre-flight: ... Connection reset by peer",
         f"the server reset the tiny probe (often while still loading weights). Transient errors are retried 3× with backoff; add {_c('--no-preflight')} to skip the probe.",
         f"服务端重置了这个极小探针（常见于仍在加载权重）。传输类错误会自动退避重试 3 次；加 {_c('--no-preflight')} 可完全跳过探针。"),
        ("UnicodeEncodeError on Windows",
         f"the CLI already forces UTF-8 stdio; if a third-party tool still fails, set {_c('PYTHONIOENCODING=utf-8')}.",
         f"CLI 已强制 UTF-8 stdio；若第三方工具仍报错，设置 {_c('PYTHONIOENCODING=utf-8')}。"),
    ]
    trouble = "".join(
        f"<tr><td><code class='inline'>{e(sym)}</code></td>"
        f"<td><span class='en'>{en_t}</span><span class='zh'>{zh_t}</span></td></tr>"
        for sym, en_t, zh_t in trouble_rows
    )
    body = f"""<div class='wrap' style='padding-top:34px'>
  <p class='eyebrow'>{both("Reference", "完整参考")}</p>
  <h1>{both("Every parameter, generated from the code", "全部参数，由代码自动生成")}</h1>
  <p class='lead'>{both(f"This page is generated from {_c('clawperf --help')} and the context-profile definitions, so it cannot drift from the tool. {total} parameters / {flags} flags.",
                        f"本页由 {_c('clawperf --help')} 与上下文档位定义自动生成，不会与工具脱节。共 {total} 个参数 / {flags} 个 flag。")}</p>

  <h2 id='slo-syntax'>{both("SLO constraint syntax", "SLO 约束语法")}</h2>
  <p class='sub'>{both(f"{_c('&lt;metric&gt;.&lt;agg&gt;&lt;sep&gt;&lt;ms&gt;')} — repeat {_c('--slo')} to AND several constraints together. <b>In a shell, quote {_c('&lt;=')} or use a separator without {_c('&lt;')}/{_c('&gt;')}</b>, because those characters are redirections.",
                       f"{_c('&lt;指标&gt;.&lt;统计量&gt;&lt;分隔符&gt;&lt;毫秒&gt;')} —— 重复 {_c('--slo')} 可「与」多个约束。<b>在 shell 中要么给 {_c('&lt;=')} 加引号，要么改用不含 {_c('&lt;')}/{_c('&gt;')} 的分隔符</b>，因为这两个字符是重定向符号。")}</p>
  <div class='tbl-scroll'><table>
    <thead><tr><th>{both("Write", "写法")}</th><th>{both("Means", "含义")}</th><th>{both("Notes", "说明")}</th></tr></thead>
    <tbody>
      <tr><td><code class='inline'>ttft.p99:1500</code></td><td><code class='inline'>ttft.p99 &lt;= 1500ms</code></td><td>{both("shell-safe (no quoting)", "免引号")}</td></tr>
      <tr><td><code class='inline'>tpot.avg=30</code></td><td><code class='inline'>tpot.avg &lt;= 30ms</code></td><td>{both("shell-safe (no quoting)", "免引号")}</td></tr>
      <tr><td><code class='inline'>'ttft.p99&lt;=1500'</code></td><td><code class='inline'>ttft.p99 &lt;= 1500ms</code></td><td>{both("must be quoted in bash/zsh", "在 bash/zsh 中必须加引号")}</td></tr>
      <tr><td><code class='inline'>ttft.p99:ge:1500</code></td><td><code class='inline'>ttft.p99 &gt;= 1500ms</code></td><td>{both("the only shell-safe way to write &gt;=", "唯一免引号的 &gt;= 写法")}</td></tr>
      <tr><td><code class='inline'>'a&lt;=1,b&lt;=2'</code></td><td>{both("both constraints", "两条约束")}</td><td>{both("one quoted argument, several constraints", "一个引号参数写多条约束")}</td></tr>
    </tbody>
  </table></div>
  <div class='grid c2'>
    <div class='card'><h3>{both("Metrics", "指标")}</h3>
      <p>{both(f"{_c('ttft')} (time to first token), {_c('tpot')} (time per output token), {_c('e2e')} (end-to-end latency).",
               f"{_c('ttft')}（首 token 时延）、{_c('tpot')}（每输出 token 时延）、{_c('e2e')}（端到端时延）。")}</p></div>
    <div class='card'><h3>{both("Aggregates", "统计量")}</h3>
      <p>{both(f"{_c('avg')}, {_c('min')}, {_c('max')}, and any percentile {_c('p25 p50 p75 p90 p95 p99 p99.9')}. Several constraints AND together; the sweep stops at the first level that breaks any of them.",
               f"{_c('avg')}、{_c('min')}、{_c('max')}，以及任意分位 {_c('p25 p50 p75 p90 p95 p99 p99.9')}。多条约束为「与」关系；一旦某一级打破了任意一条，扫描即在此停止。")}</p></div>
  </div>
  {sample_block("shell-safety")}

  <h2 id='params'>{both("All parameters", "全部参数")}</h2>
  <p class='sub'>{both(f"Generated from {_c('clawperf --help')} — every option, its default and its accepted values. Mode-specific groups are listed after the shared ones.",
                       f"由 {_c('clawperf --help')} 自动生成 —— 每个参数、默认值与可选值。各模式专属参数列在通用参数之后。")}</p>
  {params_html}

  <h2 id='exit'>{both("Output &amp; exit codes", "产物与退出码")}</h2>
  <div class='tbl-scroll'><table>
    <thead><tr><th>{both("Code", "退出码")}</th><th>{both("Meaning", "含义")}</th></tr></thead>
    <tbody>
      <tr><td><code class='inline'>0</code></td><td>{both("the benchmark ran; results written", "基准跑完并写出结果")}</td></tr>
      <tr><td><code class='inline'>1</code></td><td>{both("configuration or pre-flight error (no benchmark ran)", "配置或预检错误（未开始跑基准）")}</td></tr>
      <tr><td><code class='inline'>2</code></td><td>{both("the benchmark ran but <b>every</b> request failed (CI gate)", "基准跑了但<b>全部</b>请求失败（CI 门禁）")}</td></tr>
      <tr><td><code class='inline'>3</code></td><td>{both("interrupted (Ctrl+C); partial results are written", "被中断（Ctrl+C）；退出前会写出部分结果")}</td></tr>
    </tbody>
  </table></div>
  <p class='sub'>{both(f"Every run writes a JSON result plus a Markdown report next to it. {_c('clawperf report results.json')} regenerates the report from any result, and {_c('clawperf compare a.json b.json')} diffs two runs.",
                       f"每次运行都会写一份 JSON 结果与旁边的 Markdown 报告。{_c('clawperf report results.json')} 可从任意结果重新生成报告，{_c('clawperf compare a.json b.json')} 可对比两次运行。")}</p>

  <h2 id='trouble'>{both("Troubleshooting", "故障排查")}</h2>
  <div class='tbl-scroll'><table>
    <thead><tr><th>{both("Symptom", "现象")}</th><th>{both("Fix", "解决")}</th></tr></thead>
    <tbody>{trouble}</tbody>
  </table></div>
  <p class='sub'>{both(f"More detail (including tokenizer backend selection) is in the <a href='{REPO}#troubleshooting'>README</a> and the <a href='{REPO}/blob/main/docs/E2E_TEST_REPORT.md'>E2E test report</a>.",
                       f"更多细节（含 tokenizer 后端选择）见 <a href='{REPO}#troubleshooting'>README</a> 与 <a href='{REPO}/blob/main/docs/E2E_TEST_REPORT.md'>端到端测试报告</a>。")}</p>
</div>"""
    return "reference.html", f"Reference — {total} parameters", sections, body


# ── driver ───────────────────────────────────────────────────────────────────

SAMPLES_DATA: dict = {}

DESCRIPTIONS = {
    "index.html": "ClawPerf benchmarks LLM serving under real agent workloads: seven modes, one CLI.",
    "quickstart.html": "Install ClawPerf, run the default scenario mode and read the output.",
    "configuration.html": "Context profiles, suites, pacing knobs and metrics endpoints.",
    "reference.html": "Every ClawPerf parameter, generated from clawperf --help.",
}


def build_pages() -> dict:
    pages = {}
    for maker in (page_index, page_quickstart, page_configuration, page_reference):
        slug, title, sections, body = maker()
        pages[slug] = (title, sections, body)
    for mode in MODES:
        slug, title, sections, body = mode_page(mode)
        pages[slug] = (title, sections, body)
    return pages


def render_all() -> dict:
    global SAMPLES_DATA
    SAMPLES_DATA = json.loads(SAMPLES.read_text(encoding="utf-8"))
    out = {}
    for slug, (title, sections, body) in build_pages().items():
        desc = DESCRIPTIONS.get(slug, f"{title} — ClawPerf mode documentation.")
        out[slug] = shell(slug, title, body, sections, desc)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if any page is out of date")
    args = ap.parse_args(argv[1:])

    pages = render_all()
    if args.check:
        stale = [slug for slug, text in pages.items()
                 if not (DOCS / slug).is_file()
                 or (DOCS / slug).read_text(encoding="utf-8") != text]
        if stale:
            print("FAIL: out of date — run python scripts/gen_site.py: " + ", ".join(stale))
            return 1
        print(f"site up to date ({len(pages)} pages)")
        return 0

    for slug, text in pages.items():
        path = DOCS / slug
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"  {slug:32s} {len(text):>7,} bytes")
    print(f"wrote {len(pages)} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
