"""Lightweight text helpers used by the EchoInsight prototype."""

from __future__ import annotations

import math
import re
from collections import Counter

TOKEN_RE = re.compile(r"[a-z0-9']+")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "had", "has", "have", "i", "if", "in", "is", "it", "its", "my", "of",
    "on", "or", "so", "that", "the", "their", "them", "this", "to", "was",
    "were", "with",
}


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def tokenize(text: str) -> list[str]:
    return [tok for tok in TOKEN_RE.findall(normalize_text(text)) if tok not in STOPWORDS]


def token_counts(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def phrase_hits(text: str, phrases: list[str]) -> list[str]:
    normalized = normalize_text(text)
    text_tokens = set(tokenize(text))
    hits = []
    for phrase in phrases:
        normalized_phrase = normalize_text(phrase)
        if not normalized_phrase:
            continue
        phrase_tokens = tokenize(normalized_phrase)
        if len(phrase_tokens) == 1:
            if phrase_tokens[0] in text_tokens:
                hits.append(phrase)
        elif normalized_phrase in normalized:
            hits.append(phrase)
    return hits


def cosine_from_counters(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[token] * right[token] for token in set(left) & set(right))
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def bounded_score(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))
