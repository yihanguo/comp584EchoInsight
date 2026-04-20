# Semantic GLM Continuation Commands

Run a small smoke test first because this path calls the GLM API:

```bash
cd "/Users/wujinhua/Desktop/COMP584 Final Project"
python3 run_semantic_glm_continuation.py \
  --input "data/airpods_pipeline_input.csv" \
  --max-reviews 10 \
  --max-iterations 6 \
  --output-dir "results_airpods_semantic_glm_10"
```

Run a larger trial:

```bash
cd "/Users/wujinhua/Desktop/COMP584 Final Project"
python3 run_semantic_glm_continuation.py \
  --input "data/airpods_pipeline_input.csv" \
  --max-reviews 50 \
  --max-iterations 8 \
  --output-dir "results_airpods_semantic_glm_50"
```

Inspect whether the final active map was exported:

```bash
cat results_airpods_semantic_glm_50/semantic_glm_summary.json
```

If `all_reviews_passed_before_final_active_map` is false, inspect the failed review IDs in the same summary and the trial map:

```bash
head -20 results_airpods_semantic_glm_50/semantic_active_feature_map_trial.csv
```

The final map is only exported when every processed review passes:

```bash
ls results_airpods_semantic_glm_50/final_active_feature_map.csv
```
