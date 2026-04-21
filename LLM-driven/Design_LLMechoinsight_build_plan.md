# EchoInsight V2 Build Plan

## EchoInsight V2 Result Sketch

```text
                 +-----------------------------+
                 |  User Review Corpus         |
                 |  AirPods reviews            |
                 +-------------+---------------+
                               |
                               v
                 +-----------------------------+
                 |  Master Agent               |
                 |  init mode                  |
                 |  sample 10-100 reviews      |
                 |  build init feature map     |
                 +-------------+---------------+
                               |
                               v
                 +-----------------------------+
                 |  Top-k / Init Feature Map   |
                 |  feature1 ... featureN      |
                 +-------------+---------------+
                               |
                               v
                 +-----------------------------+
                 |  Fixed Agent Pool           |
                 |  A. trained agents          |
                 |     sentiment               |
                 |     subjective/objective    |
                 |  B. LLM feature classifier  |
                 |     feature existence       |
                 |     feature score           |
                 +-------------+---------------+
                               |
                               v
                 +-----------------------------+
                 |  Feature Fusion             |
                 |  per-review feature bundle  |
                 |  has_feature + score        |
                 +-------------+---------------+
                               |
                               v
                 +-----------------------------+
                 |  Validation Agent           |
                 |  coverage only              |
                 |  are any features missing?  |
                 +-------------+---------------+
                               |
                    pass?      |
                   /     \     
                 yes      no
                  |        |
                  v        v
   +----------------------+  +-----------------------------+
   | Actionable Feature   |  | Master Agent               |
   | Map Output           |  | generate dynamic features  |
   | binary + scores      |  | from uncovered review      |
   +----------------------+  +-------------+---------------+
                                            |
                                            v
                              +-----------------------------+
                              |  New Classifier Agents      |
                              |  score new dynamic features |
                              +-------------+---------------+
                                            |
                                            v
                              +-----------------------------+
                              |  Back to Validation         |
                              |  until covered or stop      |
                              +-----------------------------+
```

## Goal

Build a V2 architecture centered on one `Master Agent`, one `Fixed Agent Pool`, and one lightweight `Validation Agent`.

Target direction:

- `Master Agent` handles initialization and feature expansion
- `Fixed Agent Pool` handles stable per-review analysis
- `Validation Agent` checks only coverage, not complex score aggregation
- final output keeps both:
  - whether a feature exists in a review
  - the score or strength of that feature

Expected final output:

- a reusable feature inventory
- per-review binary feature presence
- per-review feature scores
- additional signals from trained agents such as sentiment and subjective vs objective
- a final actionable feature map

## V2 Pipeline Snapshot

Planned V2 flow:

1. `Master Agent Init`
   - sample `10-100` reviews from the corpus
   - extract and normalize initial reusable features
   - build the initial feature map

2. `Fixed Agent Pool`
   - run trained agents for stable auxiliary signals
   - run LLM feature classifier for feature existence and feature score

3. `Feature Fusion`
   - combine the outputs from the fixed pool
   - produce one fused per-review feature bundle

4. `Validation Agent`
   - check only whether the current feature bundle covers the review
   - if not, identify what is missing

5. `Dynamic Backflow`
   - return to `Master Agent`
   - generate dynamic reusable features for the uncovered review
   - send those new features to classifier agents
   - re-run fusion and validation

6. `Final Outputs`
   - actionable feature map
   - binary presence matrix
   - feature score matrix
   - review-level diagnostics

## Why This Version

This version is easier to reason about because each component has one clear job:

- `Master Agent`: create and expand the feature space
- `Fixed Agent Pool`: analyze each review against a stable set of analyzers
- `Validation Agent`: only decide completeness of coverage

Compared with the previous mixed design, this version is closer to your diagrams:

- the top layer creates the feature map
- the middle layer scores reviews against that map
- the validator only asks whether the map is enough
- feature expansion happens only when validation says the review is not covered

## Proposed V2 Architecture

## 1. Master Agent

### Purpose

The `Master Agent` owns the feature space.

It has three responsibilities:

1. initialize the first feature map from sampled reviews
2. pass the default fixed feature set to the classifier layer for each new review
3. generate dynamic new features when validation says coverage is incomplete

### Input

- full review corpus
- sample size between `10` and `100`
- one newly entered review
- failed validation feedback for dynamic expansion

### Init process

1. sample a subset of reviews
2. ask the LLM to extract reusable product-review features
3. normalize names and descriptions
4. merge semantically equivalent features
5. store the initial feature catalog

### Review routing process

1. receive one new review
2. load the current default fixed feature inventory
3. package the review plus default features into one structured payload
4. dispatch that payload to the fixed agent pool

### Dynamic process

1. receive a review that failed validation
2. inspect the uncovered aspects
3. generate reusable missing features
4. return those features to the classifier side

### Expected output

Suggested feature schema:

```json
{
  "name": "battery_life",
  "description": "User comments about duration of use, charging frequency, or power longevity.",
  "examples": [
    "battery lasts all day",
    "dies too quickly"
  ],
  "source": "master_agent"
}
```

### Recommended agent

Suggested file:

- `src/echoinsight/master_agent.py`

Suggested class:

- `MasterAgent`

Suggested methods:

1. `sample_reviews(reviews, sample_size) -> list[ReviewRecord]`
2. `extract_initial_features(sampled_reviews) -> list[dict]`
3. `dedupe_features(features) -> list[dict]`
4. `build_initial_catalog(...) -> list[dict]`
5. `route_review(review, feature_catalog) -> dict`
6. `generate_dynamic_features(review, validation_feedback, existing_features) -> list[dict]`

### Recommended routing contract

The cleanest handoff format is structured JSON.

Reason:

- easier to log
- easier to replay
- easier to debug
- easier to pass between agents and pipeline stages

Suggested routing payload:

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
  ],
  "routing_reason": "Pass the review and the current default fixed feature set to the fixed agent pool for one-shot scoring."
}
```

This is better than a looser text-only handoff because the next layer can directly consume:

- `default_fixed_features`
- `selected_trained_agents`
- `review_text`

without additional parsing.

### Design notes

- feature names should be stable and normalized, ideally snake_case
- descriptions should stay reusable and not overfit to a single review
- init mode should be rerunnable so you can compare different sampling strategies
- routing should stay simple and lightweight
- the master agent should pass structured JSON to sub agents whenever possible
- dynamic features should stay reusable, not review-specific

## 2. Fixed Agent Pool

### Purpose

The `Fixed Agent Pool` is the stable analysis layer.

It should contain two parts:

1. trained agents you already have
2. LLM-based feature classification agents

### Pool composition

#### A. Trained agents

These are fixed non-generative or already-trained models:

- sentiment agent
- subjective vs objective agent

These outputs are stable side signals and do not need to be regenerated as features.

#### B. LLM feature classifier agents

This layer receives the default feature set from the `Master Agent` and scores the whole set in one LLM call for each review.

Core question:

- "For this review, which of these features are present, and what is each feature's score?"

Unlike validation, this layer focuses on feature detection and scoring only.

### Input

- one review
- current feature inventory from `Master Agent`

### Process

For each review:

1. run the trained agents:
   - sentiment
   - subjective vs objective
2. send the review and the default feature set in one prompt to the LLM classifier
3. ask the LLM classifier to return results for all listed features
4. return both:
   - binary presence
   - feature score
5. send everything to a fusion step

### Suggested classification schema

```json
[
  {
    "feature": "battery_life",
    "has_feature": true,
    "feature_score": 0.88,
    "evidence_span": "battery lasts almost two days",
    "reason": "The review explicitly mentions strong battery duration."
  },
  {
    "feature": "comfort_fit",
    "has_feature": false,
    "feature_score": 0.12,
    "evidence_span": "",
    "reason": "The review does not clearly discuss comfort or fit."
  }
]
```

### Suggested trained-agent schema

```json
{
  "sentiment": "positive",
  "subjectivity": "subjective"
}
```

### Recommended agents

Suggested files:

- `src/echoinsight/classify_agent.py`
- `src/echoinsight/sentiment_agent.py`
- `src/echoinsight/subjectivity_agent.py`

Suggested classes:

- `ClassifyAgent`
- `SentimentAgent`
- `SubjectivityAgent`

Suggested methods:

1. `classify_review(review, features) -> list[dict]`
2. `_build_classification_prompt(...) -> str`
3. `_parse_classification_response(...) -> list[dict]`

### Recommended prompt shape

```text
You are the feature classification agent in EchoInsight.
Given one customer review and a list of feature definitions, decide for each feature whether it is present in the review and how strongly it is expressed.

Rules:
- Judge semantic meaning, not exact word overlap.
- For each feature, mark true only if the feature is actually discussed.
- Ignore weak or ambiguous hints.
- Return JSON only.
```

### Design notes

- this stage should be deterministic in output format, even if semantic judgment is LLM-based
- use one LLM call to score multiple default features for the same review to save tokens
- the main output here is dual:
  - `has_feature`
  - `feature_score`
- trained-agent outputs should stay separate from feature-scoring outputs until fusion

## 3. Validation Agent

### Purpose

Validation should only check coverage.

It should not be responsible for detailed feature scoring.

### Core question

Given:

- the original review
- the current accepted feature bundle

Ask:

- "Does the current feature bundle already cover the review, or are there missing reusable features?"

### Output

Suggested schema:

```json
{
  "pass": false,
  "missing_features": [
    {
      "name": "bluetooth_connection_stability",
      "description": "Whether pairing and connection remain stable during use."
    }
  ],
  "reason": "The current bundle misses the review's discussion of intermittent connection drops.",
  "confidence": 0.84
}
```

### Recommended agent

Suggested file:

- `src/echoinsight/vaiidation_agent.py`

Suggested class:

- `ValidationAgent`

Suggested methods:

1. `validate_bundle(review, accepted_features) -> dict`
2. `_build_validation_prompt(...) -> str`
3. `_parse_validation_response(...) -> dict`

### Recommended prompt shape

```text
You are the validation agent in EchoInsight.
Given the original review and the current feature bundle, decide whether the bundle fully covers the review.

Rules:
- Judge semantic coverage, not wording overlap.
- Do not rescore features one by one.
- Only decide whether important reusable features are missing.
- If coverage is incomplete, identify the missing reusable feature(s).
- Return JSON only.
```

### Design notes

- validation is a gatekeeper, not a scorer
- if validation fails, the next step is back to `Master Agent`
- validation feedback should be directly reusable by the dynamic feature generator

## 4. Dynamic Backflow

### Purpose

When validation fails, control returns to the `Master Agent`.

The `Master Agent` then generates new reusable features for the uncovered part of the review, and those new features are sent to classifier agents for rescoring.

### Trigger

```text
validation_result.pass == false
```

### Process

1. receive:
   - review text
   - currently accepted feature bundle
   - current feature inventory
   - validation agent's missing-feature analysis
2. let `Master Agent` propose one or more reusable new features
3. dedupe against existing features
4. add accepted new features to the active feature inventory
5. send new features to classifier agents
6. re-run feature fusion for the same review
7. re-run validation

### Suggested dynamic feature schema

```json
{
  "name": "bluetooth_connection_stability",
  "description": "Whether pairing, reconnecting, and ongoing Bluetooth connection remain reliable.",
  "examples": [
    "keeps disconnecting",
    "connection drops randomly"
  ],
  "source": "master_agent_dynamic"
}
```

### Design notes

- dynamic features are owned by `Master Agent`, not by a separate long-lived validator module
- generated features should still be reusable catalog features, not review-specific labels
- dedupe remains important even in an all-LLM pipeline
- validation output should guide dynamic generation, otherwise the loop becomes noisy
- new features must go back through classifier agents before they are accepted into the final review result

## 5. Full Review Loop

For each review, the V2 workflow should look like this:

1. start with current active feature inventory
2. run the trained agents in the fixed pool
3. run `ClassifyAgent` across all active features
4. fuse the outputs into one per-review feature bundle
5. run `ValidationAgent`
6. if validation passes, finalize the review result
7. if validation fails, return to `Master Agent`
8. generate dynamic features and classify them
9. re-run fusion and validation on the same review
10. stop when validation passes or a max-iteration limit is reached

This gives V2 a true master-pool-validation loop instead of the current score-threshold loop.

## Proposed V2 Files

Suggested new modules:

- `src/echoinsight/master_agent.py`
- `src/echoinsight/classify_agent.py`
- `src/echoinsight/vaiidation_agent.py`
- `src/echoinsight/sentiment_agent.py`
- `src/echoinsight/subjectivity_agent.py`
- `src/echoinsight/feature_fusion.py`
- `src/echoinsight/v2_pipeline.py`

Suggested supporting files:

- `config/feature_catalog_v2.json`
- `results/.../final_active_feature_map.csv`
- `results/.../review_level_diagnostics.json`
- `results/.../feature_inventory_final.json`

## Proposed V2 Pipeline Contract

Suggested per-review result:

```json
{
  "review_id": "12",
  "trained_agent_outputs": {
    "sentiment": "positive",
    "subjectivity": "subjective"
  },
  "accepted_features": {
    "battery_life": {
      "has_feature": true,
      "feature_score": 0.91
    },
    "comfort_fit": {
      "has_feature": true,
      "feature_score": 0.74
    }
  },
  "validation_pass": true,
  "validation_reason": "Current feature bundle covers the review.",
  "dynamic_features_added": [],
  "iterations_used": 1
}
```

Suggested failed review result:

```json
{
  "review_id": "13",
  "trained_agent_outputs": {
    "sentiment": "negative",
    "subjectivity": "subjective"
  },
  "accepted_features": {
    "sound_quality": {
      "has_feature": true,
      "feature_score": 0.66
    }
  },
  "validation_pass": false,
  "validation_reason": "The review also discusses unstable Bluetooth connection.",
  "dynamic_features_added": [
    {
      "name": "bluetooth_connection_stability",
      "feature_score": 0.89
    }
  ],
  "iterations_used": 3
}
```

## Output Format

V2 should export two levels of results.

### Review-level diagnostics

For debugging and analysis:

- `review_id`
- `review_text`
- `accepted_features`
- `validation_pass`
- `validation_reason`
- `dynamic_features_added`
- `iterations_used`

### Final active feature map

For downstream analysis:

- one row per review
- one column per final feature
- each cell can be:
  - `1` if feature is present
  - `0` if feature is absent

Optional later extension:

- replace binary cells with confidence scores

## Prompt Strategy

V2 relies on prompt discipline more than numeric formulas.

Recommended prompt principles:

- use one narrow decision per call
- require JSON-only output
- include explicit rules against overcalling weak evidence
- define "reusable feature" clearly
- separate classification prompts from validation prompts from dynamic-generation prompts

Recommended prompt roles:

- `InitAgent`: ontology builder
- `ClassifyAgent`: binary feature detector
- `ValidationAgent`: coverage checker
- `DynamicAgent`: missing-feature generator

## Dedupe Strategy

Even in V2, dedupe is still required.

Where dedupe should happen:

1. after init feature extraction
2. after dynamic feature generation
3. before adding any new feature to the long-lived catalog

Recommended checks:

- exact name duplicates
- near-duplicate paraphrases
- overly narrow review-specific labels

If needed, this can be a separate LLM dedupe prompt or a dedicated `DedupeAgent`.

## Implementation Phases

## Phase 1

Build the V2 skeleton without removing V1:

- add `init_agent.py`
- add `classify_agent.py`
- add `vaiidation_agent.py`
- add `dynamic_agent.py`
- add `v2_pipeline.py`

## Phase 2

Implement init mode:

- sample review subset
- extract initial features
- dedupe and save initial catalog

## Phase 3

Implement per-review classification loop:

- one feature at a time
- strict JSON output
- store accepted features

## Phase 4

Implement validation + dynamic backflow:

- validation decides pass/fail
- dynamic agent proposes missing reusable features
- re-run loop until pass or limit

## Phase 5

Export outputs:

- review-level diagnostics
- final feature inventory
- final active feature map

## Recommended First Refactor Boundary

To keep the rewrite manageable, the best first code boundary is:

- build V2 as a parallel pipeline
- do not mutate the current heuristic pipeline in place

That means:

- keep current `agents.py` and old pipeline for reference
- add new V2 agents in separate files
- add a new `v2_pipeline.py`
- compare outputs before deleting old code

This will make debugging much easier during the transition.

## Open Questions

These are the main design choices still worth deciding during implementation:

1. Should `ClassifyAgent` classify features one-by-one or in small batches?
   My recommendation: one-by-one first, for cleaner behavior and easier debugging.

2. Should active feature map cells be binary or confidence-weighted?
   My recommendation: binary first, confidence as optional extra metadata.

3. Should validation directly return missing normalized feature names?
   My recommendation: return both normalized candidates and a natural-language reason.

4. Should dedupe be embedded into `DynamicAgent` or separated out?
   My recommendation: keep it inside the dynamic flow first, split later only if needed.

5. How many dynamic iterations should one review be allowed?
   My recommendation: keep a hard cap such as `3-5` in V2.

## My Recommendation

The clean V2 version is:

- use LLM to create the initial feature ontology from sampled reviews
- use LLM to classify each review against each feature
- use LLM validation to judge whether the accepted bundle fully covers the review
- use a new dynamic agent to grow the feature space when coverage is incomplete
- export a final feature map built from the final feature inventory

This architecture matches your described direction much better than the current score-based pipeline, and it gives you a strong refactor boundary for the next coding step.
