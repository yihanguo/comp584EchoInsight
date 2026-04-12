# EchoInsight COMP 584 Prototype

This folder contains a lightweight prototype of the three-layer EchoInsight workflow.

## What's in this folder

- `config/feature_catalog.json`: predefined feature sets used to initialize the classification layer.
- `data/amazon_reviews_2023_electronics_sample_5k.csv`: local demo input file used by the default runner path in this branch.
- `src/echoinsight/`: main, classification, and validation layer logic.
- `run_echoinsight.py`: entry point for running the pipeline locally.
- `results/`: preliminary outputs from a local pipeline run.

## Quick start

This prototype uses only the Python standard library, so there are no extra package installs required.

From the repository root:

```bash
cd comp584_build
python3 run_echoinsight.py
```

That command uses the default input path and writes output files into `comp584_build/results/`.

## Sample commands

Run the default demo data:

```bash
cd comp584_build
python3 run_echoinsight.py
```

Limit the run to a smaller number of reviews:

```bash
cd comp584_build
python3 run_echoinsight.py --max-reviews 25
```

Write outputs to a clean test directory:

```bash
cd comp584_build
python3 run_echoinsight.py --max-reviews 25 --output-dir results/test_run
```

Use a different CSV with the same columns (`rating`, `title`, `text`):

```bash
cd comp584_build
python3 run_echoinsight.py \
  --input /path/to/your_reviews.csv \
  --features config/feature_catalog.json \
  --output-dir results/custom_run \
  --max-reviews 100
```

## Expected outputs

After a successful run, you should see console output like:

```text
EchoInsight prototype run complete
reviews_processed=100
reviews_with_confirmed_features=...
average_preliminary_overall_score=...
```

The run writes:

- `results/preliminary_run_summary.json`: overall run-level statistics.
- `results/review_diagnostics.json`: per-review suggestions, classification decisions, and validation diagnostics.
- `results/review_feature_assignments.csv`: compact review-to-feature assignment table.

## Notes on the bundled data

The original full source CSV used during development was not present in this workspace when this branch was prepared.
To keep the branch runnable for collaborators, `data/amazon_reviews_2023_electronics_sample_5k.csv` in this branch is a reconstructed demo dataset built from the 100 review previews captured in `results/review_diagnostics.json`.

That means:

- the branch is self-contained and easy to test immediately;
- reruns will exercise the full pipeline successfully;
- the bundled demo data is smaller and preview-truncated, so it should be treated as a reproducible test fixture rather than the original full 5k review file.

## Current prototype scope

- Implements the agentic flow up to validation.
- Produces interpretable feature suggestions, confirmations, and bundle-level validation scores.
- Does not yet implement the backflow loop or threshold-based feature expansion.
