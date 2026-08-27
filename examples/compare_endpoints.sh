#!/usr/bin/env bash
# ClawPerf Compare — run the same benchmark against two endpoints and compare.
# Usage: ./compare_endpoints.sh [ENDPOINT_A] [ENDPOINT_B] [MODEL]
set -euo pipefail

ENDPOINT_A="${1:-http://localhost:8000/v1}"
ENDPOINT_B="${2:-http://localhost:8001/v1}"
MODEL="${3:-Qwen/Qwen2.5-7B}"

echo "=== ClawPerf Endpoint Comparison ==="
echo "Endpoint A: $ENDPOINT_A"
echo "Endpoint B: $ENDPOINT_B"
echo "Model:      $MODEL"
echo ""

# Run A
echo "--- Running benchmark against Endpoint A ---"
clawperf \
    --mode scenario \
    --endpoint "$ENDPOINT_A" \
    --model "$MODEL" \
    --context-profile medium \
    --num-users 8 \
    --max-turns 10 \
    --output results_a.json \
    --history "" \
    2>&1 | tail -5

# Run B
echo ""
echo "--- Running benchmark against Endpoint B ---"
clawperf \
    --mode scenario \
    --endpoint "$ENDPOINT_B" \
    --model "$MODEL" \
    --context-profile medium \
    --num-users 8 \
    --max-turns 10 \
    --output results_b.json \
    --history "" \
    2>&1 | tail -5

# Compare
echo ""
echo "=== Comparison ==="
clawperf compare results_a.json results_b.json \
    --label-a "Endpoint-A" \
    --label-b "Endpoint-B" \
    --print
