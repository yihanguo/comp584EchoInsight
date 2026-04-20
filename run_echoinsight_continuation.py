"""Run EchoInsight continuation: thresholding, new features, and active map trial."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from echoinsight.continuation import ContinuationWorkflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run EchoInsight continuation workflow.")
    parser.add_argument("--input", default=str(ROOT / "data" / "airpods_pipeline_input.csv"))
    parser.add_argument("--features", default=str(ROOT / "config" / "feature_catalog.json"))
    parser.add_argument("--output-dir", default=str(ROOT / "results_airpods_continuation_500"))
    parser.add_argument("--max-reviews", type=int, default=500)
    parser.add_argument("--max-iterations", type=int, default=8)
    parser.add_argument("--bootstrap-k", type=int, default=12)
    parser.add_argument("--min-bootstrap-support", type=float, default=0.25)
    parser.add_argument("--feature-source", choices=["heuristic", "glm"], default="heuristic")
    parser.add_argument("--info-path", default=str(ROOT / "results_airpods_500" / "info.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workflow = ContinuationWorkflow(
        feature_catalog_path=args.features,
        info_path=args.info_path,
        feature_source=args.feature_source,
        bootstrap_k=args.bootstrap_k,
        min_bootstrap_support=args.min_bootstrap_support,
    )
    summary = workflow.run(
        input_csv=args.input,
        output_dir=args.output_dir,
        max_reviews=args.max_reviews,
        max_iterations=args.max_iterations,
    )
    threshold = summary["threshold_calibration"]["threshold"]
    print("EchoInsight continuation run complete")
    print(f"reviews_processed={summary['reviews_processed']}")
    print(f"threshold={threshold}")
    print(f"initial_pass_count={summary['initial_pass_count']}")
    print(f"final_pass_count_after_backflow_trial={summary['final_pass_count_after_backflow_trial']}")
    print(f"reviews_with_accepted_new_feature={summary['reviews_with_accepted_new_feature']}")
    print("accepted_new_feature_counts=")
    for feature, count in summary["accepted_new_feature_counts"].items():
        print(f"  - {feature}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
