#!/usr/bin/env bash
# One-command launcher for local debug L40S jobs.
# It submits an srun job on the debug partition, starts a local vLLM server,
# prints allocation success details, and optionally runs the EchoInsight pipeline.
#
# Examples:
#   bash scripts/run_debug_vllm.sh --gpus 2 --run-name airpod_debug_2gpu
#   bash scripts/run_debug_vllm.sh --gpus 1 --mode pipeline --model-alias local-vllm-debug-1xl40s-max
#   bash scripts/run_debug_vllm.sh --gpus 2 --mode serve --port 8001

set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
    cat <<'EOF'
Usage:
  bash scripts/run_debug_vllm.sh [options]

Options:
  --gpus N             Number of debug L40S GPUs to request: 1 or 2. Default: 2
  --mode MODE          "pipeline" to run run_v2.py after vLLM is ready, or "serve" to keep only the server alive. Default: pipeline
  --model MODEL        Override the served model path or Hugging Face repo id
  --model-alias ALIAS  Registry alias passed to run_v2.py. Default depends on --gpus
  --port PORT          Local vLLM port. Default: 8000
  --run-name NAME      Output subdir under results_v2/. Default: debug_local
  --csv PATH           Input CSV for run_v2.py. Default: data/smoke_input.csv
  --max-reviews N      run_v2.py --max-reviews. Default: 10
  --sample-size N      run_v2.py --sample-size. Default: 10
  --max-iters N        run_v2.py --max-iters. Default: 2
  --time HH:MM:SS      SLURM walltime for debug job. Default: 00:30:00
  --mem MEM            SLURM memory request. Default: 64G
  --cpus N             SLURM cpus-per-task. Default: 8
  --max-len N          vLLM max model len. Default: 4096
  --gpu-util X         vLLM gpu-memory-utilization. Default depends on --gpus
  --help               Show this help

Profiles:
  2 GPUs default to the cached /scratch Qwen3.5-35B-A3B snapshot with TP=2.
  1 GPU defaults to the cached /scratch Qwen2.5-32B-Instruct-GPTQ-Int4 snapshot.

Notes:
  - I did not find a cached directory named Qwen3.5-30B under /scratch/rl182.
  - The 2-GPU default therefore uses the cached Qwen3.5-35B-A3B model.
EOF
}

GPUS=2
MODE="pipeline"
MODEL=""
MODEL_ALIAS=""
PORT=8000
RUN_NAME="debug_local"
CSV="data/smoke_input.csv"
MAX_REVIEWS=10
SAMPLE_SIZE=10
MAX_ITERS=2
TIME_LIMIT="00:30:00"
MEMORY="64G"
CPUS=8
MAX_LEN=4096
GPU_UTIL=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --gpus)
            GPUS="$2"
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
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "[debug-vllm] Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ "$GPUS" != "1" && "$GPUS" != "2" ]]; then
    echo "[debug-vllm] --gpus must be 1 or 2" >&2
    exit 1
fi

if [[ "$MODE" != "pipeline" && "$MODE" != "serve" ]]; then
    echo "[debug-vllm] --mode must be pipeline or serve" >&2
    exit 1
fi

if [[ -z "$MODEL" ]]; then
    if [[ "$GPUS" == "2" ]]; then
        MODEL="/scratch/rl182/meme/models/hf/models--Qwen--Qwen3.5-35B-A3B/snapshots/ec2d4ece1ffb563322cbee9a48fe0e3fcbce0307"
    else
        MODEL="/scratch/rl182/meme/models/hf/models--Qwen--Qwen2.5-32B-Instruct-GPTQ-Int4/snapshots/c83e67dfb2664f5039fd4cd99e206799e27dd800"
    fi
fi

if [[ -z "$MODEL_ALIAS" ]]; then
    if [[ "$GPUS" == "2" ]]; then
        MODEL_ALIAS="local-vllm-debug-2xl40s"
    else
        MODEL_ALIAS="local-vllm-debug-1xl40s-max"
    fi
fi

if [[ -z "$GPU_UTIL" ]]; then
    if [[ "$GPUS" == "2" ]]; then
        GPU_UTIL="0.92"
    else
        GPU_UTIL="0.90"
    fi
fi

echo "[debug-vllm] Requesting ${GPUS}x L40S from partition=debug time=${TIME_LIMIT} mem=${MEMORY} cpus=${CPUS}"
echo "[debug-vllm] Selected model=${MODEL}"
echo "[debug-vllm] Selected registry alias=${MODEL_ALIAS}"

SLURM_CMD=$(cat <<EOF
set -euo pipefail
cd "$PWD"
echo "[alloc] SLURM allocation succeeded: job=\${SLURM_JOB_ID:-unknown} host=\$(hostname) gpus=${GPUS} partition=debug"
echo "[alloc] CUDA_VISIBLE_DEVICES=\${CUDA_VISIBLE_DEVICES:-unset}"
echo "[alloc] Querying GPU(s)..."
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

LOG=/tmp/echoinsight_vllm_\${SLURM_JOB_ID:-manual}_${PORT}.log
echo "[vllm] Launch log: \$LOG"

MODEL='$MODEL' \
SERVED_NAME=local-llm \
PORT='${PORT}' \
MAX_LEN='${MAX_LEN}' \
GPU_UTIL='${GPU_UTIL}' \
TP_SIZE='${GPUS}' \
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
        tail -40 "\$LOG"
        exit 1
    fi
    sleep 5
done

if ! curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
    echo "[vllm] ERROR: readiness check timed out. Tail of log:"
    tail -40 "\$LOG"
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
    -p debug \
    --gres="gpu:lovelace:${GPUS}" \
    -N1 \
    -n1 \
    --cpus-per-task="${CPUS}" \
    --mem="${MEMORY}" \
    --time="${TIME_LIMIT}" \
    bash -lc "$SLURM_CMD"
