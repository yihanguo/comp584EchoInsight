"""Regenerate report and statistics for a completed EchoInsight V2 run."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.echoinsight.v2_pipeline import EchoInsightV2Pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize an existing EchoInsight V2 results folder.")
    parser.add_argument("--results-dir", required=True, help="Existing run directory under results_v2/.")
    return parser.parse_args()


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    results_dir = Path(args.results_dir).expanduser().resolve()
    if not results_dir.exists():
        raise FileNotFoundError(f"Results directory not found: {results_dir}")

    catalog = load_json(results_dir / "initialized_feature_corpus.json", [])
    summary = load_json(results_dir / "v2_summary.json", {})
    diag_path = results_dir / "review_level_diagnostics.jsonl"
    if not diag_path.exists():
        raise FileNotFoundError(f"Missing diagnostics file: {diag_path}")

    records = [
        json.loads(line)
        for line in diag_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not summary:
        summary = EchoInsightV2Pipeline._build_summary(None, catalog, records, 0.0)

    pipeline = object.__new__(EchoInsightV2Pipeline)
    pipeline.out_dir = results_dir
    pipeline._progress = lambda message: print(f"[finalize] {message}", flush=True)
    EchoInsightV2Pipeline._export_feature_map(pipeline, records)
    EchoInsightV2Pipeline._write_report(pipeline, catalog, records, summary)

    stats_script = ROOT / "scripts" / "summarize_results.py"
    subprocess.run(
        [sys.executable, str(stats_script), "--results-dir", str(results_dir)],
        check=True,
    )
    print(f"[finalize] Complete: {results_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
