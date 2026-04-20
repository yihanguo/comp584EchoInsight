# Revised Semantic GLM Run Instructions

These commands run the approved workflow in `SEMANTIC_GLM_WORKFLOW_PLAN.md`.

The revised workflow now:

- randomly samples reviews before the main processing loop,
- asks GLM to initialize extra feature candidates from that sample,
- rejects GLM features that are semantically equivalent to existing corpus features,
- processes reviews with the expanded corpus,
- calls GLM for failed reviews using `--glm-suggestion-turns`,
- exports available features even if a review still does not pass threshold,
- writes detailed logs to `semantic_glm_run_log.json`.

## Quick Smoke Test

Run this first. It uses a small sample and only two processed reviews, so it should finish quickly.

```bash
cd "/Users/wujinhua/Desktop/COMP584 Final Project"

python run_semantic_glm_continuation.py \
  --input "data/airpods_pipeline_input.csv" \
  --max-reviews 2 \
  --init-sample-size 5 \
  --init-batch-size 5 \
  --init-features-per-batch 4 \
  --glm-suggestion-turns 1 \
  --max-candidates-per-turn 4 \
  --output-dir "results_airpods_semantic_glm_revised_smoke_2" \
  --glm-timeout 100 \
  --glm-rpm 60 \
  --request-delay 0.3 \
  --persist-initialized-corpus false
```

Use `--persist-initialized-corpus false` for smoke tests so quick experiments do not permanently expand `config/dynamic_feature_candidates_glm.json`.

On this machine, `python` points to the miniforge environment that has `requests` installed. If your terminal's `python3` is also the miniforge Python, `python3` is fine too.

## Medium Trial

This is a better sanity check after the smoke test.

```bash
cd "/Users/wujinhua/Desktop/COMP584 Final Project"

python run_semantic_glm_continuation.py \
  --input "data/airpods_pipeline_input.csv" \
  --max-reviews 25 \
  --init-sample-size 100 \
  --init-batch-size 20 \
  --init-features-per-batch 8 \
  --random-seed 584 \
  --glm-suggestion-turns 1 \
  --max-candidates-per-turn 4 \
  --output-dir "results_airpods_semantic_glm_revised_25" \
  --glm-timeout 100 \
  --glm-rpm 60 \
  --request-delay 0.3
```

## Larger AirPods Trial

Use this when the smaller run looks reasonable.

```bash
cd "/Users/wujinhua/Desktop/COMP584 Final Project"

python run_semantic_glm_continuation.py \
  --input "data/airpods_pipeline_input.csv" \
  --max-reviews 100 \
  --init-sample-size 100 \
  --init-batch-size 20 \
  --init-features-per-batch 8 \
  --random-seed 584 \
  --glm-suggestion-turns 1 \
  --max-candidates-per-turn 4 \
  --output-dir "results_airpods_semantic_glm_revised_100" \
  --glm-timeout 100 \
  --glm-rpm 60 \
  --request-delay 0.3
```

## Clean Corpus Trial

Your default dynamic corpus may already contain features from earlier experiments. If you want a cleaner run that starts with only the predefined catalog plus the new initialization sample, point `--dynamic-pool` to a new JSON file:

```bash
cd "/Users/wujinhua/Desktop/COMP584 Final Project"

python run_semantic_glm_continuation.py \
  --input "data/airpods_pipeline_input.csv" \
  --dynamic-pool "config/dynamic_feature_candidates_glm_clean_trial.json" \
  --max-reviews 25 \
  --init-sample-size 100 \
  --init-batch-size 20 \
  --init-features-per-batch 8 \
  --random-seed 584 \
  --glm-suggestion-turns 1 \
  --max-candidates-per-turn 4 \
  --output-dir "results_airpods_semantic_glm_clean_trial_25" \
  --glm-timeout 100 \
  --glm-rpm 60 \
  --request-delay 0.3
```

## Important Parameters

- `--init-sample-size 100`: number of random reviews used before the loop to initialize the GLM feature corpus.
- `--random-seed 584`: makes the random sample reproducible.
- `--init-batch-size 20`: number of sampled reviews sent per GLM initialization prompt.
- `--init-features-per-batch 8`: maximum GLM feature candidates requested per sample batch.
- `--glm-suggestion-turns 1`: number of GLM suggestion rounds for a review that fails threshold. Increase to `2` only if you want more attempts and accept slower runtime.
- `--max-candidates-per-turn 4`: maximum new candidates GLM suggests per failed review turn.
- `--persist-initialized-corpus true`: saves accepted GLM features to `config/dynamic_feature_candidates_glm.json`. Use `false` for throwaway tests.
- `--glm-timeout 100`: timeout for one GLM request.
- `--glm-rpm 60`: caps GLM API traffic at 60 requests per minute, meaning at least 1 second between calls. Lower this to `30` if you still see SSL EOF or rate-limit style failures.

## Output Files

Every run writes these files under the selected output directory:

- `initial_sample_reviews.json`: the random reviews used for GLM initial corpus generation.
- `initialized_feature_corpus.json`: predefined features plus accepted dynamic/GLM features.
- `semantic_active_feature_map_trial.csv`: one row per processed review in scored feature-map format.
- `semantic_active_feature_map_detailed.csv`: detailed readable feature bundles before/after GLM.
- `semantic_glm_run_log.json`: detailed log of GLM calls, equivalence checks, added/rejected features, scores, and final decisions.
- `semantic_support_records.json`: candidate-level equivalence and corpus-addition decision records.
- `semantic_glm_summary.json`: run-level summary.
- `semantic_glm_report.md`: readable sample report.
- `final_active_feature_map.csv`: exported only if every processed review passes the threshold; uses the same scored feature-map format as the trial CSV.

The scored feature-map CSV columns look like:

```text
review_id, rating, text_preview, feature_1, feature_2, ..., threshold, score_before_glm, score_after_glm, passed_final_threshold
```

For each feature column, `0` means the review is not related to that feature. If the review is related, the value is a `0-1` relevance score based on classification confidence, semantic/prototype similarity, and direct evidence hits.

## Inspect Results

```bash
cat "results_airpods_semantic_glm_revised_smoke_2/semantic_glm_summary.json"

python3 -m json.tool \
  "results_airpods_semantic_glm_revised_smoke_2/semantic_glm_run_log.json" | less

head -n 5 \
  "results_airpods_semantic_glm_revised_smoke_2/semantic_active_feature_map_trial.csv"
```

If the run is slow, reduce `--max-reviews`, reduce `--init-sample-size`, or keep `--glm-suggestion-turns 1`.
