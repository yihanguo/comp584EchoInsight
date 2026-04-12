"""Run the EchoInsight three-layer prototype on the local review data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from echoinsight.pipeline import EchoInsightPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the EchoInsight prototype pipeline.")
    parser.add_argument("--input", default=str(ROOT / "data" / "amazon_reviews_2023_electronics_sample_5k.csv"), help="Path to the review CSV.")
    parser.add_argument("--features", default=str(ROOT / "config" / "feature_catalog.json"), help="Path to the predefined feature catalog.")
    parser.add_argument("--output-dir", default=str(ROOT / "results"), help="Directory where diagnostics and summary files are written.")
    parser.add_argument("--max-reviews", type=int, default=100, help="How many reviews to process for the preliminary run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pipeline = EchoInsightPipeline(feature_catalog_path=args.features)
    summary = pipeline.run(input_csv=args.input, output_dir=args.output_dir, max_reviews=args.max_reviews)
    print("EchoInsight prototype run complete")
    print(f"reviews_processed={summary['reviews_processed']}")
    print(f"reviews_with_confirmed_features={summary['reviews_with_confirmed_features']}")
    print(f"average_preliminary_overall_score={summary['average_preliminary_overall_score']}")
    print("top_features=")
    for item in summary["top_features"][:5]:
        print(f"  - {item['feature']}: {item['confirmed_reviews']} reviews {item['sentiment_breakdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
