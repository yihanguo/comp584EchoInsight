"""ClassifyAgent: per-pair review-feature classification with sentiment score."""

from __future__ import annotations

from typing import Any

from .qwen_api import QwenClient


class ClassifyAgent:
    def __init__(self, client: QwenClient, temperature: float = 0.1):
        self.client = client
        self.temperature = temperature

    def classify_one(self, review: dict, feature: dict) -> dict:
        """Classify one (review, feature) pair.

        Returns:
            {
              "feature": str,
              "is_relevant": bool,
              "score": float in [-1.0, 1.0],
              "evidence_span": str,
              "reason": str,
            }
        """
        review_text = review.get("review_text", "")
        feature_name = str(feature.get("name", "")).strip()
        feature_desc = feature.get("description", "")

        prompt = f"""You are the feature classification agent in EchoInsight.
You are given ONE customer review and ONE feature.
Decide whether the review discusses this feature, and if so, whether the sentiment is positive, negative, or neutral.

Output JSON only (a single object) with these keys:
- feature: string, must equal the feature name provided
- is_relevant: true if the review talks about this feature, false otherwise
- score: float in [-1.0, 1.0]
    * positive value -> positive sentiment about this feature
    * negative value -> negative sentiment about this feature
    * 0.0 -> neutral mention, OR not relevant
- evidence_span: a verbatim substring from the review text that supports the judgment ("" if not relevant)
- reason: one short sentence explaining the decision

Rules (must be followed strictly):
- If is_relevant == false, then score MUST be 0.0 and evidence_span MUST be "".
- If the review mentions the feature but shows no clear positive or negative attitude, set is_relevant=true and score=0.0.
- Judge semantic meaning, not exact word overlap.
- evidence_span must be copied verbatim from the review.

Feature name: {feature_name}
Feature description: {feature_desc}

Review: {review_text}

Return JSON object only."""

        result = self.client.chat_json(prompt, temperature=self.temperature)
        return self._normalize(result, feature_name)

    def _normalize(self, raw: Any, feature_name: str) -> dict:
        if isinstance(raw, list) and raw:
            raw = raw[0]
        if not isinstance(raw, dict):
            return self._empty(feature_name)

        is_relevant = bool(raw.get("is_relevant", False))
        try:
            score = float(raw.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        if score > 1.0:
            score = 1.0
        elif score < -1.0:
            score = -1.0

        evidence = str(raw.get("evidence_span", "") or "")
        reason = str(raw.get("reason", "") or "")

        if not is_relevant:
            score = 0.0
            evidence = ""

        return {
            "feature": feature_name,
            "is_relevant": is_relevant,
            "score": score,
            "evidence_span": evidence,
            "reason": reason,
        }

    @staticmethod
    def _empty(feature_name: str) -> dict:
        return {
            "feature": feature_name,
            "is_relevant": False,
            "score": 0.0,
            "evidence_span": "",
            "reason": "",
        }
