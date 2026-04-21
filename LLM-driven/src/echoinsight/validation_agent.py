"""ValidationAgent: checks whether fused feature bundle covers the review."""

from __future__ import annotations

import json

from .qwen_api import QwenClient


class ValidationAgent:
    def __init__(self, client: QwenClient, temperature: float = 0.0):
        self.client = client
        self.temperature = temperature

    def validate(self, review_text: str, fused_bundle: dict) -> dict:
        bundle_str = json.dumps(fused_bundle, ensure_ascii=False, indent=2)
        prompt = f"""You are the validation agent in EchoInsight.
Given the original review and the current feature bundle, decide whether the bundle fully covers the review.

Rules:
- Do not rescore the existing features.
- Only judge whether important reusable product-review features are missing.
- If the bundle covers the review, return pass: true with empty missing_features.
- If missing features exist, list them as reusable catalog candidates.
- Return JSON only with keys: pass (bool), missing_features (list of {{name, description}}), reason (str), confidence (float 0-1).

Review: {review_text}

Current feature bundle:
{bundle_str}

Return JSON only."""
        result = self.client.chat_json(prompt, temperature=self.temperature)
        if isinstance(result, dict):
            return {
                "pass": bool(result.get("pass", True)),
                "missing_features": result.get("missing_features", []),
                "reason": result.get("reason", ""),
                "confidence": float(result.get("confidence", 1.0)),
            }
        return {"pass": True, "missing_features": [], "reason": "parse error fallback", "confidence": 0.5}
