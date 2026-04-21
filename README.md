# EchoInsight V2: LLM-Driven Feature Extraction

This branch contains the rewritten EchoInsight pipeline under `LLM-driven/`.
The V2 pipeline uses an LLM to initialize a product-specific feature catalog,
classify review-level feature evidence, validate coverage, and dynamically add
missing features when needed.

Start from this directory:

```bash
cd /home/rl182/dl/NLP/project/comp584EchoInsight/LLM-driven
```

## Repository Layout

```text
LLM-driven/
  api/                    API smoke checks
  config/                 model registry and seed feature config
  data/                   local input CSVs, ignored by git
  results_v2/             generated run outputs, ignored by git
  scripts/                local vLLM / SLURM launch helpers
  src/echoinsight/        V2 pipeline implementation
  run_v2.py               main entry point
```

Important implementation files:

- `src/echoinsight/v2_pipeline.py`: orchestration, output writing, run log
- `src/echoinsight/master_agent.py`: initial and dynamic feature generation
- `src/echoinsight/classify_agent.py`: review-feature classification
- `src/echoinsight/validation_agent.py`: coverage validation
- `src/echoinsight/feature_fusion.py`: feature score filtering/fusion
- `src/echoinsight/qwen_api.py`: OpenAI-compatible chat client

## Environment

On the Rice cluster, activate the existing environment:

```bash
conda activate /scratch/rl182/envs/echoinsight
```

The code expects Python 3.9+ and common packages such as `requests`. For local
statistics/plots, install `matplotlib` if it is not already available.

## API Credentials

Credential files are intentionally ignored by git. Create one locally, for
example `api/info_volcengine.md`:

```text
apikey = YOUR_API_KEY
model = glm-4-7-251222
base_url = https://ark.cn-beijing.volces.com/api/v3
```

Model aliases live in `config/model_registry.json`. Print them with:

```bash
python run_v2.py --list-models
```

Quick API check:

```bash
python api/check_volcengine_api.py --info api/info_volcengine.md
```

## Quick Smoke Test

Run a tiny end-to-end job:

```bash
python run_v2.py \
  --csv data/smoke_input.csv \
  --info api/info_volcengine.md \
  --model glm-4.7-volcengine \
  --run-name smoke_glm \
  --max-reviews 3 \
  --sample-size 3 \
  --max-iters 1
```

Outputs are written to:

```text
results_v2/smoke_glm/
```

## Reproduce the iPad GLM Run

This is the latest iPad-style run used for result inspection:

```bash
python run_v2.py \
  --csv data/ipad_pipeline_input_500.csv \
  --info api/info_volcengine.md \
  --model glm-4.7-volcengine \
  --run-name ipad_glm_20 \
  --max-reviews 20 \
  --sample-size 5 \
  --max-features 40 \
  --chunk-max-reviews 4 \
  --chunk-max-chars 6000
```

One-line version:

```bash
python run_v2.py --csv data/ipad_pipeline_input_500.csv --info api/info_volcengine.md --model glm-4.7-volcengine --run-name ipad_glm_20 --max-reviews 20 --sample-size 5 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000
```

## Reproduce the AirPods GLM Run

```bash
python run_v2.py \
  --csv data/airpods_pipeline_input_1k.csv \
  --info api/info_volcengine.md \
  --model glm-4.7-volcengine \
  --run-name airpods_glm_10 \
  --max-reviews 10 \
  --sample-size 5 \
  --max-features 40 \
  --chunk-max-reviews 4 \
  --chunk-max-chars 6000
```

## Main Parameters

| Parameter | Default | Meaning |
|---|---:|---|
| `--csv` | `data/smoke_input.csv` | Input CSV containing review text and optional rating |
| `--info` | `../info.md` | Local credential file with `apikey`, `model`, `base_url` |
| `--model` | registry default | Model alias from `config/model_registry.json` |
| `--run-name` | `smoke` | Output folder under `results_v2/` |
| `--max-reviews` | `5` | Maximum reviews to process |
| `--sample-size` | `10` | Reviews sampled for initial feature extraction |
| `--max-features` | `40` | Maximum catalog size used in classification prompts |
| `--chunk-max-reviews` | `4` | Maximum reviews per initialization chunk |
| `--chunk-max-chars` | `6000` | Maximum characters per initialization chunk; `0` disables the cap |
| `--max-iters` | `2` | Maximum dynamic feature expansion iterations per review |
| `--min-score` | `0.5` | Minimum score for keeping a feature |
| `--list-models` | n/a | Print model aliases and exit |

## Output Files

Each run writes to `results_v2/<run-name>/`:

| File | Description |
|---|---|
| `initialized_feature_corpus.json` | Initial features extracted from sampled reviews |
| `feature_map.csv` | Review-by-feature binary matrix plus metadata |
| `feature_scores_detail.json` | Per-review feature scores and evidence spans |
| `review_level_diagnostics.jsonl` | One JSON record per processed review |
| `v2_run_log.json` | Metadata, initial catalog, and event log |
| `v2_summary.json` | Review count, pass rate, average iterations, elapsed time |
| `report.md` | Human-readable run report |

Generated outputs are ignored by git. Keep any result files locally or attach
them separately if needed for a report.

## Optional Result Statistics

For a finished run, feature frequencies can be computed from `feature_map.csv`.
The current `ipad_glm_20` analysis produced:

```text
feature_frequency_stats.csv
feature_origin_stats.csv
feature_frequency_top20.png
feature_stats_report.md
```

These files are generated artifacts under `results_v2/` and are not committed.

## Local vLLM / SLURM Helpers

Use these only when running a local model through SLURM:

```bash
bash scripts/run_v100_local.sh --run-name v100_smoke --csv data/smoke_input.csv
bash scripts/run_debug_vllm.sh --gpus 2 --run-name debug_smoke --csv data/smoke_input.csv
```

Hosted API runs through `glm-4.7-volcengine` are simpler and do not require
starting vLLM.

## Git Hygiene

Do not commit:

- `data/`
- `results_v2/`
- `api/info*.md`
- `.claude/`
- `.nfs*`

These are already covered by the repository `.gitignore`.

