#!/usr/bin/env bash
# ClawPerf Quick Start — a fast smoke test using a small context profile.
# Usage: ./quick_start.sh [ENDPOINT] [MODEL]
set -euo pipefail

ENDPOINT="${1:-http://localhost:8000/v1}"
MODEL="${2:-Qwen/Qwen2.5-7B}"

echo "=== ClawPerf Quick Start ==="
echo "Endpoint: $ENDPOINT"
echo "Model:    $MODEL"
echo ""

clawperf \
    --mode scenario \
    --endpoint "$ENDPOINT" \
    --model "$MODEL" \
    --context-profile fresh \
    --num-users 4 \
    --max-turns 10 \
    --output results_quick.json \
    --verbose

echo ""
echo "=== Done! ==="
echo "Results:  results_quick.json"
echo "Report:   results_quick.md"
