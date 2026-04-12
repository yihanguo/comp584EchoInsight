# EchoInsight COMP 584 Prototype

This folder contains a lightweight prototype of the three-layer EchoInsight workflow.

For the fuller prototype code, data assets, and setup notes, see the active development branch:

- `codex/comp584-echoinsight-sync`
- https://github.com/yihanguo/comp584EchoInsight/tree/codex/comp584-echoinsight-sync

- `config/feature_catalog.json`: predefined feature sets used to initialize the classification layer.
- `src/echoinsight/`: main, classification, and validation layer logic.
- `run_echoinsight.py`: entry point for running the pipeline locally.
- `results/`: preliminary outputs from a local pipeline run.

Run it with:

```bash
python3 run_echoinsight.py --max-reviews 100
```

Current prototype scope:

- Implements the agentic flow up to validation.
- Produces interpretable feature suggestions, confirmations, and bundle-level validation scores.
- Does not yet implement the backflow loop or threshold-based feature expansion.
