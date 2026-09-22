#!/usr/bin/env bash
# Verify the SLO shell-quoting trap and its fixes with a REAL bash parser.
#
# Usage: bash scripts/e2e_bash.sh <mock-port> [clawperf-executable]
#
# Needs a mock server already listening on <mock-port>:
#   clawperf-mock-server --port 18081 --ttft 30 --tpot 2 &
# (On Windows+WSL the executable is .venv/Scripts/clawperf.exe; on Linux just
# `clawperf` from the active environment.)
#
# Exits non-zero when a supported spelling did not work or the unquoted form
# unexpectedly succeeded — this is what CI asserts on.
set -u
PORT="${1:-18081}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
mkdir -p results_e2e
if [ -n "${2:-}" ]; then
    EXE="$2"
elif [ -x ./.venv/Scripts/clawperf.exe ]; then
    EXE=./.venv/Scripts/clawperf.exe      # Windows (WSL interop)
else
    EXE="$(command -v clawperf || echo ./.venv/bin/clawperf)"
fi
# The tokenizer path must be spelled the way the executable's OS sees it.
case "$ROOT" in
    /mnt/[a-zA-Z]/*)  # WSL: /mnt/d/... -> D:/...
        DRIVE="$(printf '%s' "$ROOT" | cut -d/ -f3 | tr '[:lower:]' '[:upper:]')"
        TOK="${DRIVE}:/$(printf '%s' "$ROOT" | cut -d/ -f4-)/tokenizers/qwen3-0.6b" ;;
    *) TOK="$ROOT/tokenizers/qwen3-0.6b" ;;
esac

fail=0
note() { echo "$1"; }

echo "=== argv tokenization (what bash actually hands the program) ==="
set -- --slo ttft.p99<=10000
note "unquoted '--slo ttft.p99<=10000'  -> argc=$#  args: $(printf '[%s] ' "$@")"
set -- --slo 'ttft.p99<=10000'
note "quoted   \"--slo 'ttft.p99<=10000'\" -> argc=$#  args: $(printf '[%s] ' "$@")"
set -- --slo ttft.p99:10000
note "colon    '--slo ttft.p99:10000'   -> argc=$#  args: $(printf '[%s] ' "$@")"
echo

COMMON=(--mode slo --endpoint "http://127.0.0.1:${PORT}/v1/chat/completions"
        --model qwen3-0.6b --tokenizer "$TOK"
        --system-prefix-tokens 200 --user-prefix-tokens 100
        --input-tokens-per-turn 50 --output-tokens-per-turn 16
        --max-context-tokens 4096 --slo-min-users 1 --slo-max-users 2
        --slo-step-turns 1 --no-slo-step-reset-cache)

echo "=== 1. EXACTLY the command that failed for the user (unquoted) ==="
if "$EXE" "${COMMON[@]}" --slo ttft.p99<=10000 --output results_e2e/bash_trap.json; then
    note "FAIL: the unquoted form ran — bash did not treat '<' as a redirection?"
    fail=1
else
    note "OK: the shell ate the operator and ClawPerf never started (as reported)"
fi
echo

echo "=== 2. quoted symbolic form ==="
"$EXE" "${COMMON[@]}" --slo 'ttft.p99<=10000' --output results_e2e/bash_quoted.json > /tmp/q.log 2>&1
rc=$?
note "exit=$rc  SLO line: $(grep -o 'SLO=.*' /tmp/q.log | head -1)"
if [ "$rc" -ne 0 ] || ! grep -q 'SLO=ttft.p99<=10000ms' /tmp/q.log; then
    note "FAIL: the quoted form did not produce the expected SLO line"
    fail=1
fi
echo

echo "=== 3. shell-safe colon form (nothing to quote) ==="
"$EXE" "${COMMON[@]}" --slo ttft.p99:10000 --slo tpot.avg:50 --slo e2e.max:30000 \
    --output results_e2e/bash_colon.json > /tmp/c.log 2>&1
rc=$?
note "exit=$rc  SLO line: $(grep -o 'SLO=.*' /tmp/c.log | head -1)"
for expect in 'ttft.p99<=10000ms' 'tpot.avg<=50ms' 'e2e.max<=30000ms'; do
    if ! grep -q "$expect" /tmp/c.log; then
        note "FAIL: colon form missing $expect"
        fail=1
    fi
done
echo

echo "=== 4. bare 'ttft.p99' (what the trap leaves behind) ==="
"$EXE" "${COMMON[@]}" --slo ttft.p99 --output results_e2e/bash_bare.json > /tmp/b.log 2>&1
if grep -q "shell consumed '<'" /tmp/b.log; then
    note "OK: actionable hint printed"
else
    note "FAIL: no shell-redirect hint in the error"
    fail=1
fi
grep -o 'configuration error.*' /tmp/b.log | head -1 | cut -c1-160
echo

if [ "$fail" -eq 0 ]; then
    note "shell-quoting matrix: all checks passed"
else
    note "shell-quoting matrix: FAILURES above"
fi
exit "$fail"
