# Semantic GLM EchoInsight Workflow Plan

This document proposes the revised workflow before implementation. No code changes should proceed until this plan is approved or edited.

## Goal

Revise the current EchoInsight semantic GLM workflow while preserving the existing project structure.

The new workflow should:

1. Randomly sample 100 reviews from the current dataset before the processing loop starts.
2. Use GLM to suggest an initialized feature corpus from those sampled reviews.
3. Add only semantically non-duplicate GLM features to the current feature corpus.
4. Process reviews one by one with the expanded feature corpus.
5. If a review still does not pass the calibrated threshold, call GLM to suggest new features.
6. Before adding any GLM-suggested feature, check whether it is semantically equivalent to any existing feature in the current feature corpus.
7. Only add semantically new features to the corpus.
8. Export available features even when a review still fails threshold.
9. Preserve current active feature map export logic.

## Preserved Existing Structure

The system should continue using:

- `config/feature_catalog.json` as the predefined initial feature catalog.
- `src/echoinsight/glm_api.py` for GLM API calls.
- `src/echoinsight/semantic_glm_continuation.py` for semantic GLM continuation.
- `config/dynamic_feature_candidates_glm.json` as the dynamic GLM feature corpus.
- `semantic_glm_run_log.json` as the structured run log.
- Trial active feature map export for every run.
- Final active feature map export only if all processed reviews pass threshold.

## Revised High-Level Flow

```text
Load dataset
  -> Randomly sample 100 reviews
  -> Ask GLM to suggest reusable features from sampled reviews
  -> Check each GLM feature for semantic equivalence against current corpus
  -> Add non-equivalent GLM features to initialized feature corpus
  -> Process reviews one by one
      -> Match current review against current feature corpus
      -> Build available feature bundle
      -> Compute validation score
      -> If score passes threshold:
           export active feature map row
      -> If score fails threshold:
           keep/export available features anyway
           call GLM for new features
           check semantic equivalence against current corpus
           add only non-equivalent features to corpus
           re-evaluate current review with expanded corpus
           export updated trial row whether pass or fail
```

## Step 1: Dataset Loading

Input remains controlled by terminal arguments:

```bash
--input data/airpods_pipeline_input.csv
--max-reviews 500
```

The framework expects:

```text
rating,text
```

Extra columns may remain in the CSV but are ignored by the review object.

## Step 2: Pre-Loop Random Sampling

Before processing reviews, randomly sample reviews from the dataset.

Default:

```bash
--init-sample-size 100
--random-seed 584
```

If the dataset has fewer than 100 reviews, sample all available reviews.

Save the sampled reviews to:

```text
initial_sample_reviews.json
```

Each sampled item should include:

```json
{
  "review_id": "...",
  "text_preview": "..."
}
```

## Step 3: GLM Initial Feature Corpus Generation

GLM receives the sampled reviews and proposes reusable feature candidates.

Because 100 full reviews may exceed the prompt budget, use batching.

Default:

```bash
--init-batch-size 20
--init-features-per-batch 8
```

Expected GLM output:

```json
[
  {
    "name": "noise_cancellation",
    "description": "Whether customers discuss active noise cancellation or ambient sound blocking.",
    "seed_keywords": ["noise cancellation", "noise cancelling", "ambient", "transparency"],
    "positive_keywords": ["noise cancellation is great", "blocks noise"],
    "negative_keywords": ["too much noise cancellation", "noise cancellation does not work"]
  }
]
```

These are candidate features, not automatically trusted.

## Step 4: Simple Semantic Equivalence Check

For every GLM-suggested feature, check whether it is semantically equivalent to any current feature in the corpus.

The current corpus includes:

1. predefined features from `feature_catalog.json`
2. existing dynamic features from `dynamic_feature_candidates_glm.json`
3. earlier accepted GLM features from this same run

The equivalence check should be simple for now. GLM only needs to return whether the candidate is equivalent or not equivalent.

Suggested output schema:

```json
{
  "equivalent": false,
  "equivalent_feature_name": null,
  "reason": "The candidate focuses on noise cancellation, which is not already represented by the current corpus."
}
```

Decision rule:

```text
If equivalent is true, do not add the feature.
If equivalent is false, add the feature to the current feature corpus.
```

No equivalence score is needed in this version.

## Step 5: Initialized Feature Corpus

The initialized feature corpus for this run becomes:

```text
predefined feature catalog
+ existing dynamic feature corpus
+ non-equivalent GLM features from sampled-review initialization
```

Save this to:

```text
initialized_feature_corpus.json
```

Optionally persist initialized GLM features to:

```text
config/dynamic_feature_candidates_glm.json
```

Suggested default:

```bash
--persist-initialized-corpus true
```

## Step 6: Threshold Calibration

Keep the current rigorous threshold calibration:

```text
hybrid Otsu + positive-score quantile
```

Threshold should be logged in:

```text
semantic_glm_summary.json
semantic_glm_run_log.json
```

## Step 7: Per-Review Matching

For each review, evaluate against the current feature corpus.

The review should produce:

```json
{
  "available_features": [],
  "initial_score": 0.0,
  "threshold": 0.42,
  "passed_initial_threshold": false
}
```

Important rule:

```text
Available features must be exported even if threshold is not passed.
```

## Step 8: If Review Fails Threshold

If the review does not pass threshold:

1. Keep the currently available features.
2. Call GLM to suggest new features.
3. Default to one GLM suggestion turn.
4. Make this adjustable from terminal.

Default:

```bash
--glm-suggestion-turns 1
--max-candidates-per-turn 4
```

This replaces the previous behavior where very high `--max-iterations` could trigger repeated GLM calls for the same review.

## Step 9: Per-Review GLM Feature Addition

For each GLM-suggested feature from the failed review:

1. Check semantic equivalence against the current feature corpus.
2. If equivalent, reject it and log why.
3. If not equivalent, add it to the current corpus.
4. Evaluate whether it helps the current review pass the threshold.

The workflow should maintain per-review sets:

```text
evaluated_candidate_names
rejected_equivalent_candidate_names
accepted_new_candidate_names
```

This prevents repeated validation of candidates like:

```text
product_loyalty
repurchase_intent
repeat_purchase_behavior
replacement_necessity
```

GLM prompts should explicitly include banned names and say:

```text
Do not repeat or paraphrase these previously attempted feature names.
```

## Step 10: Re-Evaluate Current Review

After non-equivalent GLM features are added to the corpus:

1. Re-evaluate the current review.
2. Add semantically fitting features to the active bundle.
3. Recompute final score.
4. Mark pass/fail.

If it still fails:

```text
Do not discard available features.
Export the trial row with available features and failed status.
```

## Step 11: Export Behavior

Always export:

```text
semantic_active_feature_map_trial.csv
semantic_glm_run_log.json
semantic_support_records.json
semantic_glm_summary.json
initialized_feature_corpus.json
initial_sample_reviews.json
```

Export final map only if all processed reviews pass:

```text
final_active_feature_map.csv
```

If some reviews fail, summary should say:

```json
{
  "all_reviews_passed_before_final_active_map": false,
  "final_active_feature_map_exported": false,
  "failed_review_ids": []
}
```

## Step 12: Logging Requirements

The JSON log must record:

- sampled review IDs
- GLM calls for initial corpus generation
- GLM initial feature outputs
- semantic equivalence checks
- initial features added or rejected
- per-review available features before GLM
- per-review score before GLM
- GLM calls for failed reviews
- candidate equivalence decisions
- candidate corpus-add decisions
- candidate active-bundle accept/reject decisions
- score after each accepted candidate
- final pass/fail status

Log file:

```text
semantic_glm_run_log.json
```

## Step 13: Proposed Commands

Small smoke test:

```bash
cd "/Users/wujinhua/Desktop/COMP584 Final Project"

python3 run_semantic_glm_continuation.py \
  --input "data/airpods_pipeline_input.csv" \
  --max-reviews 10 \
  --init-sample-size 100 \
  --random-seed 584 \
  --glm-suggestion-turns 1 \
  --max-candidates-per-turn 4 \
  --output-dir "results_airpods_semantic_glm_revised_10" \
  --glm-timeout 100
```

Larger trial:

```bash
python3 run_semantic_glm_continuation.py \
  --input "data/airpods_pipeline_input.csv" \
  --max-reviews 100 \
  --init-sample-size 100 \
  --random-seed 584 \
  --glm-suggestion-turns 1 \
  --max-candidates-per-turn 4 \
  --output-dir "results_airpods_semantic_glm_revised_100" \
  --glm-timeout 100
```

## Open Questions

Please confirm or edit:

1. Should initialized GLM features be persisted to `config/dynamic_feature_candidates_glm.json` by default?
2. Is `--init-sample-size 100` acceptable as the default?
3. Is `--glm-suggestion-turns 1` the right default?
4. Should final active map still only export when all processed reviews pass?
5. Should semantically equivalent but more specific features be rejected, or allowed as child/subfeatures?

## Implementation Status

This is a plan only. Coding should not proceed until this document is approved or modified.
