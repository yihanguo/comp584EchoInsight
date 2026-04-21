# EchoInsight V2 Develop Plan

## Goal

Implement the new V2 pipeline described in [Design_LLMechoinsight_build_plan.md](/home/rl182/dl/NLP/project/comp584EchoInsight/Design_LLMechoinsight_build_plan.md:1) with a clean parallel code path, without breaking the current heuristic pipeline.

The implementation target is:

- keep the current V1 files for reference and reuse
- add a new V2 agent pipeline
- support one-shot multi-feature LLM classification per review
- keep both:
  - binary feature existence
  - per-feature score

## 1. Preserve Current Data And Reusable Parts

Do not rewrite the current pipeline in place. Create a new V2 file group and reuse only the stable building blocks.

### Keep as-is

- [agents.py](/home/rl182/dl/NLP/project/comp584EchoInsight/src/echoinsight/agents.py:1)
- [pipeline.py](/home/rl182/dl/NLP/project/comp584EchoInsight/src/echoinsight/pipeline.py:1)
- [continuation.py](/home/rl182/dl/NLP/project/comp584EchoInsight/src/echoinsight/continuation.py:1)
- [semantic_qwen_continuation.py](/home/rl182/dl/NLP/project/comp584EchoInsight/src/echoinsight/semantic_qwen_continuation.py:1)

### Reuse directly

- [features.py](/home/rl182/dl/NLP/project/comp584EchoInsight/src/echoinsight/features.py:1)
  For feature schema and catalog loading.
- [qwen_api.py](/home/rl182/dl/NLP/project/comp584EchoInsight/src/echoinsight/qwen_api.py:1)
  For model settings loading, API request handling, JSON parsing, retry behavior.
- existing `data/*.csv`
  For input review corpus.
- existing `config/feature_catalog.json`
  As fallback reference corpus or migration source.

### New V2 files

- `src/echoinsight/master_agent.py`
- `src/echoinsight/classify_agent.py`
- `src/echoinsight/vaiidation_agent.py`
- `src/echoinsight/feature_fusion.py`
- `src/echoinsight/v2_pipeline.py`
- optional(wake for later):
  - `src/echoinsight/sentiment_agent.py`
  - `src/echoinsight/subjectivity_agent.py`

### Output folder strategy

Create a new output root instead of mixing with V1 outputs:

- `results_v2/<run_name>/`

## 2. Data Pipeline

Planned V2 data pipeline:

1. Load review corpus from CSV.
2. `MasterAgent` samples `10-100` reviews for init mode.
3. `MasterAgent` builds the initial fixed feature catalog.
4. For each review:
   - package `review + default_fixed_features`
   - run trained fixed agents if enabled
   - run one-shot LLM classification for all default features
   - fuse outputs into one review bundle
   - run `ValidationAgent`
5. If validation fails:
   - send review + validation feedback back to `MasterAgent`
   - generate dynamic features
   - run classifier again on the new features
   - fuse again
   - validate again
6. Export final review-level outputs and final feature maps.

## 3. Data Passing Format

Use structured JSON-like Python dict contracts between pipeline stages. This is the default handoff format.

### Review input payload

```json
{
  "review_id": "42",
  "rating": 4.0,
  "review_text": "The sound is great but it keeps disconnecting during calls."
}
```

### Master-to-classifier payload

```json
{
  "review_id": "42",
  "review_text": "The sound is great but it keeps disconnecting during calls.",
  "default_fixed_features": [
    {
      "name": "sound_quality",
      "description": "Perceived audio clarity, balance, and listening quality."
    },
    {
      "name": "call_connection_stability",
      "description": "Reliability of connection and continuity during calls."
    }
  ],
  "selected_trained_agents": [
    "sentiment_agent",
    "subjectivity_agent"
  ]
}
```

### One-shot classifier output

```json
[
  {
    "feature": "sound_quality",
    "has_feature": true,
    "feature_score": 0.92,
    "evidence_span": "sound is great",
    "reason": "The review explicitly praises audio quality."
  },
  {
    "feature": "call_connection_stability",
    "has_feature": true,
    "feature_score": 0.87,
    "evidence_span": "keeps disconnecting during calls",
    "reason": "The review explicitly mentions unstable call connection."
  }
]
```

### Validation output

```json
{
  "pass": false,
  "missing_features": [
    {
      "name": "bluetooth_connection_stability",
      "description": "Reliability of Bluetooth pairing and ongoing connection."
    }
  ],
  "reason": "The current bundle misses general Bluetooth stability beyond call quality.",
  "confidence": 0.82
}
```

### Final fused per-review record

```json
{
  "review_id": "42",
  "trained_agent_outputs": {
    "sentiment": "mixed",
    "subjectivity": "subjective"
  },
  "accepted_features": {
    "sound_quality": {
      "has_feature": true,
      "feature_score": 0.92
    },
    "call_connection_stability": {
      "has_feature": true,
      "feature_score": 0.87
    }
  },
  "validation_pass": true,
  "dynamic_features_added": [],
  "iterations_used": 1
}
```

## 4. OOD Design Architecture

Use a small OOD layout with clear single-purpose classes.

### Core classes

- `MasterAgent`
  Owns init feature generation and dynamic feature expansion.
- `ClassifyAgent`
  Runs one-shot multi-feature LLM classification for one review.
- `ValidationAgent`
  Checks whether the current bundle covers the review.
- `FeatureFusion`
  Merges trained-agent outputs, classifier outputs, and dynamic updates.
- `EchoInsightV2Pipeline`
  Orchestrates the whole workflow.

### Suggested responsibilities

- `MasterAgent`
  - sample reviews
  - build initial feature catalog
  - generate dynamic features after validation failure
- `ClassifyAgent`
  - build one prompt for one review plus many features
  - parse JSON list output
  - normalize `has_feature` and `feature_score`
- `ValidationAgent`
  - compare fused feature bundle with review text
  - return only pass/fail plus missing features
- `FeatureFusion`
  - convert classifier outputs into per-review map
  - merge repeated iterations
  - preserve both binary and score values
- `EchoInsightV2Pipeline`
  - file IO
  - loop control
  - max-iteration limit
  - output export

## 5. Agent Prompts

Keep prompts short, strict, and JSON-only.

### MasterAgent init prompt

Purpose:

- extract reusable initial features from sampled reviews

Prompt shape:

```text
You are the master agent in EchoInsight.
Read these sampled customer reviews and extract reusable product-review features.

Rules:
- Return reusable feature names, not one-off phrases.
- Use snake_case names.
- Keep descriptions short and general.
- Avoid duplicates and near-duplicates.
- Return JSON only.
```

### ClassifyAgent prompt

Purpose:

- one review
- many default features
- one LLM call

Prompt shape:

```text
You are the feature classification agent in EchoInsight.
Given one customer review and a list of feature definitions, decide for each feature:
1. whether the feature is present
2. how strongly it is expressed

Rules:
- Judge semantic meaning, not exact word overlap.
- Mark true only if the feature is clearly discussed.
- Give a score in [0,1].
- Return JSON only as a list.
```

### ValidationAgent prompt

Purpose:

- check bundle coverage only

Prompt shape:

```text
You are the validation agent in EchoInsight.
Given the original review and the current feature bundle, decide whether the bundle fully covers the review.

Rules:
- Do not rescore the existing features.
- Only judge whether important reusable features are missing.
- If missing, return the missing reusable feature candidates.
- Return JSON only.
```

### MasterAgent dynamic prompt

Purpose:

- generate missing reusable features after validation failure

Prompt shape:

```text
You are the master agent in EchoInsight.
The current feature bundle does not fully cover this review.
Generate reusable missing features based on the review and validation feedback.

Rules:
- Do not repeat existing features.
- Use reusable catalog-style features.
- Use snake_case names.
- Return JSON only.
```

## 6. Model API And Result Paths

### Model API

Prefer reusing [qwen_api.py](/home/rl182/dl/NLP/project/comp584EchoInsight/src/echoinsight/qwen_api.py:1).

Recommended config source:

- `info.md` or equivalent settings file already used by current Qwen flows

Required settings:

- `apikey`
- `model`
- `base_url`

Known current examples in repo:

- `base_url`: `https://api-inference.modelscope.cn/v1` from [check_modelscope_qwen_api.py](/home/rl182/dl/NLP/project/comp584EchoInsight/check_modelscope_qwen_api.py:18)
- example model: `Qwen/Qwen3.5-35B-A3B` from [check_modelscope_qwen_api.py](/home/rl182/dl/NLP/project/comp584EchoInsight/check_modelscope_qwen_api.py:28)

### Result paths

Recommended V2 output layout:

- `results_v2/<run_name>/initial_sample_reviews.json`
- `results_v2/<run_name>/initialized_feature_corpus.json`
- `results_v2/<run_name>/review_level_diagnostics.json`
- `results_v2/<run_name>/feature_scores_final.json`
- `results_v2/<run_name>/binary_active_feature_map.csv`
- `results_v2/<run_name>/scored_active_feature_map.csv`
- `results_v2/<run_name>/v2_summary.json`

## 7. Inference Strategy And Tunable Hyperparameters

### Local GPU inference mode

For development free of remote rate limits, the pipeline can target a local vLLM server running on a SLURM GPU node.

**Workflow (one-shot, debug reservation):**

```bash
srun --pty --time=2:59:59 --gpus=1 --reservation=classroom --mem=64G $SHELL
cd /home/rl182/dl/NLP/project/comp584EchoInsight/LLM-driven
MAX_REVIEWS=20 RUN_NAME=local_airpods CSV=data/airpods_pipeline_input.csv \
  bash scripts/run_local_demo.sh
```

This starts `/scratch/rl182/envs/dl-vllm/bin/vllm serve` in the background, waits until `/v1/models` responds, runs `run_v2.py --model local-vllm`, and tears down when done.

**Workflow (manual, two terminals):**

- Terminal A (inside srun): `bash scripts/start_local_vllm.sh` — serves model on `http://127.0.0.1:8000/v1`
- Terminal B: `python run_v2.py --model local-vllm --run-name X ...`

Default model: `Qwen/Qwen3.5-9B` (already cached on `/scratch/rl182/meme/models/hf`). Override with `MODEL=Qwen/Qwen2.5-3B-Instruct` to swap smaller. Registry entry `local-vllm` points to `http://127.0.0.1:8000/v1` and is only active inside the srun shell; the model is served under the alias `local-llm`.

### Inference strategy

- use one-shot multi-feature classification for each review
- use low-temperature JSON output
- validate after fusion, not before
- only generate dynamic features when validation fails
- keep a hard cap on backflow iterations
- **thinking/reasoning mode is disabled for all models** — pipeline needs fast deterministic JSON output, not chain-of-thought; set `disable_thinking=true` and `extra_body={"enable_thinking": false}` per model in `config/model_registry.json`

### First-pass recommended settings

- `sample_size_init = 20`
- `max_reviews = 20` for early debugging
- `max_dynamic_iterations = 3`
- `classification_temperature = 0.1`
- `validation_temperature = 0.0`
- `dynamic_generation_temperature = 0.2`
- `min_feature_score_to_keep = 0.5`

### Parameters to tune later

- init sample size: `10-100`
- number of default features kept after init
- score threshold for `has_feature`
- max dynamic iterations
- whether to keep all scored features or only positive features in the fused bundle
- whether to run trained agents on every review or only in debug / full mode

## Implementation Order

1. Add V2 file skeletons.
2. Reuse `qwen_api.py` and `features.py`.
3. Implement `MasterAgent` init mode.
4. Implement one-shot `ClassifyAgent`.
5. Implement `ValidationAgent`.
6. Implement `FeatureFusion`.
7. Implement `EchoInsightV2Pipeline`.
8. Add output writers and run logs.

This is enough to start coding without touching the old pipeline.
