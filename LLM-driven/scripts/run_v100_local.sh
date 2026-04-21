#!/usr/bin/env bash
# Single-GPU V100 launcher for EchoInsight.
# Requests one Volta GPU from commons by default, starts a local vLLM server
# with a conservative single-card configuration, then runs the pipeline.

set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
    cat <<'EOF'
Usage:
  bash scripts/run_v100_local.sh [options]

Options:
  --partition NAME     SLURM partition. Default: commons
  --mode MODE          "pipeline" or "serve". Default: pipeline
  --model MODEL        Override model path or Hugging Face repo id
  --model-alias ALIAS  Registry alias for run_v2.py. Default: local-vllm-v100-smoke
  --port PORT          Local port. Default: 8000
  --run-name NAME      Output subdir. Default: v100_local
  --csv PATH           Input CSV. Default: data/smoke_input.csv
  --max-reviews N      Default: 3
  --sample-size N      Default: 3
  --max-iters N        Default: 1
  --time HH:MM:SS      Default: 06:00:00
  --mem MEM            Default: 48G
  --cpus N             Default: 8
  --max-len N          Default: 2048
  --gpu-util X         Default: 0.78
  --dtype TYPE         Default: float16
  --help               Show this help

Defaults:
  - single GPU: gpu:volta:1
  - partition: commons
  - time: 06:00:00
  - model: cached DeepSeek-R1-Distill-Qwen-7B snapshot under /scratch
EOF
}

PARTITION="commons"
MODE="pipeline"
MODEL="/scratch/rl182/meme/models/hf/models--deepseek-ai--DeepSeek-R1-Distill-Qwen-7B/snapshots/916b56a44061fd5cd7d6a8fb632557ed4f724f60"
MODEL_ALIAS="local-vllm-v100-smoke"
PORT=8000
RUN_NAME="v100_local"
CSV="data/smoke_input.csv"
MAX_REVIEWS=3
SAMPLE_SIZE=3
MAX_ITERS=1
TIME_LIMIT="06:00:00"
MEMORY="48G"
CPUS=8
MAX_LEN=2048
GPU_UTIL="0.78"
DTYPE="float16"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --partition)
            PARTITION="$2"
            shift 2
            ;;
        --mode)
            MODE="$2"
            shift 2
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        --model-alias)
            MODEL_ALIAS="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --run-name)
            RUN_NAME="$2"
            shift 2
            ;;
        --csv)
            CSV="$2"
            shift 2
            ;;
        --max-reviews)
            MAX_REVIEWS="$2"
            shift 2
            ;;
        --sample-size)
            SAMPLE_SIZE="$2"
            shift 2
            ;;
        --max-iters)
            MAX_ITERS="$2"
            shift 2
            ;;
        --time)
            TIME_LIMIT="$2"
            shift 2
            ;;
        --mem)
            MEMORY="$2"
            shift 2
            ;;
        --cpus)
            CPUS="$2"
            shift 2
            ;;
        --max-len)
            MAX_LEN="$2"
            shift 2
            ;;
        --gpu-util)
            GPU_UTIL="$2"
            shift 2
            ;;
        --dtype)
            DTYPE="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "[v100-smoke] Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ "$MODE" != "pipeline" && "$MODE" != "serve" ]]; then
    echo "[v100-smoke] --mode must be pipeline or serve" >&2
    exit 1
fi

echo "[v100-smoke] Requesting 1x V100 from partition=${PARTITION} time=${TIME_LIMIT} mem=${MEMORY} cpus=${CPUS}"
echo "[v100-smoke] Selected model=${MODEL}"
echo "[v100-smoke] Selected registry alias=${MODEL_ALIAS}"

SLURM_CMD=$(cat <<EOF
set -euo pipefail
cd "$PWD"
echo "[alloc] SLURM allocation succeeded: job=\${SLURM_JOB_ID:-unknown} host=\$(hostname) gpu=1 partition=${PARTITION}"
echo "[alloc] CUDA_VISIBLE_DEVICES=\${CUDA_VISIBLE_DEVICES:-unset}"
echo "[alloc] Querying GPU(s)..."
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

LOG=/tmp/echoinsight_v100_vllm_\${SLURM_JOB_ID:-manual}_${PORT}.log
echo "[vllm] Launch log: \$LOG"

MODEL='${MODEL}' \
SERVED_NAME=local-llm \
PORT='${PORT}' \
MAX_LEN='${MAX_LEN}' \
GPU_UTIL='${GPU_UTIL}' \
TP_SIZE='1' \
DTYPE='${DTYPE}' \
ENFORCE_EAGER='1' \
bash scripts/start_local_vllm.sh >"\$LOG" 2>&1 &
VLLM_PID=\$!
trap 'echo "[vllm] Stopping pid=\$VLLM_PID"; kill \$VLLM_PID 2>/dev/null || true' EXIT

echo "[vllm] Waiting for http://127.0.0.1:${PORT}/v1/models ..."
for i in \$(seq 1 120); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
        echo "[vllm] Server ready after \${i}x5s on host=\$(hostname) port=${PORT}"
        echo "[vllm] Pipeline profile to use: ${MODEL_ALIAS}"
        break
    fi
    if ! kill -0 \$VLLM_PID 2>/dev/null; then
        echo "[vllm] ERROR: process died before readiness. Tail of log:"
        tail -80 "\$LOG"
        exit 1
    fi
    sleep 5
done

if ! curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
    echo "[vllm] ERROR: readiness check timed out. Tail of log:"
    tail -80 "\$LOG"
    exit 1
fi

if [[ '${MODE}' == 'serve' ]]; then
    echo "[vllm] Serve-only mode active. Keep this job running while you use:"
    echo "       python run_v2.py --model ${MODEL_ALIAS} --run-name ${RUN_NAME}"
    wait \$VLLM_PID
    exit 0
fi

echo "[pipeline] Starting run_v2.py ..."
python run_v2.py \
    --model '${MODEL_ALIAS}' \
    --run-name '${RUN_NAME}' \
    --csv '${CSV}' \
    --max-reviews '${MAX_REVIEWS}' \
    --sample-size '${SAMPLE_SIZE}' \
    --max-iters '${MAX_ITERS}'
EOF
)

srun \
    -p "${PARTITION}" \
    --gres="gpu:volta:1" \
    -N1 \
    -n1 \
    --cpus-per-task="${CPUS}" \
    --mem="${MEMORY}" \
    --time="${TIME_LIMIT}" \
    bash -lc "$SLURM_CMD"
