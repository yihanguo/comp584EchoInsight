"""Runner script for EchoInsight V2 pipeline."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
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


def load_profile(model_alias: str | None) -> tuple[str, dict]:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    alias = model_alias or data.get("default", "")
    models = data.get("models", {})
    if alias not in models:
        available = ", ".join(models.keys())
        raise ValueError(f"Unknown model alias {alias!r}. Available: {available}")
    return alias, models[alias]


def infer_run_name(csv_path: str | Path, model_alias: str | None, max_reviews: int) -> str:
    alias, profile = load_profile(model_alias)
    stem = Path(csv_path).stem.lower()
    stem = re.sub(r"(_pipeline)?_input(_\d+)?$", "", stem)
    stem = re.sub(r"(_reviews?|_data|_dataset)$", "", stem)
    product = re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "run"

    model_id = str(profile.get("model", "")).lower()
    base_url = str(profile.get("base_url", "")).lower()
    if "glm" in alias.lower() or "glm" in model_id:
        provider = "glm"
    elif "modelscope" in base_url:
        provider = "modelscope"
    else:
        provider = re.sub(r"[^a-z0-9]+", "_", alias.lower()).strip("_") or "model"

    return f"{product}_{provider}_{max_reviews}"


def main():
    parser = argparse.ArgumentParser(
        description="EchoInsight V2 Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run with --list-models to see all available model profiles.",
    )
    parser.add_argument("--csv", default=str(ROOT / "data/ipad.csv"), help="Input CSV path")
    parser.add_argument("--info", default=str(ROOT.parent / "info.md"), help="API credentials file (apikey)")
    parser.add_argument(
        "--run-name",
        default=None,
        help="Output run name under results_v2/. Defaults to <csv>_<provider>_<max-reviews>, e.g. ipad_glm_20.",
    )
    parser.add_argument("--max-reviews", type=int, default=5, help="Max reviews to process")
    parser.add_argument("--sample-size", type=int, default=10, help="Sample size for init")
    parser.add_argument("--max-features", type=int, default=40, help="Max features in catalog (caps classify prompt size)")
    parser.add_argument("--chunk-max-reviews", type=int, default=4, help="Max reviews per init chunk sent to LLM")
    parser.add_argument("--chunk-max-chars", type=int, default=6000, help="Max chars per init chunk (0 = unlimited)")
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
    parser.add_argument(
        "--classify-workers",
        type=int,
        default=1,
        help="Number of concurrent feature classifications per review. "
             "1 = serial (default). Keep low (<=5) for hosted APIs to avoid rate limits.",
    )
    parser.add_argument(
        "--max-validation-iters",
        type=int,
        default=2,
        help="Maximum validation passes per review. Validation is always enabled; failed validation triggers dynamic feature generation.",
    )
    args = parser.parse_args()

    if args.list_models:
        list_models()
        return

    run_name = args.run_name or infer_run_name(args.csv, args.model, args.max_reviews)
    print(f"[V2] Output run name: {run_name}", flush=True)

    pipeline = EchoInsightV2Pipeline(
        info_path=args.info,
        output_root=ROOT / "results_v2",
        run_name=run_name,
        sample_size_init=args.sample_size,
        max_reviews=args.max_reviews,
        max_features=args.max_features,
        chunk_max_reviews=args.chunk_max_reviews,
        chunk_max_chars=args.chunk_max_chars,
        model_alias=args.model,
        registry_path=REGISTRY,
        classify_workers=args.classify_workers,
        max_validation_iters=args.max_validation_iters,
    )
    summary = pipeline.run(args.csv)

    stats_script = ROOT / "scripts" / "summarize_results.py"
    if stats_script.exists():
        sys.stdout.flush()
        subprocess.run(
            [
                sys.executable,
                str(stats_script),
                "--results-dir",
                str(ROOT / "results_v2" / run_name),
            ],
            check=True,
        )

    print("\n=== V2 Summary ===", flush=True)
    for k, v in summary.items():
        print(f"  {k}: {v}", flush=True)


if __name__ == "__main__":
    main()
