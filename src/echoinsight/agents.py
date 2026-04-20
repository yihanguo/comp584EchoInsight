"""Main, classification, and validation agents for the EchoInsight prototype."""

from __future__ import annotations

from dataclasses import dataclass

from .features import FeatureDefinition
from .text_utils import bounded_score, cosine_from_counters, phrase_hits, token_counts

POSITIVE_RATING_HINT = {"great", "excellent", "love", "perfect", "amazing", "good"}
NEGATIVE_RATING_HINT = {"bad", "terrible", "poor", "broke", "broken", "awful", "disappointed"}


@dataclass
class ReviewRecord:
    review_id: str
    rating: float
    text: str


class MainLayerAgent:
    """Suggests potentially related features for a review."""

    def __init__(self, init_feature_count: int = 8, top_n_after_growth: int = 5):
        self.init_feature_count = init_feature_count
        self.top_n_after_growth = top_n_after_growth

    def suggest_features(self, review: ReviewRecord, feature_catalog: list[FeatureDefinition]) -> list[dict]:
        review_counts = token_counts(review.text)
        suggestions = []

        for feature in feature_catalog:
            seed_overlap = sum(review_counts.get(token, 0) for token in token_counts(" ".join(feature.seed_keywords)))
            description_similarity = cosine_from_counters(review_counts, feature.prototype_counts)
            phrase_overlap = len(phrase_hits(review.text, feature.positive_keywords + feature.negative_keywords))
            rating_hint = self._rating_alignment(review)
            score = (
                0.65 * description_similarity
                + 0.20 * min(seed_overlap / 4.0, 1.0)
                + 0.10 * min(phrase_overlap / 2.0, 1.0)
                + 0.05 * rating_hint
            )
            suggestions.append({
                "feature": feature.name,
                "main_score": round(score, 4),
                "main_reasons": {
                    "description_similarity": round(description_similarity, 4),
                    "seed_overlap": seed_overlap,
                    "phrase_overlap": phrase_overlap,
                    "rating_alignment": round(rating_hint, 4),
                },
            })

        suggestions.sort(key=lambda item: item["main_score"], reverse=True)
        if len(feature_catalog) <= self.init_feature_count:
            return [item for item in suggestions if item["main_score"] >= 0.08]
        return suggestions[: self.top_n_after_growth]

    def _rating_alignment(self, review: ReviewRecord) -> float:
        counts = token_counts(review.text)
        positive_hint = sum(counts.get(token, 0) for token in POSITIVE_RATING_HINT)
        negative_hint = sum(counts.get(token, 0) for token in NEGATIVE_RATING_HINT)
        if review.rating >= 4:
            return bounded_score((positive_hint + 1) / (positive_hint + negative_hint + 2))
        if review.rating <= 2:
            return bounded_score((negative_hint + 1) / (positive_hint + negative_hint + 2))
        return 0.5


class ClassificationAgent:
    """Determines whether a suggested feature is truly related to a review."""

    def classify(self, review: ReviewRecord, feature: FeatureDefinition, main_score: float) -> dict:
        combined = review.text
        positive_hits = phrase_hits(combined, feature.positive_keywords)
        negative_hits = phrase_hits(combined, feature.negative_keywords)
        seed_hits = phrase_hits(combined, feature.seed_keywords)
        score = 0.35 * main_score
        score += 0.25 * min(len(seed_hits) / 2.0, 1.0)
        score += 0.20 * min(len(positive_hits) / 2.0, 1.0)
        score += 0.20 * min(len(negative_hits) / 2.0, 1.0)
        polarity = "positive" if review.rating >= 4 else "negative" if review.rating <= 2 else "mixed"
        has_strong_phrase = bool(positive_hits or negative_hits)
        has_supported_seed_match = bool(seed_hits) and score >= 0.18
        is_related = has_strong_phrase or has_supported_seed_match or main_score >= 0.24
        return {
            "is_related": is_related,
            "classification_confidence": round(bounded_score(score), 4),
            "feature_sentiment": polarity,
            "evidence": {
                "seed_hits": seed_hits[:5],
                "positive_hits": positive_hits[:5],
                "negative_hits": negative_hits[:5],
            },
        }


class ValidationLayer:
    """Evaluates the confirmed feature bundle without enforcing the future backflow threshold."""

    def validate(self, review: ReviewRecord, classifications: list[dict]) -> dict:
        confirmed = [item for item in classifications if item["classification"]["is_related"]]
        if not confirmed:
            return {
                "confirmed_feature_count": 0,
                "validated_feature_bundle": [],
                "bundle_confidence": 0.0,
                "coverage_score": 0.0,
                "coherence_score": 0.0,
                "preliminary_overall_score": 0.0,
                "threshold_status": "not_evaluated_yet",
            }

        confidences = [item["classification"]["classification_confidence"] for item in confirmed]
        evidence_terms = 0
        for item in confirmed:
            evidence = item["classification"]["evidence"]
            evidence_terms += len(evidence["seed_hits"]) + len(evidence["positive_hits"]) + len(evidence["negative_hits"])

        review_length = max(len(token_counts(review.text)), 1)
        coverage_score = bounded_score(evidence_terms / max(review_length * 0.25, 1.0))
        bundle_confidence = sum(confidences) / len(confidences)
        distinct_names = {item["feature"] for item in confirmed}
        coherence_score = bounded_score(0.55 + 0.1 * min(len(distinct_names), 3) + 0.35 * bundle_confidence)
        preliminary = round(0.45 * bundle_confidence + 0.35 * coverage_score + 0.20 * coherence_score, 4)
        return {
            "confirmed_feature_count": len(confirmed),
            "validated_feature_bundle": [item["feature"] for item in confirmed],
            "bundle_confidence": round(bundle_confidence, 4),
            "coverage_score": round(coverage_score, 4),
            "coherence_score": round(coherence_score, 4),
            "preliminary_overall_score": preliminary,
            "threshold_status": "not_evaluated_yet",
        }
