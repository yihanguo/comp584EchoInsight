# EchoInsight V2: LLM-Driven Feature Extraction

This branch contains the EchoInsight V2 pipeline. An OpenAI-compatible LLM
endpoint initializes a product-specific feature catalog, then for every
`(review, feature)` pair `ClassifyAgent.classify_one` returns a relevance flag
plus a sentiment score in `[-1.0, 1.0]`. `ValidationAgent` checks whether the
relevant-feature bundle covers the main product-related points in the review.
If validation fails, the failure is sent to `MasterAgent`, which proposes
reusable dynamic features; `ClassifyAgent` classifies only those new features
for the same review, and `ValidationAgent` checks coverage again. The loop is
bounded by `--max-validation-iters`.

Start from this directory (Windows example):

```bash
cd "D:/code/hk/584 nlp hk/project/comp584EchoInsight"
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

- `src/echoinsight/v2_pipeline.py`: orchestration, validation loop, per-review feature loop, output writing, run log
- `src/echoinsight/master_agent.py`: initial feature extraction and validation-driven dynamic feature proposals
- `src/echoinsight/classify_agent.py`: `classify_one(review, feature)` — per-pair relevance + sentiment score
- `src/echoinsight/validation_agent.py`: relevant-feature coverage validation
- `src/echoinsight/feature_fusion.py`: feature score filtering/fusion (phase 2, not invoked by main loop)
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

Credential files are intentionally ignored by git. Use the local `infor_*.md`
format consistently. For Volcengine Ark, create `api/infor_tt.md`:

```text
apikey = YOUR_API_KEY
model = glm-4-7-251222
base_url = https://ark.cn-beijing.volces.com/api/v3
```

For Zhipu BigModel (GLM-4.7), use `api/infor_zhipu.md`:

```text
apikey = YOUR_ZHIPU_API_KEY
model = glm-4.7
base_url = https://open.bigmodel.cn/api/paas/v4
```

For ModelScope, use `api/infor_modelscope.md`:

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
conda run --no-capture-output -n base python -u api/check_glm_api.py --info-path api/infor_tt.md
conda run --no-capture-output -n base python -u api/check_modelscope_api.py --text-only --stream --model deepseek-ai/DeepSeek-R1-Distill-Qwen-7B --text "你好"
```

## Run The Pipeline

Use `--no-capture-output` and `python -u` so terminal progress appears in real
time. The progress log prints one line per `(review, feature)` pair plus a
per-review summary with running pair-rate and ETA:

```text
[V2 HH:MM:SS]   [par 3/40] r2/10 id=1 battery_life: +0.75 t=1.80s
[V2 HH:MM:SS] Review 2/10 id=1 done in 6.4s | relevant=7 pos=5 neg=2 neu=0 errors=0 | rate=2.5 pair/s ETA 0:05:20
```

There is one initial `ClassifyAgent` call per `(review, current global feature)`
pair. If validation fails, the pipeline may add a small number of dynamic
features to the global catalog, classify those new features for the current
review, and use the expanded catalog for all later reviews.

### ValidationAgent and Dynamic Features

Validation is enabled in the main pipeline. It is not a post-processing-only
step. For each review:

```text
MasterAgent initializes feature catalog
-> ClassifyAgent classifies initial features
-> ValidationAgent checks relevant-feature coverage
-> if coverage fails, ValidationAgent suggests one reusable feature
-> MasterAgent turns the suggestion into one catalog feature
-> the accepted feature is appended to the global catalog
-> ClassifyAgent classifies only the new features for the current review
-> ValidationAgent checks coverage again
-> outputs, report, and visualization
```

Validation ignores sentiment direction. A negative battery-life mention covers
`battery_life` just as much as a positive one. Dynamic features mutate the
global feature catalog once accepted by `MasterAgent`; they are classified for
the current review and for future reviews. Earlier reviews are not reprocessed,
because they already passed validation without that feature. Use
`--max-validation-iters` to cap the number of validation passes per review
(default: `2`). `--max-features` caps only the initial catalog size; dynamic
features can grow the final catalog beyond that cap.

### Local parallelism: `--classify-workers`

Feature classification is network-bound, so the per-review feature loop can fan
out to a small `ThreadPoolExecutor`:

- `--classify-workers 1` — **serial** (default). One feature at a time per
  review. Safe for any provider.
- `--classify-workers 3` — up to **3 feature classifications in flight** per
  review. Usually 2–4× faster wall-clock on hosted APIs.
- Keep workers **≤ 5** for hosted APIs. Higher values risk HTTP 429 / timeouts
  and can degrade rather than help. Stop increasing if you see `errors>0` in
  per-review summaries or 429s in the stderr.

Reviews are still processed sequentially; `--classify-workers` only parallelises
the features **inside** one review. Results are re-ordered back to catalog order
before being written, so `feature_map.csv` column order is stable. One feature
failure does not kill the whole review — the failed pair is recorded in
`review_level_diagnostics.jsonl` under `classify_errors` and surfaced in the
per-review summary as `errors=N`.

Observed speedup on the Zhipu (GLM-4.7) smoke (1 review × 5 features):

| `--classify-workers` | per-review wall-clock | speedup |
|---:|---:|---:|
| 1 (serial) | 25.1s | 1× |
| 3 (parallel) | 5.9s | ~4.3× |

### Known-good smoke commands

Serial baseline (Zhipu, 1 review × 5 features, ~30s end-to-end):

```bash
conda run --no-capture-output -n base python -u run_v2.py --csv data/airpod.csv --info api/infor_zhipu.md --model glm-4.7-zhipu --run-name smoke_serial --max-reviews 1 --sample-size 3 --max-features 5 --classify-workers 1
```

Parallel smoke (Zhipu, same payload, workers=3, ~10s end-to-end):

```bash
conda run --no-capture-output -n base python -u run_v2.py --csv data/airpod.csv --info api/infor_zhipu.md --model glm-4.7-zhipu --run-name smoke_parallel --max-reviews 1 --sample-size 3 --max-features 5 --classify-workers 3 --max-validation-iters 2
```

Validation smoke, serial classify:

```bash
conda run --no-capture-output -n base python -u run_v2.py --csv data/airpod.csv --info api/infor_tt.md --model glm-4.7-volcengine --run-name smoke_valid_serial --max-reviews 2 --sample-size 3 --max-features 5 --classify-workers 1 --max-validation-iters 2
```

Validation smoke, local parallel classify:

```bash
conda run --no-capture-output -n base python -u run_v2.py --csv data/airpod.csv --info api/infor_tt.md --model glm-4.7-volcengine --run-name smoke_valid_parallel --max-reviews 2 --sample-size 3 --max-features 5 --classify-workers 3 --max-validation-iters 2
```

Tiny GLM (Volcengine) parallel smoke:

```bash
conda run --no-capture-output -n base python -u run_v2.py --csv data/airpod.csv --info api/infor_tt.md --model glm-4.7-volcengine --run-name airpod_parallel_5 --max-reviews 5 --sample-size 3 --max-features 10 --classify-workers 3
```

Tiny GLM (Volcengine) serial smoke — use this first if you are not sure whether
your provider allows concurrency:

```bash
conda run --no-capture-output -n base python -u run_v2.py --csv data/ipad.csv --info api/infor_tt.md --model glm-4.7-volcengine --run-name ipad_glm_3 --max-reviews 3 --sample-size 3 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000 --classify-workers 1
```

### Larger runs (phase-1 hard caps: reviews ≤ 100, features ≤ 40)

Start with `--classify-workers 3`; only bump to `5` if the smaller smokes
finish with `errors=0`:

```bash
conda run --no-capture-output -n base python -u run_v2.py --csv data/ipad.csv --info api/infor_tt.md --model glm-4.7-volcengine --run-name ipad_glm_100 --max-reviews 100 --sample-size 10 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000 --classify-workers 3
conda run --no-capture-output -n base python -u run_v2.py --csv data/airpod.csv --info api/infor_tt.md --model glm-4.7-volcengine --run-name airpod_glm_100 --max-reviews 100 --sample-size 10 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000 --classify-workers 3
conda run --no-capture-output -n base python -u run_v2.py --csv data/ipad.csv --info api/infor_modelscope.md --model deepseek-r1-7b --run-name ipad_modelscope_100 --max-reviews 100 --sample-size 20 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000 --classify-workers 3
conda run --no-capture-output -n base python -u run_v2.py --csv data/airpod.csv --info api/infor_modelscope.md --model deepseek-r1-7b --run-name airpod_modelscope_100 --max-reviews 100 --sample-size 20 --max-features 40 --chunk-max-reviews 4 --chunk-max-chars 6000 --classify-workers 3
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
| `--classify-workers` | `1` | Threads for per-review feature classify. `1` = serial. Keep ≤ 5 on hosted APIs. |
| `--list-models` | n/a | Print model aliases and exit |

`--max-iters` and `--min-score` have been removed for phase 1. Validation and
dynamic expansion are deferred to phase 2.

## Output Files And Visualizations

Each run writes to `results_v2/<run-name>/`:

| File | Description |
|---|---|
| `initialized_feature_corpus.json` | Initial features extracted from sampled reviews |
| `final_feature_catalog.json` | Final global feature catalog after validation-driven dynamic additions |
| `feature_map.csv` | Review-by-feature continuous sentiment score in `[-1.0, 1.0]` plus metadata (`review_id`, `rating`, `review_preview`) |
| `feature_scores_detail.json` | Per-review, per-feature `{is_relevant, score, evidence_span, reason}` |
| `review_level_diagnostics.jsonl` | One JSON record per review with relevant/positive/negative/neutral feature lists, `classify_errors`, `new_feature_candidates`, and `agent_timing` (`classify_total`, `classify_workers`, `features_classified`, `classify_agent_avg_seconds_per_feature`) |
| `v2_run_log.json` | Metadata (including `classify_workers`), initial/final catalogs, and event log |
| `v2_summary.json` | Review count, initial/final catalog size, avg relevant features/review, `avg_features_per_review`, positive/negative/neutral assignment counts, `classify_error_count`, avg classify seconds per review and per feature, `classify_workers` |
| `report.md` | Human-readable run report (top positive/negative/most-relevant features, per-review highlights) |
| `feature_frequency_stats.csv` | Per-feature relevance counts, positive/negative/neutral counts, avg score when relevant |
| `agent_timing_summary.csv` | Agent-level latency summary (review total, classify total per review, classify per feature) |
| `feature_stats_report.md` | Markdown summary with embedded relevance plot |
| `feature_relevance_top.svg` | Top-N features by number of reviews that discuss them |

Score semantics:

- `score > 0` — positive sentiment about the feature
- `score < 0` — negative sentiment about the feature
- `score == 0` with `is_relevant == true` — neutral mention
- `score == 0` with `is_relevant == false` — feature not discussed

### Validation Outputs

The current pipeline also writes validation and dynamic-feature fields:

- `review_level_diagnostics.jsonl` includes `validation_pass`, `validation_reason`, `validation_confidence`, `suggest_feature`, `new_feature_candidates`, `dynamic_features_added`, `validation_iterations_used`, `validation_iteration_detail`, and validation/master timing under `agent_timing`.
- `v2_summary.json` includes `validation_pass_rate`, `validation_fail_count`, `avg_validation_iterations`, `avg_validation_seconds_per_review`, and dynamic feature counts.
- `report.md` includes a `Validation Summary` plus per-review validation status, suggested feature feedback, and dynamic features added.
- `scripts/summarize_results.py` generates `validation_distribution.svg`, `validation_iteration_distribution.svg`, `agent_latency_summary.svg`, `new_feature_candidate_frequency.svg`, `dynamic_feature_added_frequency.svg`, and `visual_dashboard.html`.

Regenerate validation/statistics visualizations for an existing run:

```bash
conda run --no-capture-output -n base python -u scripts/summarize_results.py --results-dir results_v2/smoke_valid_parallel --top-n 20
```

## Troubleshooting `--classify-workers`

- **`errors>0` in per-review summaries** — one or more feature calls failed.
  The run continues; see `classify_errors` in `review_level_diagnostics.jsonl`
  for the failing feature name + error string. Reduce `--classify-workers` if
  the error is a 429 / timeout / JSON-parse failure.
- **Wall-clock does not drop with more workers** — the provider is either
  rate-limiting or serialising your requests server-side. Drop back to `3` or
  `1`. Also check that `rpm` / `request_delay` in `config/model_registry.json`
  are not artificially capping throughput.
- **`avg_classify_seconds_per_feature` is larger than `classify_total /
  features_classified`** — expected in parallel mode. `avg_...per_feature` is
  the mean of each individual HTTP latency; `classify_total` is the review's
  wall-clock. The gap between them is the parallel speedup.

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
- `api/infor*.md`

`data/` and `results_v2/` are ignored by default because they can be large, but
they can be committed intentionally with `git add -f` for a reproducibility
snapshot.

Example commit commands that include local data/results but exclude API keys:

```bash
git status -sb
git add README.md run_v2.py config/model_registry.json src/echoinsight/classify_agent.py src/echoinsight/v2_pipeline.py api/check_glm_api.py api/check_modelscope_api.py api/check_modelscope_qwen_api.py scripts/finalize_existing_run.py scripts/summarize_results.py
git add -f data results_v2
git reset -- api/infor_tt.md api/infor_modelscope.md api/infor_zhipu.md
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
