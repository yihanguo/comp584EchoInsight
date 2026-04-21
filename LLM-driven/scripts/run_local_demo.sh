#!/usr/bin/env bash
# One-shot local demo: starts vLLM in background, waits for it to be ready,
# runs the EchoInsight V2 pipeline against it, then tears vLLM down.
#
# Must be run INSIDE an srun/salloc shell that holds a GPU, e.g.:
#   srun --pty --time=2:59:59 --gpus=1 --reservation=classroom --mem=64G $SHELL
#   cd /home/rl182/dl/NLP/project/comp584EchoInsight/LLM-driven
#   bash scripts/run_local_demo.sh
#
# Environment overrides:
#   MODEL=Qwen/Qwen2.5-3B-Instruct    # HF model ID
#   PORT=8000                         # local server port
#   RUN_NAME=local_demo               # output subdir name
#   CSV=data/smoke_input.csv          # input reviews
#   MAX_REVIEWS=10 SAMPLE_SIZE=10 MAX_ITERS=2

set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${MODEL:-deepseek-ai/DeepSeek-R1-Distill-Qwen-7B}"
PORT="${PORT:-8000}"
RUN_NAME="${RUN_NAME:-local_demo}"
CSV="${CSV:-data/smoke_input.csv}"
MAX_REVIEWS="${MAX_REVIEWS:-10}"
SAMPLE_SIZE="${SAMPLE_SIZE:-10}"
MAX_ITERS="${MAX_ITERS:-2}"

LOG=/tmp/echoinsight_vllm_${PORT}.log
echo "[demo] Starting vLLM (log: $LOG)..."

MODEL="$MODEL" PORT="$PORT" SERVED_NAME=local-llm \
    bash scripts/start_local_vllm.sh >"$LOG" 2>&1 &
VLLM_PID=$!
trap 'echo "[demo] Stopping vLLM pid=$VLLM_PID"; kill $VLLM_PID 2>/dev/null || true' EXIT

# Wait for vLLM to be ready (up to 10 minutes for large model loading)
echo "[demo] Waiting for http://127.0.0.1:${PORT}/v1/models ..."
for i in $(seq 1 120); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
        echo "[demo] vLLM ready after ${i}x5s"
        break
    fi
    if ! kill -0 $VLLM_PID 2>/dev/null; then
        echo "[demo] ERROR: vLLM process died. Tail of log:"
        tail -40 "$LOG"
        exit 1
    fi
    sleep 5
done

if ! curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
    echo "[demo] ERROR: vLLM never became ready. Tail of log:"
    tail -40 "$LOG"
    exit 1
fi

echo "[demo] Running EchoInsight V2 pipeline against local-vllm profile..."
python run_v2.py \
    --model local-vllm \
    --run-name "$RUN_NAME" \
    --csv "$CSV" \
    --max-reviews "$MAX_REVIEWS" \
    --sample-size "$SAMPLE_SIZE" \
    --max-iters "$MAX_ITERS"

echo "[demo] Done. Results in results_v2/${RUN_NAME}/"
