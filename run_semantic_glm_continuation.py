"""Run the revised semantic GLM EchoInsight continuation workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from echoinsight.semantic_glm_continuation import SemanticGLMContinuationWorkflow


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected a boolean value, got {value!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run revised semantic GLM EchoInsight continuation.")
    parser.add_argument("--input", default=str(ROOT / "data" / "airpods_pipeline_input.csv"))
    parser.add_argument("--features", default=str(ROOT / "config" / "feature_catalog.json"))
    parser.add_argument("--info-path", default=str(ROOT / "results_airpods_500" / "info.md"))
    parser.add_argument("--dynamic-pool", default=str(ROOT / "config" / "dynamic_feature_candidates_glm.json"))
    parser.add_argument("--output-dir", default=str(ROOT / "results_airpods_semantic_glm_revised_50"))
    parser.add_argument("--max-reviews", type=int, default=50)
    parser.add_argument("--init-sample-size", type=int, default=100)
    parser.add_argument("--random-seed", type=int, default=584)
    parser.add_argument("--init-batch-size", type=int, default=20)
    parser.add_argument("--init-features-per-batch", type=int, default=8)
    parser.add_argument("--glm-suggestion-turns", type=int, default=1)
    parser.add_argument("--max-candidates-per-turn", type=int, default=4)
    parser.add_argument("--persist-initialized-corpus", type=parse_bool, default=True)
    parser.add_argument("--request-delay", type=float, default=0.2)
    parser.add_argument("--glm-rpm", type=float, default=60.0, help="Maximum GLM requests per minute; default 60 means at least 1 second between calls")
    parser.add_argument("--glm-timeout", type=float, default=100.0)
    parser.add_argument("--enable-thinking", action="store_true", help="Do not send the GLM thinking-disabled flag")
    parser.add_argument("--sglang-disable-thinking", action="store_true", help="Also send chat_template_kwargs enable_thinking=false")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workflow = SemanticGLMContinuationWorkflow(
        feature_catalog_path=args.features,
        info_path=args.info_path,
        dynamic_pool_path=args.dynamic_pool,
        request_delay=args.request_delay,
        glm_rpm=args.glm_rpm,
        glm_timeout=args.glm_timeout,
        disable_thinking=not args.enable_thinking,
        sglang_disable_thinking=args.sglang_disable_thinking,
    )
    summary = workflow.run(
        input_csv=args.input,
        output_dir=args.output_dir,
        max_reviews=args.max_reviews,
        init_sample_size=args.init_sample_size,
        random_seed=args.random_seed,
        init_batch_size=args.init_batch_size,
        init_features_per_batch=args.init_features_per_batch,
        glm_suggestion_turns=args.glm_suggestion_turns,
        max_candidates_per_turn=args.max_candidates_per_turn,
        persist_initialized_corpus=args.persist_initialized_corpus,
    )
    print("Revised semantic GLM continuation run complete")
    print(f"reviews_processed={summary['reviews_processed']}")
    print(f"threshold={summary['threshold']}")
    print(f"final_pass_count={summary['final_pass_count']}")
    print(f"all_reviews_passed={summary['all_reviews_passed']}")
    print(f"initialized_feature_count={summary['initialized_feature_count']}")
    print(f"initial_glm_features_added={summary['initial_glm_features_added']}")
    print("accepted_new_feature_counts=")
    for feature, count in summary["accepted_new_feature_counts"].items():
        print(f"  - {feature}: {count}")
    print(f"output_dir={summary['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
