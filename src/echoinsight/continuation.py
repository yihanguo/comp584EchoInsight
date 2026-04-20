"""Continuation workflow for thresholding, feature backflow, and active feature maps.

This module extends the initial three-layer prototype without replacing it. It adds:
1. unsupervised threshold calibration for the validation score,
2. new named feature suggestions when a review fails the threshold,
3. bootstrap validation for candidate new features,
4. a trial active feature map after the accepted backflow feature is added.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .agents import ClassificationAgent, ReviewRecord, ValidationLayer
from .features import FeatureDefinition
from .pipeline import EchoInsightPipeline
from .text_utils import bounded_score, cosine_from_counters, phrase_hits, token_counts


@dataclass(frozen=True)
class NamedFeatureCandidate:
    name: str
    description: str
    seed_keywords: list[str]
    positive_keywords: list[str]
    negative_keywords: list[str]

    def to_feature_definition(self) -> FeatureDefinition:
        return FeatureDefinition(
            name=self.name,
            description=self.description,
            seed_keywords=self.seed_keywords,
            positive_keywords=self.positive_keywords,
            negative_keywords=self.negative_keywords,
        )


AIRPODS_CANDIDATES = [
    NamedFeatureCandidate(
        name="sound_quality",
        description="How customers evaluate audio clarity, volume, bass, and overall listening quality.",
        seed_keywords=["sound", "audio", "bass", "volume", "music", "clear", "loud", "quality"],
        positive_keywords=["sound is clear", "sound quality is great", "sounds amazing", "great sound", "clear sound"],
        negative_keywords=["bad sound", "poor sound", "low volume", "too quiet", "no bass", "sound quality isn't"],
    ),
    NamedFeatureCandidate(
        name="noise_cancellation",
        description="Whether noise cancellation, transparency, or ambient noise handling works as expected.",
        seed_keywords=["noise", "cancellation", "canceling", "cancelling", "transparency", "ambient"],
        positive_keywords=["noise cancellation is great", "noise cancelling is great", "blocks noise", "cancels noise"],
        negative_keywords=["too much noise cancelling", "noise cancellation doesn't", "noise cancelling doesn't", "poor noise cancellation"],
    ),
    NamedFeatureCandidate(
        name="ear_fit_comfort",
        description="Whether earbuds fit securely, stay in the ear, or cause ear discomfort.",
        seed_keywords=["ear", "ears", "fit", "fall", "fell", "hurt", "painful", "buds", "tips"],
        positive_keywords=["fit well", "stay in", "don't fall out", "not painful", "comfortable in my ears"],
        negative_keywords=["fall out", "fell out", "hurt my ears", "hurting", "painful", "don't stay in", "bad fit"],
    ),
    NamedFeatureCandidate(
        name="touch_controls",
        description="Whether tap, squeeze, skip, and adjustment controls are easy or frustrating to use.",
        seed_keywords=["tap", "skip", "controls", "adjustments", "button", "press", "squeeze"],
        positive_keywords=["controls are easy", "easy to skip", "tap works", "controls work"],
        negative_keywords=["can't tap", "cannot tap", "hard to skip", "controls are difficult", "not as effective"],
    ),
    NamedFeatureCandidate(
        name="authenticity_concern",
        description="Whether customers worry the item is fake, not genuine, or not official Apple hardware.",
        seed_keywords=["fake", "real", "authentic", "genuine", "green", "serial", "applecare"],
        positive_keywords=["real apple", "authentic apple", "genuine apple"],
        negative_keywords=["not real", "fake", "green light", "not authentic", "not genuine"],
    ),
    NamedFeatureCandidate(
        name="charging_case",
        description="Problems or praise involving the charging case, case battery, lid, or case charging behavior.",
        seed_keywords=["case", "lid", "charging case", "case battery", "case charge"],
        positive_keywords=["case charges", "charging case works", "case battery lasts"],
        negative_keywords=["case won't charge", "case does not charge", "charging case broke", "case battery dies"],
    ),
    NamedFeatureCandidate(
        name="microphone_call_quality",
        description="How microphone quality, call quality, and voice pickup perform during calls.",
        seed_keywords=["mic", "microphone", "call", "calls", "voice", "talking"],
        positive_keywords=["calls are clear", "microphone works", "voice is clear"],
        negative_keywords=["bad mic", "poor microphone", "can't hear me", "calls drop", "voice sounds bad"],
    ),
    NamedFeatureCandidate(
        name="water_resistance",
        description="Whether customers mention water, sweat, or moisture resistance.",
        seed_keywords=["water", "sweat", "resistant", "resistance", "rain", "moisture"],
        positive_keywords=["water resistant", "sweat resistant", "works in rain"],
        negative_keywords=["water damage", "not water resistant", "sweat damaged"],
    ),
]


class ThresholdCalibrator:
    """Calibrates a pass threshold from score distribution when labels are unavailable."""

    def __init__(self, quantile: float = 0.60, min_threshold: float = 0.22):
        self.quantile = quantile
        self.min_threshold = min_threshold

    def calibrate(self, scores: list[float]) -> dict:
        positive_scores = sorted(score for score in scores if score > 0)
        if not positive_scores:
            return {
                "threshold": self.min_threshold,
                "method": "fallback_min_threshold",
                "otsu_threshold": 0.0,
                "quantile_threshold": 0.0,
                "score_count": len(scores),
                "positive_score_count": 0,
            }

        otsu_threshold = self._otsu_threshold(positive_scores)
        quantile_threshold = self._quantile(positive_scores, self.quantile)
        threshold = max(self.min_threshold, 0.5 * otsu_threshold + 0.5 * quantile_threshold)
        return {
            "threshold": round(threshold, 4),
            "method": "hybrid_otsu_plus_quantile_without_labels",
            "otsu_threshold": round(otsu_threshold, 4),
            "quantile_threshold": round(quantile_threshold, 4),
            "score_count": len(scores),
            "positive_score_count": len(positive_scores),
        }

    def _quantile(self, values: list[float], q: float) -> float:
        if len(values) == 1:
            return values[0]
        idx = max(0, min(len(values) - 1, round(q * (len(values) - 1))))
        return values[idx]

    def _otsu_threshold(self, values: list[float]) -> float:
        if len(values) < 3:
            return values[len(values) // 2]
        unique_values = sorted(set(values))
        if len(unique_values) == 1:
            return unique_values[0]

        total = len(values)
        total_mean = sum(values) / total
        best_threshold = unique_values[0]
        best_between_variance = -1.0

        for threshold in unique_values[:-1]:
            low = [value for value in values if value <= threshold]
            high = [value for value in values if value > threshold]
            if not low or not high:
                continue
            low_weight = len(low) / total
            high_weight = len(high) / total
            low_mean = sum(low) / len(low)
            high_mean = sum(high) / len(high)
            between_variance = low_weight * (low_mean - total_mean) ** 2 + high_weight * (high_mean - total_mean) ** 2
            if between_variance > best_between_variance:
                best_between_variance = between_variance
                best_threshold = threshold
        return best_threshold


class HeuristicNewFeatureSuggester:
    """Suggests AirPods-specific named features for failed reviews."""

    def __init__(self, candidates: Iterable[NamedFeatureCandidate] = AIRPODS_CANDIDATES):
        self.candidates = list(candidates)

    def ranked_candidates(self, review: ReviewRecord, existing_feature_names: set[str]) -> list[dict]:
        scored = []
        review_counts = token_counts(review.text)
        for candidate in self.candidates:
            if candidate.name in existing_feature_names:
                continue
            feature = candidate.to_feature_definition()
            seed_hits = phrase_hits(review.text, candidate.seed_keywords)
            pos_hits = phrase_hits(review.text, candidate.positive_keywords)
            neg_hits = phrase_hits(review.text, candidate.negative_keywords)
            similarity = cosine_from_counters(review_counts, feature.prototype_counts)
            score = (
                0.45 * min(len(seed_hits) / 2.0, 1.0)
                + 0.25 * min((len(pos_hits) + len(neg_hits)) / 2.0, 1.0)
                + 0.30 * similarity
            )
            scored.append({
                "candidate": candidate,
                "proposal_score": round(score, 4),
                "seed_hits": seed_hits[:6],
                "positive_hits": pos_hits[:6],
                "negative_hits": neg_hits[:6],
            })
        scored = [item for item in scored if item["proposal_score"] >= 0.10]
        scored.sort(key=lambda item: item["proposal_score"], reverse=True)
        return scored


class GLMFeatureSuggester:
    """Optional GLM-backed feature naming client using info.md settings.

    The trial runner defaults to heuristic mode so it works offline. Use --feature-source glm
    if you want the model to propose names from failed reviews.
    """

    def __init__(self, info_path: str | Path):
        self.settings = self._read_info(info_path)

    def _read_info(self, info_path: str | Path) -> dict:
        settings = {}
        path = Path(info_path)
        if not path.exists():
            return settings
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            settings[key.strip()] = value.strip()
        return settings

    def suggest(self, review_text: str, existing_feature_names: list[str], fallback: list[dict]) -> list[dict]:
        try:
            import requests
        except Exception:
            return fallback

        api_key = self.settings.get("apikey")
        base_url = self.settings.get("base_url")
        model = self.settings.get("model")
        if not api_key or not base_url or not model:
            return fallback

        prompt = (
            "Suggest up to 3 short snake_case named customer-experience features for this review. "
            "Avoid existing feature names. Return JSON only as a list of objects with keys: "
            "name, description, seed_keywords, positive_keywords, negative_keywords.\n\n"
            f"Existing features: {existing_feature_names}\n"
            f"Review: {review_text[:1200]}"
        )
        try:
            response = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
                timeout=20,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = self._parse_json_list(content)
            converted = []
            for item in parsed:
                converted.append({
                    "candidate": NamedFeatureCandidate(
                        name=self._safe_name(item.get("name", "suggested_feature")),
                        description=item.get("description", "GLM-suggested customer experience feature."),
                        seed_keywords=list(item.get("seed_keywords", []))[:10],
                        positive_keywords=list(item.get("positive_keywords", []))[:8],
                        negative_keywords=list(item.get("negative_keywords", []))[:8],
                    ),
                    "proposal_score": 0.5,
                    "seed_hits": [],
                    "positive_hits": [],
                    "negative_hits": [],
                    "source": "glm",
                })
            return converted or fallback
        except Exception:
            return fallback

    def _parse_json_list(self, content: str) -> list[dict]:
        match = re.search(r"\[.*\]", content, flags=re.DOTALL)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    def _safe_name(self, name: str) -> str:
        lowered = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
        return lowered or "suggested_feature"


class BootstrapFeatureValidator:
    """Checks whether a proposed new feature is supported by similar failed reviews."""

    def __init__(self, bootstrap_k: int = 12, min_support: float = 0.25, match_threshold: float = 0.18):
        self.bootstrap_k = bootstrap_k
        self.min_support = min_support
        self.match_threshold = match_threshold

    def validate_candidate(self, review: ReviewRecord, candidate: NamedFeatureCandidate, pool: list[ReviewRecord]) -> dict:
        bootstrapped = self._nearest_reviews(review, pool, self.bootstrap_k)
        if not bootstrapped:
            bootstrapped = [review]

        matches = []
        for candidate_review in bootstrapped:
            match = self._feature_match_score(candidate_review, candidate)
            if match["match_score"] >= self.match_threshold:
                matches.append({"review_id": candidate_review.review_id, **match})

        support = len(matches) / len(bootstrapped)
        return {
            "candidate_name": candidate.name,
            "bootstrap_size": len(bootstrapped),
            "support_count": len(matches),
            "support_ratio": round(support, 4),
            "accepted": support >= self.min_support,
            "support_examples": matches[:5],
        }

    def _nearest_reviews(self, review: ReviewRecord, pool: list[ReviewRecord], k: int) -> list[ReviewRecord]:
        base_counts = token_counts(review.text)
        ranked = []
        for candidate in pool:
            if candidate.review_id == review.review_id:
                continue
            similarity = cosine_from_counters(base_counts, token_counts(candidate.text))
            ranked.append((similarity, candidate))
        ranked.sort(key=lambda item: item[0], reverse=True)
        selected = [item[1] for item in ranked[: max(0, k - 1)]]
        return [review] + selected

    def _feature_match_score(self, review: ReviewRecord, candidate: NamedFeatureCandidate) -> dict:
        feature = candidate.to_feature_definition()
        seed_hits = phrase_hits(review.text, candidate.seed_keywords)
        pos_hits = phrase_hits(review.text, candidate.positive_keywords)
        neg_hits = phrase_hits(review.text, candidate.negative_keywords)
        similarity = cosine_from_counters(token_counts(review.text), feature.prototype_counts)
        score = (
            0.45 * min(len(seed_hits) / 2.0, 1.0)
            + 0.30 * min((len(pos_hits) + len(neg_hits)) / 2.0, 1.0)
            + 0.25 * similarity
        )
        return {
            "match_score": round(score, 4),
            "seed_hits": seed_hits[:5],
            "positive_hits": pos_hits[:5],
            "negative_hits": neg_hits[:5],
        }


class ContinuationWorkflow:
    """Runs the remaining methodology steps after the initial validation layer."""

    def __init__(
        self,
        feature_catalog_path: str | Path,
        info_path: str | Path | None = None,
        feature_source: str = "heuristic",
        bootstrap_k: int = 12,
        min_bootstrap_support: float = 0.25,
    ):
        self.pipeline = EchoInsightPipeline(feature_catalog_path)
        self.classifier = ClassificationAgent()
        self.validator = ValidationLayer()
        self.threshold_calibrator = ThresholdCalibrator()
        self.heuristic_suggester = HeuristicNewFeatureSuggester()
        self.glm_suggester = GLMFeatureSuggester(info_path) if info_path else None
        self.feature_source = feature_source
        self.bootstrap_validator = BootstrapFeatureValidator(bootstrap_k=bootstrap_k, min_support=min_bootstrap_support)

    def run(self, input_csv: str | Path, output_dir: str | Path, max_reviews: int = 500, max_iterations: int = 8) -> dict:
        output_dir = Path(output_dir)
        first_pass_dir = output_dir / "first_pass"
        first_pass_summary = self.pipeline.run(input_csv=input_csv, output_dir=first_pass_dir, max_reviews=max_reviews)
        review_outputs = json.loads((first_pass_dir / "review_diagnostics.json").read_text(encoding="utf-8"))
        reviews = self.pipeline._load_reviews(input_csv, max_reviews=max_reviews)
        review_by_id = {review.review_id: review for review in reviews}

        threshold_info = self.threshold_calibrator.calibrate([
            item["validation_layer"]["preliminary_overall_score"] for item in review_outputs
        ])
        threshold = threshold_info["threshold"]

        failed_outputs = [item for item in review_outputs if item["validation_layer"]["preliminary_overall_score"] < threshold]
        failed_reviews = [review_by_id[item["review_id"]] for item in failed_outputs]
        existing_feature_names = {feature.name for feature in self.pipeline.feature_catalog}

        active_rows = []
        candidate_counter = Counter()
        accepted_candidate_counter = Counter()
        feature_support_records = []

        for item in review_outputs:
            review = review_by_id[item["review_id"]]
            initial_score = item["validation_layer"]["preliminary_overall_score"]
            initial_features = list(item["validation_layer"]["validated_feature_bundle"])
            final_score = initial_score

            active_classifications = [
                row for row in item.get("classification_layer", [])
                if row["classification"].get("is_related")
            ]
            final_features = list(initial_features)
            accepted_new_features = []
            accepted_support_ratios = []
            iteration_records = []
            considered_new_feature_names = set()

            if initial_score < threshold:
                for iteration in range(max_iterations):
                    excluded_names = existing_feature_names | set(final_features) | considered_new_feature_names
                    candidates = self._rank_candidates(review, excluded_names)
                    if not candidates:
                        break

                    accepted_this_iteration = False
                    for proposal in candidates:
                        if proposal["proposal_score"] < 0.10:
                            continue
                        candidate = proposal["candidate"]
                        if candidate.name in considered_new_feature_names or candidate.name in final_features:
                            continue

                        considered_new_feature_names.add(candidate.name)
                        candidate_counter[candidate.name] += 1
                        support = self.bootstrap_validator.validate_candidate(review, candidate, failed_reviews)
                        feature_support_records.append({
                            "review_id": review.review_id,
                            "iteration": iteration + 1,
                            "candidate": candidate.name,
                            "proposal_score": proposal["proposal_score"],
                            "support": support,
                        })

                        trace_record = {
                            "iteration": iteration + 1,
                            "candidate": candidate.name,
                            "proposal_score": proposal["proposal_score"],
                            "support": support,
                            "accepted_into_bundle": False,
                            "bundle_score_after_candidate": final_score,
                        }

                        if not support["accepted"]:
                            iteration_records.append(trace_record)
                            continue

                        feature = candidate.to_feature_definition()
                        classification = self.classifier.classify(review, feature, main_score=max(0.24, proposal["proposal_score"]))
                        trace_record["classification"] = classification
                        if not classification["is_related"]:
                            iteration_records.append(trace_record)
                            continue

                        active_classifications.append({
                            "feature": feature.name,
                            "main_score": proposal["proposal_score"],
                            "main_reasons": {"source": "new_feature_backflow"},
                            "classification": classification,
                        })
                        recomputed = self.validator.validate(review, active_classifications)
                        final_features = list(recomputed["validated_feature_bundle"])
                        final_score = recomputed["preliminary_overall_score"]
                        accepted_new_features.append(feature.name)
                        accepted_support_ratios.append(str(support["support_ratio"]))
                        accepted_candidate_counter[feature.name] += 1
                        accepted_this_iteration = True
                        trace_record["accepted_into_bundle"] = True
                        trace_record["bundle_score_after_candidate"] = final_score
                        iteration_records.append(trace_record)
                        break

                    if final_score >= threshold:
                        break
                    if not accepted_this_iteration and len(considered_new_feature_names) >= len(AIRPODS_CANDIDATES):
                        break

            active_rows.append({
                "review_id": review.review_id,
                "text_preview": review.text[:240].replace("\n", " "),
                "initial_features": "|".join(initial_features),
                "initial_score": round(initial_score, 4),
                "threshold": threshold,
                "passed_initial_threshold": initial_score >= threshold,
                "accepted_new_feature": "|".join(accepted_new_features),
                "accepted_new_feature_support": "|".join(accepted_support_ratios),
                "final_features": "|".join(final_features),
                "final_score": round(final_score, 4),
                "passed_final_threshold": final_score >= threshold,
                "iteration_trace": json.dumps(iteration_records, ensure_ascii=False),
            })

        summary = self._write_outputs(
            output_dir=output_dir,
            first_pass_summary=first_pass_summary,
            threshold_info=threshold_info,
            active_rows=active_rows,
            candidate_counter=candidate_counter,
            accepted_candidate_counter=accepted_candidate_counter,
            support_records=feature_support_records,
        )
        return summary

    def _rank_candidates(self, review: ReviewRecord, existing_feature_names: set[str]) -> list[dict]:
        heuristic = self.heuristic_suggester.ranked_candidates(review, existing_feature_names)
        if self.feature_source != "glm" or not self.glm_suggester:
            return heuristic
        glm_ranked = self.glm_suggester.suggest(review.text, sorted(existing_feature_names), heuristic)
        return glm_ranked + heuristic

    def _write_outputs(
        self,
        output_dir: Path,
        first_pass_summary: dict,
        threshold_info: dict,
        active_rows: list[dict],
        candidate_counter: Counter,
        accepted_candidate_counter: Counter,
        support_records: list[dict],
    ) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        active_path = output_dir / "active_feature_map_trial.csv"
        with active_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(active_rows[0].keys()) if active_rows else [])
            writer.writeheader()
            writer.writerows(active_rows)

        support_path = output_dir / "new_feature_support_trials.json"
        support_path.write_text(json.dumps(support_records, indent=2, ensure_ascii=False), encoding="utf-8")

        final_pass_count = sum(1 for row in active_rows if row["passed_final_threshold"])
        initial_pass_count = sum(1 for row in active_rows if row["passed_initial_threshold"])
        new_feature_count = sum(1 for row in active_rows if row["accepted_new_feature"])
        multiple_new_feature_count = sum(1 for row in active_rows if "|" in row["accepted_new_feature"])
        summary = {
            "scope": "continuation_after_initial_validation",
            "threshold_calibration": threshold_info,
            "reviews_processed": len(active_rows),
            "initial_pass_count": initial_pass_count,
            "final_pass_count_after_backflow_trial": final_pass_count,
            "reviews_with_accepted_new_feature": new_feature_count,
            "reviews_with_multiple_accepted_new_features": multiple_new_feature_count,
            "first_pass_summary": first_pass_summary,
            "proposed_new_feature_counts": dict(candidate_counter.most_common()),
            "accepted_new_feature_counts": dict(accepted_candidate_counter.most_common()),
            "outputs": {
                "active_feature_map_trial_csv": str(active_path),
                "new_feature_support_trials_json": str(support_path),
            },
        }
        (output_dir / "continuation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        self._write_markdown_report(output_dir, summary, active_rows)
        self._write_command_examples(output_dir)
        return summary

    def _write_markdown_report(self, output_dir: Path, summary: dict, active_rows: list[dict]) -> None:
        lines = []
        lines.append("# EchoInsight Continuation Trial Report")
        lines.append("")
        lines.append("## Threshold Calibration")
        lines.append("")
        info = summary["threshold_calibration"]
        lines.append(f"- Method: {info['method']}")
        lines.append(f"- Selected threshold: {info['threshold']}")
        lines.append(f"- Otsu threshold: {info['otsu_threshold']}")
        lines.append(f"- Quantile threshold: {info['quantile_threshold']}")
        lines.append("")
        lines.append("The threshold is calibrated without labels by combining an Otsu-style distribution split with a positive-score quantile floor. This is appropriate for the current prototype because no gold feature labels are available yet.")
        lines.append("")
        lines.append("## Backflow Trial Results")
        lines.append("")
        lines.append(f"- Reviews processed: {summary['reviews_processed']}")
        lines.append(f"- Initial pass count: {summary['initial_pass_count']}")
        lines.append(f"- Final pass count after backflow trial: {summary['final_pass_count_after_backflow_trial']}")
        lines.append(f"- Reviews with accepted new feature: {summary['reviews_with_accepted_new_feature']}")
        lines.append(f"- Reviews with multiple accepted new features: {summary['reviews_with_multiple_accepted_new_features']}")
        lines.append("")
        lines.append("For each below-threshold review, the workflow now repeatedly proposes alternative new features, bootstrap-validates each candidate, adds accepted candidates to the active bundle, recomputes the full bundle score, and continues until the calibrated threshold is passed or the rigorous candidate pool is exhausted.")
        lines.append("")
        lines.append("## Accepted New Features")
        lines.append("")
        if summary["accepted_new_feature_counts"]:
            for feature, count in summary["accepted_new_feature_counts"].items():
                lines.append(f"- {feature}: {count}")
        else:
            lines.append("- None accepted in this run.")
        lines.append("")
        lines.append("## Sample Active Feature Map Rows")
        lines.append("")
        for row in active_rows[:12]:
            lines.append(f"### Review {row['review_id']}")
            lines.append(f"- Initial features: {row['initial_features'] or 'None'}")
            lines.append(f"- Initial score: {row['initial_score']}")
            lines.append(f"- Accepted new feature: {row['accepted_new_feature'] or 'None'}")
            lines.append(f"- Final features: {row['final_features'] or 'None'}")
            lines.append(f"- Final score: {row['final_score']}")
            lines.append(f"- Text preview: {row['text_preview']}")
            lines.append("")
        (output_dir / "continuation_trial_report.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_command_examples(self, output_dir: Path) -> None:
        commands = """# EchoInsight Continuation Commands

Run a 100-review trial:

```bash
cd \"/Users/wujinhua/Desktop/COMP584 Final Project\"
python3 run_echoinsight_continuation.py \\
  --input \"data/airpods_pipeline_input.csv\" \\
  --max-reviews 100 \\
  --output-dir \"results_airpods_continuation_100\"
```

Run the same 500-review trial used for the sample report. `--max-iterations 8` means the system can keep proposing additional validated features for a failed review until it passes or the candidate pool is exhausted:

```bash
cd \"/Users/wujinhua/Desktop/COMP584 Final Project\"
python3 run_echoinsight_continuation.py \\
  --input \"data/airpods_pipeline_input.csv\" \\
  --max-reviews 500 \\
  --max-iterations 8 \\
  --output-dir \"results_airpods_continuation_500\"
```

Try the optional GLM-backed feature naming path from `results_airpods_500/info.md`:

```bash
cd \"/Users/wujinhua/Desktop/COMP584 Final Project\"
python3 run_echoinsight_continuation.py \\
  --input \"data/airpods_pipeline_input.csv\" \\
  --max-reviews 100 \\
  --output-dir \"results_airpods_continuation_glm_100\" \\
  --feature-source glm \\
  --info-path \"results_airpods_500/info.md\"
```

Inspect the threshold and counts:

```bash
cat results_airpods_continuation_500/continuation_summary.json
```

Inspect accepted new features per review:

```bash
head -20 results_airpods_continuation_500/active_feature_map_trial.csv
```

Open the sample report:

```bash
open results_airpods_continuation_500/continuation_trial_report.md
```
"""
        (output_dir / "sample_commands.md").write_text(commands, encoding="utf-8")
