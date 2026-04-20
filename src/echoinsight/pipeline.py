"""End-to-end orchestration for the EchoInsight prototype."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from .agents import ClassificationAgent, MainLayerAgent, ReviewRecord, ValidationLayer
from .features import load_feature_catalog


class EchoInsightPipeline:
    def __init__(self, feature_catalog_path: str | Path):
        self.feature_catalog = load_feature_catalog(feature_catalog_path)
        self.main_agent = MainLayerAgent(init_feature_count=len(self.feature_catalog), top_n_after_growth=5)
        self.classifier = ClassificationAgent()
        self.validator = ValidationLayer()

    def run(self, input_csv: str | Path, output_dir: str | Path, max_reviews: int = 100) -> dict:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        reviews = self._load_reviews(input_csv, max_reviews=max_reviews)
        review_outputs = []
        feature_counter = Counter()
        sentiment_counter = defaultdict(Counter)

        for review in reviews:
            suggestions = self.main_agent.suggest_features(review, self.feature_catalog)
            classifications = []
            for suggestion in suggestions:
                feature = self._feature_by_name(suggestion["feature"])
                classification = self.classifier.classify(review, feature, suggestion["main_score"])
                record = {
                    "feature": feature.name,
                    "main_score": suggestion["main_score"],
                    "main_reasons": suggestion["main_reasons"],
                    "classification": classification,
                }
                classifications.append(record)
                if classification["is_related"]:
                    feature_counter[feature.name] += 1
                    sentiment_counter[feature.name][classification["feature_sentiment"]] += 1

            validation = self.validator.validate(review, classifications)
            review_outputs.append({
                "review_id": review.review_id,
                "rating": review.rating,
                "text_preview": review.text[:220],
                "main_layer_suggestions": suggestions,
                "classification_layer": classifications,
                "validation_layer": validation,
            })

        summary = self._build_summary(review_outputs, feature_counter, sentiment_counter)
        self._write_outputs(output_dir, review_outputs, summary)
        return summary

    def _load_reviews(self, input_csv: str | Path, max_reviews: int) -> list[ReviewRecord]:
        reviews = []
        with Path(input_csv).open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for idx, row in enumerate(reader):
                if idx >= max_reviews:
                    break
                reviews.append(ReviewRecord(
                    review_id=str(idx),
                    rating=float(row.get("rating", 0) or 0),
                    text=(row.get("text") or row.get("content") or "").strip(),
                ))
        return reviews

    def _feature_by_name(self, name: str):
        for feature in self.feature_catalog:
            if feature.name == name:
                return feature
        raise KeyError(name)

    def _build_summary(self, review_outputs, feature_counter, sentiment_counter):
        confirmed_reviews = [item for item in review_outputs if item["validation_layer"]["confirmed_feature_count"] > 0]
        avg_score = 0.0
        if review_outputs:
            avg_score = sum(item["validation_layer"]["preliminary_overall_score"] for item in review_outputs) / len(review_outputs)

        feature_summary = []
        for feature_name, count in feature_counter.most_common():
            feature_summary.append({
                "feature": feature_name,
                "confirmed_reviews": count,
                "sentiment_breakdown": dict(sentiment_counter[feature_name]),
            })

        return {
            "prototype_scope": "three-layer pipeline before backflow thresholding",
            "reviews_processed": len(review_outputs),
            "reviews_with_confirmed_features": len(confirmed_reviews),
            "average_preliminary_overall_score": round(avg_score, 4),
            "top_features": feature_summary,
        }

    def _write_outputs(self, output_dir: Path, review_outputs: list[dict], summary: dict) -> None:
        (output_dir / "preliminary_run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (output_dir / "review_diagnostics.json").write_text(json.dumps(review_outputs, indent=2), encoding="utf-8")

        with (output_dir / "review_feature_assignments.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "review_id", "rating", "validated_features", "bundle_confidence",
                "coverage_score", "coherence_score", "preliminary_overall_score",
            ])
            writer.writeheader()
            for item in review_outputs:
                validation = item["validation_layer"]
                writer.writerow({
                    "review_id": item["review_id"],
                    "rating": item["rating"],
                    "validated_features": "|".join(validation["validated_feature_bundle"]),
                    "bundle_confidence": validation["bundle_confidence"],
                    "coverage_score": validation["coverage_score"],
                    "coherence_score": validation["coherence_score"],
                    "preliminary_overall_score": validation["preliminary_overall_score"],
                })
