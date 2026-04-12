# EchoInsight COMP 584 Prototype

This folder contains a lightweight prototype of the three-layer EchoInsight workflow.

## What's in this folder

- `config/feature_catalog.json`: predefined feature sets used to initialize the classification layer.
- `data/amazon_reviews_2023_electronics_sample_5k.csv`: the main 5k review CSV used by the default runner path in this branch.
- `data/amazon_reviews_2023_electronics_sample_5k.parquet`: parquet version of the same 5k sample.
- `data/`: additional dataset notes, exploratory notebooks, and smaller supporting samples used during data selection and prototyping.
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

This branch now includes the actual `amazon_reviews_2023_electronics_sample_5k.csv` file from the project workspace, so the default run command uses the real 5k sample instead of a reconstructed placeholder.

The branch also includes smaller supporting data assets that were useful during dataset exploration, including:

- `data/amazon_polarity_small/train_10k.csv`
- `data/ecommerce_candidates/*/sample_10k.csv`
- `data/data.md`
- exploratory notebooks and lightweight analysis scripts

Two larger raw files from the Desktop project were intentionally not added to this GitHub branch because they are too large for a practical standard git workflow:

- `data/ratings_Electronics (1).csv` at about `233 MB`
- `data/amazon_polarity_small/test_full.csv` at about `167 MB`

If needed later, those larger files are better shared through cloud storage, Git LFS, or a dataset hosting service rather than a normal repository commit.

## Current prototype scope

- Implements the agentic flow up to validation.
- Produces interpretable feature suggestions, confirmations, and bundle-level validation scores.
- Does not yet implement the backflow loop or threshold-based feature expansion.
