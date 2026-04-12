"""Feature catalog loader and data structures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .text_utils import token_counts


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    description: str
    seed_keywords: list[str]
    positive_keywords: list[str]
    negative_keywords: list[str]

    @property
    def prototype_text(self) -> str:
        parts = [self.name.replace("_", " "), self.description]
        parts.extend(self.seed_keywords)
        parts.extend(self.positive_keywords)
        parts.extend(self.negative_keywords)
        return " ".join(parts)

    @property
    def prototype_counts(self):
        return token_counts(self.prototype_text)


def load_feature_catalog(path: str | Path) -> list[FeatureDefinition]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [FeatureDefinition(**item) for item in raw]
