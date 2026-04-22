"""ValidationAgent: checks whether relevant feature bundle covers the review."""

from __future__ import annotations

import json

from .qwen_api import QwenClient


class ValidationAgent:
    def __init__(self, client: QwenClient, temperature: float = 0.0):
        self.client = client
        self.temperature = temperature

    def validate(self, review_text: str, relevant_bundle: dict) -> dict:
        bundle_str = json.dumps(relevant_bundle, ensure_ascii=False, indent=2)
        prompt = f"""You are the validation agent in EchoInsight.
Given the original review and the current relevant feature bundle, decide whether these relevant features cover the main product-related points in the review.

Rules:
- Do not rescore the existing features.
- Do not judge sentiment. Positive, negative, and neutral mentions all count as coverage.
- Only judge whether important reusable product-review feature topics are missing.
- Do not require every sentence to be covered.
- Ignore shipping, order, seller, and customer-service issues unless they are central to product analysis.
- If the relevant feature bundle covers the main product-related points, return pass: true with empty missing_features.
- If missing features exist, list them as reusable catalog candidates.
- Return JSON only with keys: pass (bool), missing_features (list of {{name, description}}), reason (str), confidence (float 0-1).

Review: {review_text}

Current feature bundle:
{bundle_str}

Return JSON only."""
        result = self.client.chat_json(prompt, temperature=self.temperature)
        if isinstance(result, dict):
            missing = result.get("missing_features", [])
            if not isinstance(missing, list):
                missing = []
            return {
                "pass": bool(result.get("pass", True)),
                "missing_features": missing,
                "reason": result.get("reason", ""),
                "confidence": float(result.get("confidence", 1.0)),
            }
        return {"pass": True, "missing_features": [], "reason": "parse error fallback", "confidence": 0.5}
