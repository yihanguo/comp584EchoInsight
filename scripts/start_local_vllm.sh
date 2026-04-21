#!/usr/bin/env bash
# Start a local vLLM OpenAI-compatible server on the current compute node.
# Run this INSIDE an srun/salloc shell that holds a GPU.
#
# Default model: DeepSeek-R1-Distill-Qwen-7B.
# Override with env vars, e.g.:
#   MODEL=Qwen/Qwen2.5-3B-Instruct PORT=8000 bash scripts/start_local_vllm.sh
#   MODEL=/scratch/.../snapshots/<hash> TP_SIZE=2 bash scripts/start_local_vllm.sh

set -euo pipefail

MODEL="${MODEL:-deepseek-ai/DeepSeek-R1-Distill-Qwen-7B}"
SERVED_NAME="${SERVED_NAME:-local-llm}"
PORT="${PORT:-8000}"
MAX_LEN="${MAX_LEN:-4096}"
GPU_UTIL="${GPU_UTIL:-0.88}"
TP_SIZE="${TP_SIZE:-1}"
TRUST_REMOTE_CODE="${TRUST_REMOTE_CODE:-1}"
DTYPE="${DTYPE:-auto}"
ENFORCE_EAGER="${ENFORCE_EAGER:-0}"

VLLM_BIN="/scratch/rl182/envs/dl-vllm/bin/vllm"

export HF_HOME="${HF_HOME:-/scratch/rl182/meme/models/hf}"
export HUGGINGFACE_HUB_CACHE="$HF_HOME"
export TRANSFORMERS_CACHE="$HF_HOME"
export VLLM_HOME="${VLLM_HOME:-/scratch/rl182/meme/models/vllm}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/scratch/rl182/cache}"
export PYTHONUNBUFFERED=1

echo "[vllm] host=$(hostname) port=$PORT model=$MODEL served_name=$SERVED_NAME tp_size=$TP_SIZE"
echo "[vllm] Once started, the EchoInsight pipeline can hit http://127.0.0.1:${PORT}/v1"

declare -a args
args=(
    serve "$MODEL"
    --served-model-name "$SERVED_NAME"
    --host 0.0.0.0
    --port "$PORT"
    --max-model-len "$MAX_LEN"
    --gpu-memory-utilization "$GPU_UTIL"
    --tensor-parallel-size "$TP_SIZE"
    --dtype "$DTYPE"
    --disable-log-requests
)

if [[ "$TRUST_REMOTE_CODE" == "1" ]]; then
    args+=(--trust-remote-code)
fi

if [[ "$ENFORCE_EAGER" == "1" ]]; then
    args+=(--enforce-eager)
fi

exec "$VLLM_BIN" "${args[@]}"
