"""MasterAgent: owns feature space — init, routing, dynamic expansion."""

from __future__ import annotations

import json
import random
from typing import Any

from .qwen_api import QwenClient


class MasterAgent:
    def __init__(
        self,
        client: QwenClient,
        temperature: float = 0.2,
        chunk_max_reviews: int = 4,
        chunk_max_chars: int = 6000,
    ):
        self.client = client
        self.temperature = temperature
        self.feature_catalog: list[dict] = []
        self._last_sampled_texts: dict[str, str] = {}
        self.chunk_max_reviews = chunk_max_reviews
        self.chunk_max_chars = chunk_max_chars

    # ── init ──────────────────────────────────────────────────────────────

    def sample_reviews(self, reviews: list[dict], sample_size: int) -> list[dict]:
        k = min(sample_size, len(reviews))
        return random.sample(reviews, k)

    def extract_initial_features(self, sampled_reviews: list[dict]) -> list[dict]:
        all_features: list[dict] = []
        indexed_all: dict[str, str] = {}

        for chunk_start, chunk in self._initial_review_chunks(sampled_reviews):
            indexed = {str(chunk_start + i + 1): r["review_text"] for i, r in enumerate(chunk)}
            indexed_all.update(indexed)
            result = self._extract_initial_features_chunk(indexed)
            if isinstance(result, list):
                all_features.extend(result)
            elif isinstance(result, dict) and "features" in result:
                all_features.extend(result["features"])

        self._last_sampled_texts = indexed_all
        return self.dedupe_features(all_features)

    def _extract_initial_features_chunk(self, indexed_reviews: dict[str, str]) -> Any:
        texts = "\n".join(f"[{k}] {v}" for k, v in indexed_reviews.items())
        prompt = f"""You are the master agent in EchoInsight.
Read these sampled customer reviews and extract reusable product-review features.

Rules:
- Return reusable feature names, not one-off phrases.
- Use snake_case names.
- Keep descriptions short and general (1 sentence).
- For "examples": copy the full sentence or clause from the review that best illustrates the feature. Do NOT paraphrase or invent text.
- Each example must be a verbatim substring from one of the numbered reviews below.
- Include 1-3 examples per feature.
- Avoid duplicates and near-duplicates.
- Return JSON only: a list of objects with keys: name, description, examples.
- Let the data decide how many features — extract as many or as few reusable features as the reviews actually warrant.

Reviews:
{texts}

Return JSON list only."""
        return self.client.chat_json(prompt, temperature=self.temperature)

    def _initial_review_chunks(self, sampled_reviews: list[dict]) -> list[tuple[int, list[dict]]]:
        if not sampled_reviews:
            return [(0, [])]

        max_reviews_per_chunk = self.chunk_max_reviews
        max_chars_per_chunk = self.chunk_max_chars
        chunks: list[tuple[int, list[dict]]] = []
        chunk: list[dict] = []
        chunk_chars = 0
        chunk_start = 0

        for idx, review in enumerate(sampled_reviews):
            text = review.get("review_text", "")
            text_len = len(text)
            if not chunk:
                chunk_start = idx
            if chunk and (
                len(chunk) >= max_reviews_per_chunk
                or chunk_chars + text_len > max_chars_per_chunk
            ):
                chunks.append((chunk_start, chunk))
                chunk = []
                chunk_chars = 0
                chunk_start = idx
            chunk.append(review)
            chunk_chars += text_len

        if chunk:
            chunks.append((chunk_start, chunk))
        return chunks

    def dedupe_features(self, features: list[dict]) -> list[dict]:
        seen: set[str] = set()
        deduped: list[dict] = []
        for f in features:
            if not isinstance(f, dict):
                continue
            name = f.get("name", "").lower().strip()
            if name and name not in seen:
                seen.add(name)
                deduped.append(f)
        return deduped

    def build_initial_catalog(
        self,
        reviews: list[dict],
        sample_size: int = 20,
        max_features: int = 40,
    ) -> list[dict]:
        sampled = self.sample_reviews(reviews, sample_size)
        raw_features = self.extract_initial_features(sampled)
        deduped = self.dedupe_features(raw_features)
        self.feature_catalog = deduped[:max_features]
        if len(deduped) > max_features:
            print(f"[V2] Feature catalog capped at {max_features} (extracted {len(deduped)})")
        return self.feature_catalog

    # ── routing ───────────────────────────────────────────────────────────

    def route_review(self, review: dict) -> dict:
        return {
            "review_id": review.get("review_id", ""),
            "review_text": review.get("review_text", ""),
            "rating": review.get("rating"),
            "default_fixed_features": [
                {"name": f["name"], "description": f.get("description", "")}
                for f in self.feature_catalog
            ],
        }

    # ── dynamic expansion ─────────────────────────────────────────────────

    def generate_dynamic_features(
        self,
        review: dict,
        validation_feedback: dict,
        existing_features: list[dict],
    ) -> list[dict]:
        existing_names = ", ".join(f.get("name", "") for f in existing_features)
        suggest_feature = validation_feedback.get("suggest_feature")
        suggestion_str = json.dumps(suggest_feature, ensure_ascii=False)
        prompt = f"""You are the master agent in EchoInsight.
The current feature bundle does not fully cover this review.
Generate one reusable missing feature based on the review and validation feedback.

Rules:
- Do not repeat existing features: {existing_names}
- Generate at most ONE feature.
- Use a reusable catalog-style feature, not a one-off phrase.
- Prefer a broad feature dimension that could apply to future reviews.
- Use snake_case names.
- Return JSON only: a single object with keys name, description, examples.
- For examples, copy 1-3 verbatim substrings from the review.

Review: {review.get('review_text', '')}
Validation suggested feature: {suggestion_str}

Return JSON object only."""
        result = self.client.chat_json(prompt, temperature=self.temperature)
        if isinstance(result, dict):
            return [result]
        if isinstance(result, list):
            return result[:1]
        return []
