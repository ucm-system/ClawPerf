# PD-Separation Simulation (multi-instance metrics)

Simulates the metrics shape of a **PD-disaggregated** (or plain multi-replica)
serving stack with the smallest possible footprint:

```
client ──► :9150 round-robin proxy ──┬──► vLLM instance A (:9155, davinci6)
                                     └──► vLLM instance B (:9156, davinci7)
                                             each exposes its own /metrics
```

- `start_pd_sim.sh` — starts both vLLM instances (Ascend 910B3, one NPU each)
  plus the proxy container (no NPU needed; aiohttp streaming passthrough).
- `rr_proxy.py` — the round-robin reverse proxy itself.

## Run

```bash
# on the NPU server
bash examples/pd_sim/start_pd_sim.sh   # wait for both instances to be READY

# from the client — one benchmark, metrics aggregated across both instances
clawperf --mode hitrate \
  --endpoint http://<server>:9150/v1 --model qwen3 \
  --metrics-endpoint prefill=http://<server>:9155/metrics \
  --metrics-endpoint decode=http://<server>:9156/metrics \
  --num-requests 40 --input-len 4096 --hit-rate 0.5 --prefix-num 2 \
  --output-len 32 --concurrency 4 --reset-cache
```

The per-engine table shows one row per instance (labelled `prefill:` /
`decode:`) plus a TOTAL row, and `--reset-cache` resets both instances.

## What the E2E run showed

With round-robin routing across two instances with **independent** prefix
caches, the measured hit rate was 47.41% against a 50% target — not the 25%
a naive locality argument predicts. Prefix caches are content-addressed and
lazily filled: each instance caches a prefix the first time it sees it, so
cross-instance routing only costs a **duplicate cold fill** per (prefix,
instance) pair. For real PD deployments this means KV transfer between
instances saves cold-start cost; steady-state reuse is already guaranteed by
content addressing. The per-instance engine table is exactly the tool to
watch this behavior (see `docs/E2E_TEST_REPORT.md` §5.1).

## Teardown

```bash
docker rm -f clawperf-pd-a clawperf-pd-b clawperf-rr
```
