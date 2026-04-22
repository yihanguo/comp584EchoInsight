# EchoInsight V2: LLM-Driven Feature Extraction

This branch contains the EchoInsight V2 pipeline. The pipeline uses an
OpenAI-compatible LLM endpoint to initialize a product-specific feature catalog,
classify review-level feature evidence, validate coverage, dynamically add
missing features when needed, and export report-ready tables and visualizations.

Start from this directory:

```bash
cd /Users/ryanchris/Desktop/comp584EchoInsight-llm-driven-v2-root
```

## Repository Layout

```text
LLM-driven/
  api/                    API smoke checks
  config/                 model registry and seed feature config
  data/                   input review CSVs
  results_v2/             generated run outputs
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

On this local machine, the project can be run from the conda base environment:

```bash
conda activate base
```

On the Rice cluster, activate the existing environment:

```bash
conda activate /scratch/rl182/envs/echoinsight
```

The code expects Python 3.9+ plus `requests` and `openai`. The visualization
script writes SVG/HTML directly, so `matplotlib` is not required.

## API Credentials

Credential files are intentionally ignored by git. Create one locally, for
example `api/info_glm.md`:

```text
apikey = YOUR_API_KEY
model = glm-4-7-251222
base_url = https://ark.cn-beijing.volces.com/api/v3
```

For ModelScope, use `api/info_modelscope.md`:

```text
apikey = YOUR_MODELSCOPE_TOKEN
model = deepseek-ai/DeepSeek-R1-Distill-Qwen-7B
base_url = https://api-inference.modelscope.cn/v1
```

Model aliases live in `config/model_registry.json`. Print them with:

```bash
python run_v2.py --list-models
```

Thinking/reasoning mode is disabled for pipeline runs through
`config/model_registry.json`. The ModelScope smoke script can display reasoning
only when `--show-reasoning` is passed for debugging.

Quick API checks:

```bash
conda run --no-capture-output -n base python -u api/check_glm_api.py --info-path api/info_glm.md
conda run --no-capture-output -n base python -u api/check_modelscope_api.py --text-only --stream --model deepseek-ai/DeepSeek-R1-Distill-Qwen-7B --text "你好"
```

## Run The Pipeline

Use `--no-capture-output` and `python -u` so terminal progress appears in real
time. The progress log shows each review, active agent, and timing for
`ClassifyAgent`, `ValidationAgent`, and dynamic `MasterAgent` calls.

Tiny GLM smoke run:

```bash
conda run --no-capture-output -n base python -u run_v2.py --csv data/ipad.csv --info api/info_glm.md --model glm-4.7-volcengine --run-name ipad_glm_3 --max-reviews 3 --sample-size 3 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000 --max-iters 1
```

Large GLM runs:

```bash
conda run --no-capture-output -n base python -u run_v2.py --csv data/ipad.csv --info api/info_glm.md --model glm-4.7-volcengine --run-name ipad_glm_100 --max-reviews 100 --sample-size 10 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000 --max-iters 2
conda run --no-capture-output -n base python -u run_v2.py --csv data/airpod.csv --info api/info_glm.md --model glm-4.7-volcengine --run-name airpod_glm_100 --max-reviews 100 --sample-size 10 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000 --max-iters 2
```

Large ModelScope runs:

```bash
conda run --no-capture-output -n base python -u run_v2.py --csv data/ipad.csv --info api/info_modelscope.md --model deepseek-r1-7b --run-name ipad_modelscope_100 --max-reviews 100 --sample-size 20 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000 --max-iters 2
conda run --no-capture-output -n base python -u run_v2.py --csv data/airpod.csv --info api/info_modelscope.md --model deepseek-r1-7b --run-name airpod_modelscope_100 --max-reviews 100 --sample-size 20 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000 --max-iters 2
```

When `--run-name` is omitted, `run_v2.py` creates output folders in the form
`<csv>_<provider>_<max-reviews>`, for example `results_v2/ipad_glm_100/`.
Passing `--run-name` is recommended for named experiments.

## Finalize Existing Runs

If API requests finish but the last reporting/statistics step fails, do not
rerun the expensive LLM calls. Regenerate outputs from existing diagnostics:

```bash
conda run --no-capture-output -n base python -u scripts/finalize_existing_run.py --results-dir results_v2/airpod_glm_100
```

To regenerate statistics and visualizations only:

```bash
conda run --no-capture-output -n base python -u scripts/summarize_results.py --results-dir results_v2/airpod_glm_100 --top-n 25
```

## Main Parameters

| Parameter | Default | Meaning |
|---|---:|---|
| `--csv` | `data/ipad.csv` | Input CSV containing review text and optional rating |
| `--info` | `../info.md` | Local credential file with `apikey`, `model`, `base_url` |
| `--model` | registry default | Model alias from `config/model_registry.json` |
| `--run-name` | auto | Output folder under `results_v2/`; omitted means `<csv>_<provider>_<max-reviews>` |
| `--max-reviews` | `5` | Maximum reviews to process |
| `--sample-size` | `10` | Reviews sampled for initial feature extraction |
| `--max-features` | `40` | Maximum catalog size used in classification prompts |
| `--chunk-max-reviews` | `4` | Maximum reviews per initialization chunk |
| `--chunk-max-chars` | `6000` | Maximum characters per initialization chunk; `0` disables the cap |
| `--max-iters` | `2` | Maximum dynamic feature expansion iterations per review |
| `--min-score` | `0.5` | Minimum score for keeping a feature |
| `--list-models` | n/a | Print model aliases and exit |

## Output Files And Visualizations

Each run writes to `results_v2/<run-name>/`:

| File | Description |
|---|---|
| `initialized_feature_corpus.json` | Initial features extracted from sampled reviews |
| `feature_map.csv` | Review-by-feature binary matrix plus metadata |
| `feature_scores_detail.json` | Per-review feature scores and evidence spans |
| `review_level_diagnostics.jsonl` | One JSON record per processed review, including agent timings |
| `v2_run_log.json` | Metadata, initial catalog, and event log |
| `v2_summary.json` | Review count, pass rate, average iterations, elapsed time |
| `report.md` | Human-readable run report |
| `feature_frequency_stats.csv` | Feature frequency table |
| `feature_origin_stats.csv` | Initial vs dynamic feature contribution |
| `agent_timing_summary.csv` | Agent-level latency summary |
| `agent_timing_detail.csv` | Per-review/per-iteration timing rows |
| `feature_stats_report.md` | Markdown summary with embedded visualizations |
| `visual_dashboard.html` | Browser dashboard for report inspection |
| `*.svg` | Publication-friendly visualizations |

The visualizations include top feature frequencies, initial/dynamic feature
contribution, agent latency, and validation iteration distribution.

## Local vLLM / SLURM Helpers

Use these only when running a local model through SLURM:

```bash
bash scripts/run_v100_local.sh --run-name v100_smoke --csv data/smoke_input.csv
bash scripts/run_debug_vllm.sh --gpus 2 --run-name debug_smoke --csv data/smoke_input.csv
```

Hosted API runs through `glm-4.7-volcengine` or ModelScope do not require
starting vLLM.

## Git Hygiene

Never commit credential files:

- `api/info*.md`

`data/` and `results_v2/` are ignored by default because they can be large, but
they can be committed intentionally with `git add -f` for a reproducibility
snapshot.

Example commit commands that include local data/results but exclude API keys:

```bash
git status -sb
git add README.md run_v2.py config/model_registry.json src/echoinsight/classify_agent.py src/echoinsight/feature_fusion.py src/echoinsight/v2_pipeline.py api/check_glm_api.py api/check_modelscope_api.py api/check_modelscope_qwen_api.py scripts/finalize_existing_run.py scripts/summarize_results.py
git add -f data results_v2
git reset -- api/info_glm.md api/info_modelscope.md
git status -sb
git commit -m "document and package EchoInsight V2 runs"
git push origin llm-driven-v2-root
```

Also avoid committing local machine/cache files:

- `.DS_Store`
- `__pycache__/`
- `.claude/`
- `.nfs*`

These are already covered by the repository `.gitignore`.
