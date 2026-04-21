"""FeatureFusion: merges classifier outputs across iterations."""

from __future__ import annotations


class FeatureFusion:
    def __init__(self, min_score_to_keep: float = 0.5):
        self.min_score_to_keep = min_score_to_keep

    def fuse(self, existing: dict, new_outputs: list[dict]) -> dict:
        """Merge new classifier outputs into existing accepted_features map."""
        merged = dict(existing)
        for item in new_outputs:
            name = item.get("feature", "")
            if not name:
                continue
            score = item.get("feature_score", 0.0)
            has_f = item.get("has_feature", False)
            if name in merged:
                prev = merged[name]
                # keep higher score across iterations
                if score > prev.get("feature_score", 0.0):
                    merged[name] = {
                        "has_feature": has_f,
                        "feature_score": score,
                        "evidence_span": item.get("evidence_span", ""),
                        "reason": item.get("reason", ""),
                    }
            else:
                merged[name] = {
                    "has_feature": has_f,
                    "feature_score": score,
                    "evidence_span": item.get("evidence_span", ""),
                    "reason": item.get("reason", ""),
                }
        return merged

    def filter_positive(self, fused: dict) -> dict:
        """Keep only features with score >= threshold."""
        return {
            name: data for name, data in fused.items()
            if data.get("feature_score", 0.0) >= self.min_score_to_keep
            or data.get("has_feature", False)
        }
