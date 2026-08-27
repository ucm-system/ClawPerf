#!/usr/bin/env bash
# ClawPerf Full Suite — runs the "standard" suite across medium+long profiles.
# Usage: ./full_suite.sh [ENDPOINT] [MODEL]
set -euo pipefail

ENDPOINT="${1:-http://localhost:8000/v1}"
MODEL="${2:-Qwen/Qwen2.5-72B}"

echo "=== ClawPerf Full Suite ==="
echo "Endpoint: $ENDPOINT"
echo "Model:    $MODEL"
echo ""

# The "standard" suite runs users [1,8,16,32] at medium+long context.
# Each (users × profile) combination runs max_turns turns.
clawperf \
    --mode scenario \
    --endpoint "$ENDPOINT" \
    --model "$MODEL" \
    --suite standard \
    --max-turns 20 \
    --output results_suite.json

echo ""
echo "=== Done! ==="
echo "Results:  results_suite.json"
echo "Report:   results_suite.md"
echo ""
echo "Regenerate the report later:"
echo "  clawperf report --input results_suite.json"
