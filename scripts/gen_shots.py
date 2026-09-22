#!/usr/bin/env python3
"""Render real ClawPerf output as terminal screenshots for the docs site.

Nothing here is mocked up by hand: every shot is the captured stdout/stderr of a
command that actually ran, either

  * ``clawperf report <json> --print`` over the committed results in
    ``results_e2e/`` (real vLLM-Ascend 910B3 runs), or
  * a live run against the bundled mock server + bundled tokenizer
    (no GPU needed), or
  * a real failure, to document the diagnostics.

Each capture is rendered into a terminal-window HTML page, *measured in the
browser* (so the frame is exactly as wide/tall as the text needs), and only then
screenshotted with headless Chrome/Edge. The PNG's IHDR is re-read afterwards to
confirm the pixels match the measurement, so a broken render fails loudly.

Usage:
  python scripts/gen_shots.py              # regenerate every shot
  python scripts/gen_shots.py --list       # show what would be generated
  python scripts/gen_shots.py slo hitrate  # regenerate selected shots
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "shots"
RESULTS = ROOT / "results_e2e"
TOK = ROOT / "tokenizers" / "qwen3-0.6b"
BIN = Path(sys.executable).parent
EXT = ".exe" if os.name == "nt" else ""
CLAWPERF = BIN / f"clawperf{EXT}"
MOCK = BIN / f"clawperf-mock-server{EXT}"
MOCK_PORT = 18090

ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
FONT_STACK = ("ui-monospace, SFMono-Regular, Menlo, Consolas, "
              "'DejaVu Sans Mono', 'Liberation Mono', monospace")


# ── Chrome discovery / headless helpers ──────────────────────────────────────

def find_browser() -> str | None:
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def _browser_run(browser: str, args: list[str]) -> subprocess.CompletedProcess:
    base = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions"]
    proc = subprocess.run(base + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    if proc.returncode != 0 and "--headless=new" in base:
        base[1] = "--headless"
        proc = subprocess.run(base + args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
    return proc


def measure(browser: str, page: Path) -> tuple[int, int]:
    """Ask the browser how big the terminal card actually is."""
    proc = _browser_run(browser, ["--dump-dom", page.as_uri()])
    match = re.search(r'<title>(\{.*?\})</title>', proc.stdout, re.DOTALL)
    if not match:
        raise RuntimeError(f"could not measure {page.name}: {proc.stdout[:400]}")
    size = json.loads(html.unescape(match.group(1)))
    return int(size["w"]), int(size["h"])


def screenshot(browser: str, page: Path, out: Path, w: int, h: int, scale: int = 2) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = _browser_run(browser, [
        f"--force-device-scale-factor={scale}",
        f"--window-size={w},{h}",
        f"--screenshot={out}",
        page.as_uri(),
    ])
    if not out.is_file():
        raise RuntimeError(f"screenshot failed for {page.name}: {proc.stderr[:400]}")


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"{path.name} is not a PNG")
    return struct.unpack(">II", head[16:24])


def optimize_png(path: Path) -> None:
    """Shrink the screenshot losslessly-ish.

    Terminal output is a handful of flat colours plus antialiasing, so a 256
    colour palette (no dithering) is visually identical and several times
    smaller — worth it for images that live in git.
    """
    try:
        from PIL import Image
    except ImportError:
        return  # optional dependency; the raw Chrome PNG is still fine
    with Image.open(path) as img:
        quantized = img.convert("RGB").quantize(colors=256, dither=Image.Dither.NONE)
        quantized.save(path, format="PNG", optimize=True)


def verify_png(path: Path) -> str:
    """Cheap sanity check that the screenshot rendered *something*.

    Nobody can eyeball every regenerated shot, so assert the obvious failure
    modes: a blank/white page, or a solid block of colour with no text.
    Returns a one-line summary. Requires Pillow; a no-op without it.
    """
    try:
        from PIL import Image
    except ImportError:
        return "unverified (Pillow not installed)"
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        colors = rgb.getcolors(maxcolors=1 << 24) or []
        total = rgb.width * rgb.height
        colors.sort(reverse=True)
        bg_count, bg = colors[0]
        non_bg = total - bg_count
        frac = non_bg / total
        if frac < 0.005:
            raise RuntimeError(f"{path.name}: looks blank ({frac:.3%} non-background pixels)")
        if frac > 0.75:
            raise RuntimeError(f"{path.name}: looks like a solid block ({frac:.1%} non-background)")
        if len(colors) < 20:
            raise RuntimeError(f"{path.name}: only {len(colors)} distinct colours — no text?")
        return f"bg={bg} ink={frac:.1%} colours={len(colors)}"


# ── Capturing real output ────────────────────────────────────────────────────

def capture(argv: list[str], timeout: int = 600) -> str:
    """Run a command and return stdout+stderr in the order a terminal shows them."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["COLUMNS"] = "200"
    env["NO_COLOR"] = "1"
    proc = subprocess.run(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    return proc.stdout or ""


PROGRESS_RE = re.compile(r"^[\w .:\-]*\d+(?:\.\d+)?%\|")


def clean(text: str) -> str:
    """Turn a captured stream into what a terminal would actually show."""
    text = ANSI.sub("", text)
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        # tqdm redraws with \r: keep the final frame of each progress line.
        frame = raw.split("\r")[-1].rstrip()
        if frame.strip() in ("", "Benchmark:"):
            continue
        if re.fullmatch(r"[\s█▏▎▍▌▋▊▉|/\\-]*", frame):
            continue  # a bare progress bar remnant
        if PROGRESS_RE.match(frame.strip()):
            # Consecutive redraws of the same bar collapse to the last one.
            if lines and PROGRESS_RE.match(lines[-1].strip()):
                lines[-1] = frame
                continue
        lines.append(frame)
    out: list[str] = []
    for line in lines:
        if line.strip() == "" and (not out or out[-1].strip() == ""):
            continue
        out.append(line)
    while out and out[-1].strip() == "":
        out.pop()
    return "\n".join(out)


def wrap(text: str, width: int = 132) -> str:
    """Soft-wrap like a terminal window of *width* columns.

    Real output contains a few very long single-line messages (warnings,
    diagnostics); letting them define the image width would produce a 5000px
    screenshot, so wrap them the way a real terminal does.
    """
    out: list[str] = []
    for line in text.split("\n"):
        if len(line) <= width:
            out.append(line)
            continue
        rest = line
        while len(rest) > width:
            cut = rest.rfind(" ", 0, width)
            if cut < width // 2:
                cut = width
            out.append(rest[:cut])
            rest = "  " + rest[cut:].lstrip()
        out.append(rest)
    return "\n".join(out)


def wait_for(url: str, timeout: float = 30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def free_port(default: int) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", default))
            return default
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


# ── Terminal rendering ───────────────────────────────────────────────────────

def classify(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("$ "):
        return "cmd"
    if "✅" in line or " GOOD" in line:
        return "ok"
    if "❌" in line or "FAIL" in line or "ERROR" in line or "error" in line:
        return "err"
    if "⚠" in line or "WARNING" in line or "Traceback" in line:
        return "warn"
    if line.startswith("[ClawPerf]") or line.startswith("clawperf:"):
        return "err" if "error" in line.lower() else "warn"
    if line.startswith("INFO:clawperf:"):
        return "log"
    if line.startswith("|") or set(stripped) <= set("+-=| "):
        return "table"
    if stripped.startswith("#") or stripped.startswith("##"):
        return "head"
    return ""


def display_command(command: list[str]) -> str:
    """The command as a user would type it (no venv path, no temp files)."""
    shown = []
    skip_next = False
    for i, part in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if i == 0:
            shown.append("clawperf")
            continue
        if part in ("--tokenizer", "--output", "--recording") and i + 1 < len(command):
            shown.append(part)
            nxt = command[i + 1]
            if part == "--tokenizer":
                shown.append("tokenizers/qwen3-0.6b" if "tokenizers" in nxt else nxt)
            elif part == "--output":
                shown.append("results.json")
            else:
                shown.append(nxt)
            skip_next = True
            continue
        shown.append(part)
    return " ".join(shown)


def render_page(title: str, command: list[str], text: str, font_size: int = 13) -> str:
    body = "\n".join(
        f'<span class="{classify(line)}">{html.escape(line)}</span>' if classify(line)
        else html.escape(line)
        for line in text.split("\n")
    )
    prompt = "$ " + display_command(command)
    prompt_html = html.escape(prompt)
    if len(prompt) > 100:  # wrap long commands the way a shell shows them
        parts = prompt.split(" ")
        lines, cur = [], "$"
        for part in parts[1:]:
            if len(cur) + len(part) + 1 > 96:
                lines.append(cur + " \\")
                cur = "   "
            cur += " " + part
        lines.append(cur)
        prompt_html = html.escape("\n".join(lines))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>measuring</title>
<style>
  html, body {{ margin: 0; padding: 0; background: #0b1220; }}
  body {{ padding: 18px; display: inline-block; }}
  .win {{ display: inline-block; border-radius: 12px; overflow: hidden;
          background: #0d1524; border: 1px solid #1e293b;
          box-shadow: 0 18px 50px rgba(0, 0, 0, .45); }}
  .bar {{ display: flex; align-items: center; gap: 8px; padding: 10px 14px;
          background: #131e33; border-bottom: 1px solid #1e293b; }}
  .dot {{ width: 11px; height: 11px; border-radius: 50%; }}
  .r {{ background: #f87171; }} .y {{ background: #fbbf24; }} .g {{ background: #34d399; }}
  .t {{ margin-left: 8px; font: 12px/1 {FONT_STACK}; color: #8b9ab1; letter-spacing: .02em; }}
  pre {{ margin: 0; padding: 14px 18px; font: {font_size}px/1.5 {FONT_STACK};
         color: #dbe6f5; white-space: pre; }}
  .cmd {{ color: #86efac; }}
  .ok {{ color: #4ade80; }} .err {{ color: #f87171; }} .warn {{ color: #fbbf24; }}
  .log {{ color: #7dd3fc; }} .head {{ color: #c4b5fd; }}
  .table {{ color: #b6c2d4; }}
</style></head>
<body><div class="win" id="win">
  <div class="bar"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
    <span class="t">{html.escape(title)}</span></div>
<pre id="out"><span class="cmd">{prompt_html}</span>
{body}</pre>
</div>
<script>
  var win = document.getElementById('win').getBoundingClientRect();
  document.title = JSON.stringify({{w: Math.ceil(win.width) + 36, h: Math.ceil(win.height) + 36}});
</script>
</body></html>
"""


# ── Shot definitions ─────────────────────────────────────────────────────────

def report_shot(result: str, title: str) -> tuple[list[str], str]:
    argv = [str(CLAWPERF), "report", str(RESULTS / result), "--print"]
    return argv, capture(argv)


def live_scenario(port: int) -> tuple[list[str], str]:
    argv = [
        str(CLAWPERF), "--mode", "scenario",
        "--endpoint", f"http://127.0.0.1:{port}/v1/chat/completions",
        "--model", "qwen3-0.6b", "--tokenizer", str(TOK),
        "--context-profile", "fresh", "--num-users", "4", "--max-turns", "4",
        "--output-tokens-per-turn", "48",
        "--metrics-endpoint", f"http://127.0.0.1:{port}/metrics", "--reset-cache",
        "--output", str(Path(tempfile.gettempdir()) / "shot_scenario.json"),
    ]
    return argv, capture(argv, timeout=300)


def live_hitrate(port: int) -> tuple[list[str], str]:
    argv = [
        str(CLAWPERF), "--mode", "hitrate",
        "--endpoint", f"http://127.0.0.1:{port}/v1/chat/completions",
        "--model", "qwen3-0.6b", "--tokenizer", str(TOK),
        "--num-requests", "60", "--input-len", "4096", "--output-len", "32",
        "--hit-rate", "0.7", "--prefix-num", "2", "--concurrency", "4",
        "--metrics-endpoint", f"http://127.0.0.1:{port}/metrics", "--reset-cache",
        "--output", str(Path(tempfile.gettempdir()) / "shot_hitrate.json"),
    ]
    return argv, capture(argv, timeout=300)


def shell_safety_shot() -> tuple[list[str], str]:
    """The exact mistake users hit: an unquoted '<' eaten by the shell."""
    argv = [
        str(CLAWPERF), "--mode", "slo", "--endpoint", "http://localhost:8000/v1",
        "--model", "qwen3", "--slo", "ttft.p99", "--output", "/tmp/x.json",
    ]
    text = capture(argv, timeout=60)
    header = (
        "$ clawperf --mode slo --endpoint http://141.111.32.62:8000/v1 --model /mnt/model/Qwen3.5-0.8B \\\n"
        "    --slo ttft.p99<=10000 --slo tpot.avg<=50 --slo e2e.max<=30000\n"
        "bash: =10000: No such file or directory        <- bash ate the '<' as a redirection\n"
        "\n"
        "$ # same thing, written so the shell cannot eat it:\n"
        "$ clawperf --mode slo ... --slo ttft.p99:10000 --slo tpot.avg:50\n"
        "\n"
        "# and if a bare metric does reach ClawPerf:\n"
    )
    return argv, header + text


SHOTS: list[dict] = [
    {"name": "slo", "title": "clawperf report results_e2e/slo.json  ·  vLLM-Ascend 910B3",
     "caption_en": "A real SLO sweep on an Ascend 910B3 (Qwen3-0.6B, 32K window): "
                   "the capacity curve and the largest concurrency that still met every constraint.",
     "caption_zh": "昇腾 910B3 上的真实 SLO 扫描（Qwen3-0.6B，32K 窗口）：容量曲线，以及仍能满足全部约束的最大并发。",
     "make": lambda port: report_shot("slo.json", "clawperf report · slo")},
    {"name": "scenario", "title": "clawperf report results_e2e/scenario.json  ·  vLLM-Ascend 910B3",
     "caption_en": "Multi-turn long-context scenario on real hardware: TTFT and decode throughput "
                   "as every session's context grows turn by turn.",
     "caption_zh": "真机上的多轮长上下文场景：会话上下文逐轮增长时的 TTFT 与解码吞吐。",
     "make": lambda port: report_shot("scenario.json", "clawperf report · scenario")},
    {"name": "hitrate", "title": "clawperf report results_e2e/hitrate.json  ·  vLLM-Ascend 910B3",
     "caption_en": "Prefix-cache hit rate read from the server's own Prometheus counters: "
                   "TARGET vs MEASURED, plus the speedup the cache actually bought.",
     "caption_zh": "命中率直接读服务端 Prometheus 计数器：目标 vs 实测，以及缓存真实带来的加速比。",
     "make": lambda port: report_shot("hitrate.json", "clawperf report · hitrate")},
    {"name": "trace", "title": "clawperf report results_e2e/trace.json  ·  KV-cache simulation",
     "caption_en": "Budget sweep over a real trace: hit rate against cache size, and where the "
                   "returns flatten out.",
     "caption_zh": "真实 trace 上的预算扫描：命中率随缓存容量的变化，以及收益何时趋于平坦。",
     "make": lambda port: report_shot("trace.json", "clawperf report · trace")},
    {"name": "live-run", "title": "clawperf --mode scenario  ·  live run (mock server)",
     "caption_en": "A run in progress (1/2): the resolved configuration, the pre-flight probe, "
                   "live progress and the headline counters. Mock server, so no GPU is needed.",
     "caption_zh": "运行中的样子（上）：解析后的配置、预检探针、实时进度与总体指标。"
                   "用的是 mock server，无需 GPU。",
     "make": lambda port: live_scenario(port),
     "split_at": "  HBM Prefix Cache (per engine)",
     "split_into": ["live-run", "live-tables"]},
    {"name": "live-tables", "title": "clawperf --mode scenario  ·  result tables (mock server)",
     "caption_en": "The same run (2/2): per-engine prefix-cache breakdown, the latency "
                   "distribution and the per-user summary.",
     "caption_zh": "同一轮运行（下）：逐引擎前缀缓存明细、时延分布与按用户汇总。",
     "make": None},
    {"name": "live-hitrate", "title": "clawperf --mode hitrate  ·  live run (mock server)",
     "caption_en": "The hit-rate mode end to end (1/2): prefill, measure, then TARGET vs MEASURED "
                   "read from the server's own counters.",
     "caption_zh": "hitrate 模式全流程（上）：预填充、测量，然后从服务端计数器读出目标 vs 实测命中率。",
     "make": lambda port: live_hitrate(port),
     "split_at": "  HBM Prefix Cache (per engine)",
     "split_into": ["live-hitrate", "live-hitrate-tables"]},
    {"name": "live-hitrate-tables", "title": "clawperf --mode hitrate  ·  result tables (mock server)",
     "caption_en": "The same hit-rate run (2/2): per-engine cache breakdown and the TTFT/TPOT "
                   "distribution of the measured requests.",
     "caption_zh": "同一轮 hitrate 运行（下）：逐引擎缓存明细，以及被测量请求的 TTFT/TPOT 分布。",
     "make": None},
    {"name": "shell-safety", "title": "clawperf --mode slo  ·  the shell-quoting trap",
     "caption_en": "The failure that started the 0.6.1 round: bash eats '<' as a redirection, so "
                   "ClawPerf never starts — and the diagnostic when a bare metric does reach it.",
     "caption_zh": "0.6.1 那一轮修的就是这个：bash 把 '<' 当重定向吃掉，ClawPerf 根本没启动；"
                   "以及裸指标名真的传进来时的报错提示。",
     "make": lambda port: shell_safety_shot()},
]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("names", nargs="*", help="only regenerate these shots")
    ap.add_argument("--list", action="store_true", help="list the shots and exit")
    ap.add_argument("--keep-html", action="store_true", help="keep the rendered HTML pages")
    args = ap.parse_args(argv[1:])

    if args.list:
        for shot in SHOTS:
            print(f"{shot['name']:14s} {shot['title']}")
        return 0

    browser = find_browser()
    if not browser:
        print("FAIL: no Chrome/Edge found — set CHROME_PATH to regenerate the screenshots.")
        return 1

    selected = [s for s in SHOTS if not args.names or s["name"] in args.names]
    unknown = set(args.names) - {s["name"] for s in SHOTS}
    if unknown:
        print(f"FAIL: unknown shot(s): {', '.join(sorted(unknown))}")
        return 1

    needs_mock = any(s["name"].startswith("live-") for s in selected)
    port = free_port(MOCK_PORT)
    mock = None
    if needs_mock:
        mock = subprocess.Popen(
            [str(MOCK), "--port", str(port), "--ttft", "40", "--tpot", "3"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not wait_for(f"http://127.0.0.1:{port}/health"):
            mock.terminate()
            print("FAIL: the mock server did not come up")
            return 1

    workdir = Path(tempfile.mkdtemp(prefix="clawperf_shots_"))
    failures = []

    def emit(name: str, title: str, command: list[str], text: str) -> None:
        """Render one terminal card, measure it in the browser, screenshot it."""
        lines = text.splitlines()
        if len(lines) < 4:
            failures.append(f"{name}: captured only {len(lines)} lines")
            return
        page = workdir / f"{name}.html"
        page.write_text(render_page(title, command, text), encoding="utf-8")
        w, h = measure(browser, page)
        if not (200 < w < 4000 and 120 < h < 4000):
            failures.append(f"{name}: implausible size {w}x{h}")
            return
        out = OUT_DIR / f"{name}.png"
        screenshot(browser, page, out, w, h)
        pw, ph = png_size(out)
        if (pw, ph) != (w * 2, h * 2):
            failures.append(f"{name}: PNG is {pw}x{ph}, expected {(w * 2, h * 2)}")
            return
        raw_kb = out.stat().st_size / 1024
        optimize_png(out)
        if png_size(out) != (pw, ph):
            failures.append(f"{name}: optimization changed the pixel size")
            return
        try:
            stats = verify_png(out)
        except RuntimeError as exc:
            failures.append(str(exc))
            return
        print(f"  {name:14s} {w:>4}x{h:<4} css -> {pw:>4}x{ph:<4} px  "
              f"{raw_kb:6.1f} -> {out.stat().st_size / 1024:6.1f} KB  "
              f"({len(lines)} lines)  [{stats}]")

    try:
        captured: dict = {}
        for shot in selected:
            if shot["make"] is None:
                continue  # produced by splitting another shot
            command, text = shot["make"](port)
            text = wrap(clean(text))
            captured[shot["name"]] = (command, text)

        for shot in selected:
            name = shot["name"]
            if shot["make"] is not None:
                command, text = captured[name]
                if "split_at" in shot:
                    marker = shot["split_at"]
                    head, _, tail = text.partition(marker)
                    if not tail:
                        failures.append(f"{name}: split marker {marker!r} not found")
                        continue
                    emit(shot["split_into"][0], shot["title"], command, head.rstrip())
                    other = next(s for s in SHOTS if s["name"] == shot["split_into"][1])
                    emit(shot["split_into"][1], other["title"], command,
                         (marker + tail).rstrip())
                else:
                    emit(name, shot["title"], command, text)
            else:
                # A split-off part: emitted by its parent above.
                continue
    finally:
        if mock:
            mock.terminate()
            try:
                mock.wait(timeout=10)
            except subprocess.TimeoutExpired:
                mock.kill()
        if args.keep_html:
            print(f"html kept in {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"wrote {len(selected)} shot(s) to {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
