"""Runner script for EchoInsight V2 pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.echoinsight.v2_pipeline import EchoInsightV2Pipeline

ROOT = Path(__file__).parent
REGISTRY = ROOT / "config" / "model_registry.json"


def list_models() -> None:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    default = data.get("default", "")
    print("Available model profiles (config/model_registry.json):\n")
    for alias, profile in data.get("models", {}).items():
        marker = " [default]" if alias == default else ""
        print(f"  {alias}{marker}")
        print(f"    model  : {profile['model']}")
        print(f"    url    : {profile['base_url']}")
        print(f"    rpm    : {profile.get('rpm')}  delay: {profile.get('request_delay')}s")
        print(f"    notes  : {profile.get('notes', '')}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="EchoInsight V2 Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run with --list-models to see all available model profiles.",
    )
    parser.add_argument("--csv", default=str(ROOT / "data/smoke_input.csv"), help="Input CSV path")
    parser.add_argument("--info", default=str(ROOT.parent / "info.md"), help="API credentials file (apikey)")
    parser.add_argument("--run-name", default="smoke", help="Output run name under results_v2/")
    parser.add_argument("--max-reviews", type=int, default=5, help="Max reviews to process")
    parser.add_argument("--sample-size", type=int, default=10, help="Sample size for init")
    parser.add_argument("--max-features", type=int, default=40, help="Max features in catalog (caps classify prompt size)")
    parser.add_argument("--chunk-max-reviews", type=int, default=4, help="Max reviews per init chunk sent to LLM")
    parser.add_argument("--chunk-max-chars", type=int, default=6000, help="Max chars per init chunk (0 = unlimited)")
    parser.add_argument("--max-iters", type=int, default=2, help="Max dynamic expansion iterations")
    parser.add_argument("--min-score", type=float, default=0.5, help="Min score to keep feature")
    parser.add_argument(
        "--model",
        default=None,
        metavar="ALIAS",
        help="Model profile alias from config/model_registry.json (default: registry default). "
             "Use --list-models to see options.",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Print all available model profiles and exit.",
    )
    args = parser.parse_args()

    if args.list_models:
        list_models()
        return

    pipeline = EchoInsightV2Pipeline(
        info_path=args.info,
        output_root=ROOT / "results_v2",
        run_name=args.run_name,
        sample_size_init=args.sample_size,
        max_reviews=args.max_reviews,
        max_features=args.max_features,
        chunk_max_reviews=args.chunk_max_reviews,
        chunk_max_chars=args.chunk_max_chars,
        max_dynamic_iterations=args.max_iters,
        min_feature_score_to_keep=args.min_score,
        model_alias=args.model,
        registry_path=REGISTRY,
    )
    summary = pipeline.run(args.csv)

    print("\n=== V2 Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
