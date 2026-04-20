# EchoInsight: Semantic GLM Feature-Map Workflow

This branch contains the latest COMP 584 EchoInsight prototype. It implements an agentic customer-review analysis workflow with a main layer, classification layer, validation layer, and GLM-assisted feature expansion loop.

Latest branch:

- `codex/semantic-glm-scored-feature-map`
- https://github.com/yihanguo/comp584EchoInsight/tree/codex/semantic-glm-scored-feature-map

## What This Version Does

EchoInsight turns review text into an active feature map:

1. The system starts from predefined feature definitions in `config/feature_catalog.json`.
2. It randomly samples reviews and asks GLM to suggest additional reusable feature candidates.
3. Each GLM-suggested feature is checked for semantic equivalence against the current feature corpus.
4. Non-duplicate GLM features are added to the current corpus.
5. Each review is evaluated against the current feature corpus by the main, classification, and validation layers.
6. If a review fails the calibrated validation threshold, GLM can suggest one more round of new features for that review.
7. The output active feature map stores a score for every feature-review pair.

Feature-map scores are continuous:

- `0.0` means the review is not classified as related to that feature.
- A value between `0` and `1` means the review is related, with higher values indicating stronger semantic relevance.

The relevance score combines classification confidence, semantic/prototype similarity, and direct evidence hits.

## Important Files

- `run_semantic_glm_continuation.py`: main entry point for the latest semantic GLM workflow.
- `src/echoinsight/semantic_glm_continuation.py`: revised GLM-assisted workflow and scored feature-map export.
- `src/echoinsight/glm_api.py`: GLM API client with thinking disabled and request-per-minute throttling.
- `src/echoinsight/agents.py`: main layer, classification layer, validation layer, and review object.
- `src/echoinsight/features.py`: feature data structure and catalog loader.
- `config/feature_catalog.json`: predefined feature corpus used at initialization.
- `config/dynamic_feature_candidates_glm.json`: dynamic GLM feature corpus.
- `SEMANTIC_GLM_REVISED_RUN_INSTRUCTIONS.md`: detailed run commands and output inspection notes.

Large datasets and generated outputs are intentionally ignored by Git. Keep local review data under `data/`, and write run outputs under `results...` folders.

## GLM Configuration

The GLM client reads API settings from an `info.md` file passed with `--info-path`. The expected keys are:

```text
apikey = ...
model = ...
base_url = ...
```

Do not commit API keys. The repository `.gitignore` excludes generated results folders where local API configuration may live.

## Sample Run

From the project root:

```bash
cd "/Users/wujinhua/Desktop/COMP584 Final Project"

/Users/wujinhua/miniforge3/bin/python run_semantic_glm_continuation.py \
  --input "data/airpods_pipeline_input.csv" \
  --max-reviews 10 \
  --init-sample-size 50 \
  --init-batch-size 20 \
  --init-features-per-batch 8 \
  --glm-suggestion-turns 1 \
  --max-candidates-per-turn 4 \
  --output-dir "results_airpods_scored_glm_10" \
  --persist-initialized-corpus false \
  --glm-rpm 60 \
  --glm-timeout 100
```

If your shell has the correct conda/miniforge environment active, `python` may also work.

## Output Files

The selected output folder contains:

- `semantic_active_feature_map_trial.csv`: scored active feature map for every processed review.
- `final_active_feature_map.csv`: exported only if every processed review passes the threshold.
- `semantic_active_feature_map_detailed.csv`: readable feature bundles before and after GLM expansion.
- `semantic_glm_summary.json`: run summary, threshold, pass count, and exported-file paths.
- `semantic_glm_run_log.json`: detailed log of GLM calls, feature additions/rejections, scores, and pass/fail decisions.
- `initialized_feature_corpus.json`: final initialized feature corpus for the run.
- `initial_sample_reviews.json`: reviews sampled before the processing loop.

Inspect outputs with:

```bash
cat "results_airpods_scored_glm_10/semantic_glm_summary.json"
head -n 5 "results_airpods_scored_glm_10/semantic_active_feature_map_trial.csv"
```

## Older Entrypoints

These scripts are preserved for comparison and earlier prototype stages:

- `run_echoinsight.py`: initial three-layer prototype before backflow.
- `run_echoinsight_continuation.py`: earlier threshold/backflow prototype.

For the latest workflow, use `run_semantic_glm_continuation.py`.
