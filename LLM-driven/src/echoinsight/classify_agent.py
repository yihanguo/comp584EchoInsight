"""ClassifyAgent: one-shot multi-feature LLM classification for one review."""

from __future__ import annotations

import json
from typing import Any

from .qwen_api import QwenClient


class ClassifyAgent:
    def __init__(self, client: QwenClient, temperature: float = 0.1):
        self.client = client
        self.temperature = temperature

    def classify(self, payload: dict) -> list[dict]:
        review_text = payload.get("review_text", "")
        features = payload.get("default_fixed_features", [])

        features_str = json.dumps(features, ensure_ascii=False, indent=2)
        prompt = f"""You are the feature classification agent in EchoInsight.
Given one customer review and a list of feature definitions, decide for each feature:
1. whether the feature is present (has_feature: true/false)
2. how strongly it is expressed (feature_score: float in [0,1])
3. a short evidence_span from the review text (or "" if absent)
4. a one-sentence reason

Rules:
- Judge semantic meaning, not exact word overlap.
- Mark has_feature true only if the feature is clearly discussed.
- Give feature_score = 0.0 when has_feature is false.
- Return JSON only: a list, one object per feature.
- Each object must have: feature, has_feature, feature_score, evidence_span, reason.

Review: {review_text}

Features:
{features_str}

Return JSON list only."""
        result = self.client.chat_json(prompt, temperature=self.temperature)
        if isinstance(result, list):
            return self._normalize(result, features)
        return []

    def _normalize(self, raw: list[dict], features: list[dict]) -> list[dict]:
        feature_names = {f["name"] for f in features}
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("feature", "")
            if not name:
                continue
            score = float(item.get("feature_score", 0.0))
            score = max(0.0, min(1.0, score))
            has_f = bool(item.get("has_feature", score > 0.5))
            out.append({
                "feature": name,
                "has_feature": has_f,
                "feature_score": score,
                "evidence_span": item.get("evidence_span", ""),
                "reason": item.get("reason", ""),
            })
        return out
