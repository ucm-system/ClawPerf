#!/usr/bin/env bash
# ClawPerf Record & Replay — capture a real agent session, then replay it.
#
# This workflow lets you:
#  1. Record a real agent (Claude Code, OpenClaw, etc.) session as JSONL.
#  2. Replay it against a different model/endpoint to compare performance.
#
# Prerequisites:
#  - Start the recording proxy (this script does step 1).
#  - Point your agent at the proxy (step 2, manual).
#  - Replay the recording against another endpoint (step 3, this script).
set -euo pipefail

UPSTREAM="${1:-http://localhost:8000/v1}"   # the real LLM endpoint
TARGET="${2:-http://localhost:8001/v1}"     # the endpoint to replay against
MODEL="${3:-Qwen/Qwen2.5-7B}"
RECORDING="recordings/session.jsonl"

mkdir -p recordings

echo "=== ClawPerf Record & Replay ==="
echo ""
echo "Step 1: Start the recording proxy"
echo "  Upstream:  $UPSTREAM"
echo "  Proxy:     http://localhost:9090"
echo "  Recording: $RECORDING"
echo ""
echo "  Point your agent at the proxy:"
echo "    export ANTHROPIC_BASE_URL=http://localhost:9090"
echo "    export OPENAI_BASE_URL=http://localhost:9090/v1"
echo "    claude --print 'Fix the bug in main.py'"
echo ""
echo "  When done, press Ctrl+C to stop the proxy."
echo ""

# Start the recording proxy (blocks until Ctrl+C)
clawperf \
    --mode record \
    --upstream-endpoint "$UPSTREAM" \
    --proxy-port 9090 \
    --recording "$RECORDING" \
    --api-key "${CLAWPERF_API_KEY:-}"

echo ""
echo "=== Recording complete ==="
echo "  File: $RECORDING"
echo ""

# Step 3: Replay against the target endpoint
echo "Step 3: Replaying against $TARGET ($MODEL)"
clawperf \
    --mode replay \
    --endpoint "$TARGET" \
    --model "$MODEL" \
    --recording "$RECORDING" \
    --history-mode live \
    --output results_replay.json

echo ""
echo "=== Replay complete ==="
echo "  Results: results_replay.json"
echo "  Report:  results_replay.md"
