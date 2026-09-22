"""Local end-to-end verification of the 0.6.1 fixes.

Reproduces, against a real mock server + a real local tokenizer directory:

  1. SLO mode with the shell-safe syntax (``ttft.p99:10000``) and the quoted
     symbolic syntax (``'ttft.p99<=10000'``).
  2. The mangled form a shell leaves behind (``--slo ttft.p99``) → actionable
     error instead of "No such file or directory".
  3. A server that resets the connection during the pre-flight probe →
     retries, then a clear error naming the cause and ``--no-preflight``.
  4. ``--no-preflight`` on that same server → the run proceeds.
  5. A local tokenizer directory loads strictly offline.

Requires the package installed with its dev extras (mock server + a tokenizer
backend) and the bundled ``tokenizers/qwen3-0.6b`` fixture.

Run:  python scripts/e2e_local.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.dirname(sys.executable)
_EXT = ".exe" if os.name == "nt" else ""
CLAWPERF = os.path.join(BIN, "clawperf" + _EXT)
MOCK = os.path.join(BIN, "clawperf-mock-server" + _EXT)
MOCK_PORT = 18080
RESET_PORT = 18099
TOK = os.path.join(ROOT, "tokenizers", "qwen3-0.6b")
OUT = os.path.join(ROOT, "results_e2e")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def run(args, timeout=300):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([CLAWPERF, *args], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def wait_http(url, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


class ResettingServer(threading.Thread):
    """Accepts a connection then immediately closes it (RST/EOF) — exactly what
    a vLLM instance does while it is still loading its weights."""

    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.listen(16)
        self.hits = 0
        self._stop = False

    def run(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.hits += 1
            # SO_LINGER 0 → RST instead of a clean FIN, the "connection reset
            # by peer" the user hit.
            try:
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                b"\x01\x00\x00\x00\x00\x00\x00\x00")
            except OSError:
                pass
            conn.close()

    def stop(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass


def main():
    os.makedirs(OUT, exist_ok=True)
    mock = subprocess.Popen(
        [MOCK, "--port", str(MOCK_PORT), "--ttft", "30", "--tpot", "2"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_http(f"http://127.0.0.1:{MOCK_PORT}/health"):
            check("mock server starts", False)
            return
        check("mock server starts", True, f"port {MOCK_PORT}")

        base = [
            "--endpoint", f"http://127.0.0.1:{MOCK_PORT}/v1/chat/completions",
            "--model", "qwen3-0.6b",
            "--tokenizer", TOK,
        ]

        # ── 1. Local tokenizer, offline ──────────────────────────────────────
        code, out = run([
            "--mode", "scenario", *base,
            "--system-prefix-tokens", "200", "--user-prefix-tokens", "100",
            "--input-tokens-per-turn", "50", "--output-tokens-per-turn", "16",
            "--max-context-tokens", "4096", "--num-users", "2", "--max-turns", "2",
            "--metrics-endpoint", f"http://127.0.0.1:{MOCK_PORT}/metrics",
            "--output", os.path.join(OUT, "v061_scenario.json"),
        ])
        check("scenario run with local tokenizer dir", code == 0, f"exit={code}")
        check("tokenizer reported as local",
              "Loaded local tokenizer" in out and "local dir" in out,
              next((ln for ln in out.splitlines() if "tokenizer" in ln.lower() and "Loaded" in ln), "")[:120])
        check("no ModelScope hub fallback for a local dir", "Loaded tokenizer from ModelScope" not in out)

        # ── 2. SLO mode: shell-safe and quoted forms ─────────────────────────
        slo_common = [
            "--mode", "slo", *base,
            "--system-prefix-tokens", "200", "--user-prefix-tokens", "100",
            "--input-tokens-per-turn", "50", "--output-tokens-per-turn", "16",
            "--max-context-tokens", "4096",
            "--slo-min-users", "1", "--slo-max-users", "4",
            "--slo-step-strategy", "geometric", "--slo-step-turns", "2",
            "--no-slo-step-reset-cache",
            "--output", os.path.join(OUT, "v061_slo.json"),
        ]
        code, out = run([
            *slo_common,
            "--slo", "ttft.p99:10000", "--slo", "tpot.avg:50", "--slo", "e2e.max:30000",
        ])
        check("slo mode with shell-safe specs (:) runs", code == 0, f"exit={code}")
        check("slo constraints parsed as <=", "ttft.p99<=10000ms" in out and "tpot.avg<=50ms" in out,
              next((ln for ln in out.splitlines() if "ttft.p99" in ln), "")[:120])

        code2, out2 = run([
            *slo_common,
            "--slo", "ttft.p99<=10000,tpot.avg<=50,e2e.max<=30000",  # one quoted arg
        ])
        check("slo mode with one quoted comma-separated spec", code2 == 0, f"exit={code2}")

        # ── 3. The mangled form bash leaves behind ───────────────────────────
        code3, out3 = run([*slo_common, "--slo", "ttft.p99"])
        check("bare 'ttft.p99' fails fast", code3 == 1, f"exit={code3}")
        check("...with the shell-redirect hint",
              "shell consumed '<'" in out3 and "ttft.p99:1500" in out3,
              next((ln for ln in out3.splitlines() if "shell consumed" in ln), "")[:160])

        # ── 4. Connection reset during pre-flight ────────────────────────────
        resetter = ResettingServer(RESET_PORT)
        resetter.start()
        time.sleep(0.5)
        try:
            code4, out4 = run([
                "--mode", "scenario",
                "--endpoint", f"http://127.0.0.1:{RESET_PORT}/v1/chat/completions",
                "--model", "qwen3-0.6b", "--tokenizer", TOK,
                "--system-prefix-tokens", "50", "--user-prefix-tokens", "20",
                "--input-tokens-per-turn", "10", "--output-tokens-per-turn", "4",
                "--max-context-tokens", "2048", "--num-users", "1", "--max-turns", "1",
                "--output", os.path.join(OUT, "v061_reset.json"),
            ], timeout=120)
            check("resetting server fails fast (exit 1)", code4 == 1, f"exit={code4}")
            check("pre-flight retried (>=3 attempts)", resetter.hits >= 3, f"hits={resetter.hits}")
            check("error names the cause + --no-preflight",
                  ("ClientOSError" in out4 or "ConnectionResetError" in out4)
                  and "--no-preflight" in out4,
                  next((ln for ln in out4.splitlines() if "Pre-flight" in ln and "probing" not in ln), "")[:200])
            check("no giant asyncio traceback dumped", "Traceback (most recent call last)" not in out4)

            # ── 5. --no-preflight proceeds ───────────────────────────────────
            code5, out5 = run([
                "--mode", "scenario", "--no-preflight",
                "--endpoint", f"http://127.0.0.1:{RESET_PORT}/v1/chat/completions",
                "--model", "qwen3-0.6b", "--tokenizer", TOK,
                "--system-prefix-tokens", "50", "--user-prefix-tokens", "20",
                "--input-tokens-per-turn", "10", "--output-tokens-per-turn", "4",
                "--max-context-tokens", "2048", "--num-users", "1", "--max-turns", "1",
                "--output", os.path.join(OUT, "v061_nopreflight.json"),
            ], timeout=120)
            check("--no-preflight skips the probe", "skipped (--no-preflight)" in out5
                  or "Pre-flight check skipped" in out5)
            check("--no-preflight run completes (all-error → exit 2)", code5 == 2, f"exit={code5}")
        finally:
            resetter.stop()

        # ── 6. Missing tokenizer path ────────────────────────────────────────
        code6, out6 = run([
            "--mode", "scenario",
            "--endpoint", f"http://127.0.0.1:{MOCK_PORT}/v1/chat/completions",
            "--model", "qwen3-0.6b", "--tokenizer", "/mnt/model/DoesNotExist-0.8B",
            "--num-users", "1", "--max-turns", "1",
            "--output", os.path.join(OUT, "v061_missing_tok.json"),
        ], timeout=120)
        check("missing tokenizer path fails fast", code6 == 1, f"exit={code6}")
        check("...with path + parent listing",
              "does not exist on this machine" in out6, "")

        # ── 7. Result artefacts ──────────────────────────────────────────────
        for f in ("v061_scenario.json", "v061_slo.json"):
            p = os.path.join(OUT, f)
            ok = os.path.isfile(p)
            if ok:
                with open(p, encoding="utf-8") as fh:
                    data = json.load(fh)
                ok = bool(data)
            check(f"{f} written and valid JSON", ok)
    finally:
        mock.terminate()
        try:
            mock.wait(timeout=10)
        except subprocess.TimeoutExpired:
            mock.kill()

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
