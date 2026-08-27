FROM python:3.12-slim

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project and install
COPY . /app
RUN pip install --no-cache-dir ".[record,replay,agent,dev]"

# Default output directory
RUN mkdir -p /app/results
VOLUME ["/app/results"]

# Default: show help
ENTRYPOINT ["clawperf"]
CMD ["--help"]
