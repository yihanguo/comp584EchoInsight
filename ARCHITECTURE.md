# EchoInsight Prototype Architecture

## Layer roles

### 1. Main layer
The main layer reads one review at a time and scores every predefined feature in the feature catalog.
It uses:
- lexical similarity between the review and the feature description
- overlap with seed keywords
- overlap with indicative phrases
- light rating-aware priors

Its output is a ranked list of **potentially related features**.

### 2. Classification layer
The classification layer contains one classifier per feature.
For each feature suggested by the main layer, the matching classifier decides whether the feature is **truly related** to the review.
It returns:
- a boolean relation decision
- a confidence score
- sentiment polarity inherited from the review rating
- supporting evidence terms and phrases

This implements the paper's idea that the main layer proposes candidates and the classification layer filters them.

### 3. Validation layer
The validation layer receives only the features confirmed by the classification layer.
It computes bundle-level diagnostics:
- confirmed feature count
- bundle confidence
- evidence coverage
- bundle coherence
- a preliminary overall score

In this prototype, the validation layer **does not yet apply the final pass/fail threshold** and does not trigger backflow.
That was intentionally left out, matching your request.

## Data flow

1. Review text enters the main layer.
2. Main layer proposes candidate features.
3. Candidate features are routed to their corresponding classification agents.
4. Only confirmed features move to validation.
5. Validation writes a preliminary active feature bundle plus diagnostics.

## Current initialization choice
This first pass uses a manually defined feature catalog in `config/feature_catalog.json`.
That matches your methodology slide where the classification layer is initialized with predefined feature sets.

## Why this is a good pre-training prototype
- It makes the layer boundaries explicit.
- It stores interpretable evidence for every decision.
- It is easy to replace each heuristic layer with a trainable model later.
- It already produces outputs that can be manually reviewed for label quality before training.
