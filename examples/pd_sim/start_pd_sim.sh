#!/bin/bash
# ClawPerf multi-metrics E2E: start two vLLM instances + round-robin proxy.
set -e
OPS=/home/dxlong/ops/clawperf_e2e
mkdir -p $OPS

docker rm -f clawperf-pd-a clawperf-pd-b clawperf-rr 2>/dev/null || true

COMMON="--net=host --shm-size=50g --device /dev/davinci_manager --device /dev/devmm_svm --device /dev/hisi_hdc \
 -v /usr/local/dcmi:/usr/local/dcmi \
 -v /usr/local/Ascend/driver/tools/hccn_tool:/usr/local/Ascend/driver/tools/hccn_tool \
 -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
 -v /usr/local/Ascend/driver/lib64/:/usr/local/Ascend/driver/lib64/ \
 -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info \
 -v /etc/ascend_install.info:/etc/ascend_install.info \
 -v /root/.cache:/root/.cache -v /mnt/model:/mnt/model:ro"

IMG=quay.io/ascend/vllm-ascend:v0.23.0

# Instance A — davinci6, port 9155
docker run -d --name clawperf-pd-a $COMMON -e ASCEND_RT_VISIBLE_DEVICES=0 \
  --device /dev/davinci6 $IMG \
  vllm serve /mnt/model/Qwen3-0.6B --served-model-name qwen3 \
  --tensor-parallel-size 1 --max-model-len 32768 --max-num-batched-tokens 32768 \
  --port 9155 --gpu-memory-utilization 0.85 \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml

# Instance B — davinci7, port 9156
docker run -d --name clawperf-pd-b $COMMON -e ASCEND_RT_VISIBLE_DEVICES=0 \
  --device /dev/davinci7 $IMG \
  vllm serve /mnt/model/Qwen3-0.6B --served-model-name qwen3 \
  --tensor-parallel-size 1 --max-model-len 32768 --max-num-batched-tokens 32768 \
  --port 9156 --gpu-memory-utilization 0.85 \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml

# Round-robin proxy on 9150 (no NPU needed)
docker run -d --name clawperf-rr --net=host -v $OPS:/opt/e2e $IMG \
  python3 /opt/e2e/rr_proxy.py

sleep 2
docker ps --filter name=clawperf --format {{.Names}}\|{{.Status}}
