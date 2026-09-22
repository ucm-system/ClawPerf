# syntax=docker/dockerfile:1.7
#
# ClawPerf release image — multi-arch (linux/amd64, linux/arm64).
#
#   docker build -t clawperf:local .
#   docker run --rm clawperf:local --help
#   docker run --rm -v "$PWD/results:/app/results" --net=host clawperf:local \
#     --mode scenario --endpoint http://127.0.0.1:8000/v1 --model qwen3 \
#     --output /app/results/run.json
#
# Two stages: the wheel is built with full tooling, then installed into a clean
# runtime image carrying every optional extra except `dev` (no pytest/ruff).

# ── Stage 1: build the wheel ──────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /src
# Only the files the wheel needs — keeps this layer cached across doc/code edits.
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

RUN python -m pip install --upgrade pip build \
 && python -m build --wheel --outdir /dist \
 && python -m zipfile -l /dist/*.whl | head -5

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="ClawPerf" \
      org.opencontainers.image.description="Performance benchmarking for LLM serving backends (vLLM / SGLang / MindIE / vllm-ascend) under real agent workloads" \
      org.opencontainers.image.source="https://github.com/ucm-system/ClawPerf" \
      org.opencontainers.image.url="https://github.com/ucm-system/ClawPerf" \
      org.opencontainers.image.documentation="https://github.com/ucm-system/ClawPerf#readme" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLAWPERF_HISTORY=/app/results/clawperf_history.jsonl

# Install the built wheel with every runtime extra (agent / record / replay /
# mock-server). `dev` is intentionally excluded: no pytest, ruff, or test deps.
# build-essential exists only for this layer — some transitive sdists may need
# to compile on arm64 — and is purged before the layer is committed, so the
# compiler never reaches the final image.
COPY --from=builder /dist/*.whl /tmp/
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential git ca-certificates; \
    whl="$(ls /tmp/*.whl)"; \
    python -m pip install --no-cache-dir "clawperf[agent,record,replay,mock-server] @ file://${whl}"; \
    rm -f /tmp/*.whl; \
    apt-get purge -y --auto-remove build-essential; \
    rm -rf /var/lib/apt/lists/*

# Bundled examples (trace datasets + a local tokenizer) so the documented
# end-to-end commands work inside the container without extra mounts.
COPY examples/ /app/examples/
COPY tokenizers/ /app/tokenizers/

# Non-root runtime user; results land in the writable volume.
RUN useradd --create-home --uid 10001 clawperf \
 && mkdir -p /app/results \
 && chown -R clawperf:clawperf /app

USER clawperf
WORKDIR /app
VOLUME ["/app/results"]

# Build-time sanity check: the CLI must import and print help.
RUN clawperf --help > /dev/null && clawperf-mock-server --help > /dev/null

ENTRYPOINT ["clawperf"]
CMD ["--help"]
