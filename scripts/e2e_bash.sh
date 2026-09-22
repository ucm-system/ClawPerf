#!/usr/bin/env bash
# Verify the SLO shell-quoting trap and its fixes with a REAL bash parser.
# Usage: bash scripts/e2e_bash.sh <mock-port> [clawperf-executable]
#
# Needs a mock server already listening on <mock-port>:
#   clawperf-mock-server --port 18081 --ttft 30 --tpot 2 &
# (On Windows+WSL the executable is .venv/Scripts/clawperf.exe; on Linux just
# `clawperf` from the active environment.)
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

echo "=== argv tokenization (what bash actually hands the program) ==="
set -- --slo ttft.p99<=10000
echo "unquoted '--slo ttft.p99<=10000'  -> argc=$#  args: $(printf '[%s] ' "$@")"
set -- --slo 'ttft.p99<=10000'
echo "quoted   \"--slo 'ttft.p99<=10000'\" -> argc=$#  args: $(printf '[%s] ' "$@")"
set -- --slo ttft.p99:10000
echo "colon    '--slo ttft.p99:10000'   -> argc=$#  args: $(printf '[%s] ' "$@")"
echo

COMMON=(--mode slo --endpoint "http://127.0.0.1:${PORT}/v1/chat/completions"
        --model qwen3-0.6b --tokenizer "$TOK"
        --system-prefix-tokens 200 --user-prefix-tokens 100
        --input-tokens-per-turn 50 --output-tokens-per-turn 16
        --max-context-tokens 4096 --slo-min-users 1 --slo-max-users 2
        --slo-step-turns 1 --no-slo-step-reset-cache)

echo "=== 1. EXACTLY the command that failed for the user (unquoted) ==="
"$EXE" "${COMMON[@]}" --slo ttft.p99<=10000 --output results_e2e/bash_trap.json
echo "exit=$?"
echo

echo "=== 2. quoted symbolic form ==="
"$EXE" "${COMMON[@]}" --slo 'ttft.p99<=10000' --output results_e2e/bash_quoted.json > /tmp/q.log 2>&1
echo "exit=$?  SLO line: $(grep -o 'SLO=.*' /tmp/q.log | head -1)"
echo

echo "=== 3. shell-safe colon form (nothing to quote) ==="
"$EXE" "${COMMON[@]}" --slo ttft.p99:10000 --slo tpot.avg:50 --slo e2e.max:30000 \
    --output results_e2e/bash_colon.json > /tmp/c.log 2>&1
echo "exit=$?  SLO line: $(grep -o 'SLO=.*' /tmp/c.log | head -1)"
echo

echo "=== 4. bare 'ttft.p99' (what the trap leaves behind) ==="
"$EXE" "${COMMON[@]}" --slo ttft.p99 --output results_e2e/bash_bare.json 2>&1 | head -4
