#!/usr/bin/env python3
"""Capture real ClawPerf output into docs/samples.json.

Every sample is the captured stdout+stderr of a command that actually ran:

  * ``clawperf report results_e2e/<x>.json --print`` over the committed results
    (real vLLM-Ascend 910B3 runs), or
  * a live run against the bundled mock server + bundled tokenizer, or
  * a real failure, to document the diagnostic.

The site generator embeds these as themed, copyable code blocks — better than a
screenshot: no binary blobs, selectable text, works in both themes, and it can
never silently disagree with the command shown above it.

Usage:
  python scripts/gen_samples.py            # capture everything
  python scripts/gen_samples.py --check    # re-capture and compare
  python scripts/gen_samples.py slo live-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "samples.json"
RESULTS = ROOT / "results_e2e"
TOK = ROOT / "tokenizers" / "qwen3-0.6b"
BIN = Path(sys.executable).parent
EXT = ".exe" if os.name == "nt" else ""
CLAWPERF = BIN / f"clawperf{EXT}"
MOCK = BIN / f"clawperf-mock-server{EXT}"
MOCK_PORT = 18095

ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
PROGRESS_RE = re.compile(r"^[\w .:\-]*\d+(?:\.\d+)?%\|")


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


def clean(text: str) -> str:
    """Turn a captured stream into what a terminal would actually show."""
    text = ANSI.sub("", text)
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        frame = raw.split("\r")[-1].rstrip()
        if frame.strip() in ("", "Benchmark:"):
            continue
        if re.fullmatch(r"[\s█▏▎▍▌▋▊▉|/\\-]*", frame):
            continue
        if PROGRESS_RE.match(frame.strip()) and lines and PROGRESS_RE.match(lines[-1].strip()):
            lines[-1] = frame  # collapse a redrawn progress bar to its last frame
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


def wrap(text: str, width: int = 118) -> str:
    """Soft-wrap long single-line messages the way a terminal window would."""
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


def display_command(argv: list[str]) -> str:
    """The command as a user would type it (no venv path, no temp files)."""
    shown, skip = [], False
    for i, part in enumerate(argv):
        if skip:
            skip = False
            continue
        if i == 0:
            shown.append("clawperf")
            continue
        if part in ("--tokenizer", "--output") and i + 1 < len(argv):
            shown.append(part)
            nxt = argv[i + 1]
            if part == "--tokenizer":
                shown.append("tokenizers/qwen3-0.6b" if "tokenizers" in nxt else nxt)
            else:
                shown.append("results.json")
            skip = True
            continue
        shown.append(part)
    cmd = " ".join(shown)
    # fold a long command the way a shell shows a continuation
    if len(cmd) > 96:
        words, lines, cur = cmd.split(" "), [], "clawperf"
        for w in words[1:]:
            if len(cur) + len(w) + 1 > 92:
                lines.append(cur + " \\")
                cur = "   "
            cur += " " + w
        lines.append(cur)
        cmd = "\n".join(lines)
    return cmd


def report_sample(result: str) -> tuple[str, str]:
    argv = [str(CLAWPERF), "report", str(RESULTS / result), "--print"]
    return display_command(argv), clean(capture(argv))


def live_scenario(port: int) -> tuple[str, str]:
    argv = [
        str(CLAWPERF), "--mode", "scenario",
        "--endpoint", f"http://127.0.0.1:{port}/v1/chat/completions",
        "--model", "qwen3-0.6b", "--tokenizer", str(TOK),
        "--context-profile", "fresh", "--num-users", "4", "--max-turns", "4",
        "--output-tokens-per-turn", "48",
        "--metrics-endpoint", f"http://127.0.0.1:{port}/metrics", "--reset-cache",
        "--output", str(Path(tempfile.gettempdir()) / "sample_scenario.json"),
    ]
    return display_command(argv), clean(capture(argv, timeout=300))


def live_hitrate(port: int) -> tuple[str, str]:
    argv = [
        str(CLAWPERF), "--mode", "hitrate",
        "--endpoint", f"http://127.0.0.1:{port}/v1/chat/completions",
        "--model", "qwen3-0.6b", "--tokenizer", str(TOK),
        "--num-requests", "60", "--input-len", "4096", "--output-len", "32",
        "--hit-rate", "0.7", "--prefix-num", "2", "--concurrency", "4",
        "--metrics-endpoint", f"http://127.0.0.1:{port}/metrics", "--reset-cache",
        "--output", str(Path(tempfile.gettempdir()) / "sample_hitrate.json"),
    ]
    return display_command(argv), clean(capture(argv, timeout=300))


def shell_safety() -> tuple[str, str]:
    argv = [
        str(CLAWPERF), "--mode", "slo", "--endpoint", "http://localhost:8000/v1",
        "--model", "qwen3", "--slo", "ttft.p99", "--output", "/tmp/x.json",
    ]
    text = clean(capture(argv, timeout=60))
    header = (
        "$ clawperf --mode slo --endpoint http://141.111.32.62:8000/v1 \\\n"
        "    --model /mnt/model/Qwen3.5-0.8B --tokenizer /mnt/model/Qwen3.5-0.8B \\\n"
        "    --slo ttft.p99<=10000 --slo tpot.avg<=50 --slo e2e.max<=30000\n"
        "bash: =10000: No such file or directory\n"
        "        ^ bash treated '<' as a redirection, so ClawPerf never started\n"
        "\n"
        "$ # the same constraints, written so the shell cannot eat them:\n"
        "$ clawperf --mode slo ... --slo ttft.p99:10000 --slo tpot.avg:50 --slo e2e.max:30000\n"
        "\n"
        "$ # and if a bare metric name does reach ClawPerf:\n"
    )
    return "clawperf --mode slo ... --slo ttft.p99", header + text


SAMPLES: list[dict] = [
    {"key": "slo", "title": "clawperf report results_e2e/slo.json --print",
     "note": "Real vLLM-Ascend 910B3 SLO sweep (Qwen3-0.6B, 32K window).",
     "make": lambda port: report_sample("slo.json")},
    {"key": "scenario", "title": "clawperf report results_e2e/scenario.json --print",
     "note": "Real multi-turn long-context run on the same box.",
     "make": lambda port: report_sample("scenario.json")},
    {"key": "hitrate", "title": "clawperf report results_e2e/hitrate.json --print",
     "note": "Real prefix-cache hit-rate measurement.",
     "make": lambda port: report_sample("hitrate.json")},
    {"key": "trace", "title": "clawperf report results_e2e/trace.json --print",
     "note": "KV-cache budget sweep over a real trace.",
     "make": lambda port: report_sample("trace.json")},
    {"key": "agent", "title": "clawperf report results_e2e/agent.json --print",
     "note": "Real tool-calling agent run.",
     "make": lambda port: report_sample("agent.json")},
    {"key": "replay", "title": "clawperf report results_e2e/replay.json --print",
     "note": "A recorded agent session replayed with live history.",
     "make": lambda port: report_sample("replay.json")},
    {"key": "live-run", "title": "clawperf --mode scenario ...  (mock server, no GPU)",
     "note": "A live run: resolved config, pre-flight probe, progress, counters.",
     "make": live_scenario},
    {"key": "live-hitrate", "title": "clawperf --mode hitrate ...  (mock server, no GPU)",
     "note": "The hit-rate mode end to end.",
     "make": live_hitrate},
    {"key": "shell-safety", "title": "clawperf --mode slo ... --slo ttft.p99",
     "note": "The shell-quoting trap, and the diagnostic when a bare metric reaches ClawPerf.",
     "make": lambda port: shell_safety()},
]

SPLITS = {"live-run": ("live-run", "live-tables", "  HBM Prefix Cache (per engine)"),
          "live-hitrate": ("live-hitrate", "live-hitrate-tables", "  HBM Prefix Cache (per engine)")}

# Report-derived samples are pure rendering of committed result files, so a
# fresh capture must match byte for byte. The live runs carry timings.
DETERMINISTIC = {"slo", "scenario", "hitrate", "trace", "agent", "replay", "shell-safety"}


def collect() -> dict:
    needs_mock = any(s["key"].startswith("live-") for s in SAMPLES)
    port = free_port(MOCK_PORT)
    mock = None
    if needs_mock:
        mock = subprocess.Popen([str(MOCK), "--port", str(port), "--ttft", "40", "--tpot", "3"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(f"http://127.0.0.1:{port}/health"):
            mock.terminate()
            raise RuntimeError("the mock server did not come up")
    out: dict = {}
    try:
        for spec in SAMPLES:
            command, text = spec["make"](port)
            text = wrap(text)
            if len(text.splitlines()) < 4:
                raise RuntimeError(f"{spec['key']}: captured only {len(text.splitlines())} lines")
            entries = [(spec["key"], command, text)]
            if spec["key"] in SPLITS:
                first, second, marker = SPLITS[spec["key"]]
                head, _, tail = text.partition(marker)
                if not tail:
                    raise RuntimeError(f"{spec['key']}: split marker {marker!r} not found")
                entries = [(first, command, head.rstrip()),
                           (second, command, (marker + tail).rstrip())]
            for key, cmd, body in entries:
                out[key] = {"title": spec["title"] if key == spec["key"] else spec["title"] + "  (result tables)",
                            "note": spec["note"], "command": cmd, "output": body}
                print(f"  {key:20s} {len(body.splitlines()):>4} lines")
    finally:
        if mock:
            mock.terminate()
            try:
                mock.wait(timeout=10)
            except subprocess.TimeoutExpired:
                mock.kill()
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if samples.json is stale")
    args = ap.parse_args(argv[1:])

    captured = collect()
    payload = {"generator": "scripts/gen_samples.py", "samples": captured}
    rendered = json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True) + "\n"

    if args.check:
        if not OUT.is_file():
            print("FAIL: docs/samples.json is missing — run python scripts/gen_samples.py")
            return 1
        committed = json.loads(OUT.read_text(encoding="utf-8"))["samples"]
        problems = []
        for key, fresh in captured.items():
            old = committed.get(key)
            if old is None:
                problems.append(f"{key}: missing from docs/samples.json")
                continue
            if not old.get("output", "").strip():
                problems.append(f"{key}: committed sample is empty")
            # Report-derived samples are deterministic (pure rendering of a
            # committed result file) — compare them exactly. The live runs carry
            # timings, so only their shape can be checked.
            if key in DETERMINISTIC:
                if old["output"] != fresh["output"]:
                    problems.append(f"{key}: committed output differs from a fresh capture")
                if old["command"] != fresh["command"]:
                    problems.append(f"{key}: committed command differs")
        extra = sorted(set(committed) - set(captured))
        if extra:
            problems.append(f"stale sample keys: {extra}")
        if problems:
            print("FAIL: docs/samples.json is stale — run python scripts/gen_samples.py")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print(f"samples up to date ({len(captured)} blocks, "
              f"{len(DETERMINISTIC & set(captured))} verified exactly)")
        return 0

    OUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(captured)} sample blocks")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
