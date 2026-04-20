"""Revised semantic GLM continuation workflow for EchoInsight.

The workflow follows SEMANTIC_GLM_WORKFLOW_PLAN.md:
1. sample reviews before the processing loop,
2. ask GLM for an initialized feature corpus,
3. reject semantically equivalent feature duplicates,
4. process reviews with the expanded corpus,
5. call GLM once or a configurable number of turns for failed reviews,
6. export trial rows for every review and final active map only when all pass.
"""

from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .agents import ClassificationAgent, MainLayerAgent, ReviewRecord, ValidationLayer
from .continuation import NamedFeatureCandidate, ThresholdCalibrator
from .features import FeatureDefinition, load_feature_catalog
from .glm_api import GLMClient
from .text_utils import bounded_score


POSITIVE_TEXT_HINTS = {
    "amazing", "awesome", "best", "comfortable", "easy", "excellent", "favorite",
    "good", "great", "happy", "like", "love", "loved", "perfect", "phenomenal",
    "recommend", "satisfied", "works",
}
NEGATIVE_TEXT_HINTS = {
    "awful", "bad", "broke", "broken", "cannot", "can't", "defective",
    "difficult", "disappointed", "hate", "hurts", "issue", "issues", "lost",
    "overpriced", "poor", "problem", "problems", "scratchy", "terrible",
    "uncomfortable", "worse",
}
RATING_COLUMN_CANDIDATES = (
    "review_rating",
    "stars",
    "star_rating",
    "score",
    "rating",
)


def safe_name(name: str) -> str:
    lowered = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    return lowered or "glm_suggested_feature"


def candidate_from_any(item: dict[str, Any]) -> NamedFeatureCandidate | None:
    try:
        name = safe_name(str(item.get("name", "")))
        if not name:
            return None
        return NamedFeatureCandidate(
            name=name,
            description=str(item.get("description") or "GLM-suggested customer experience feature.")[:500],
            seed_keywords=[str(x).strip() for x in item.get("seed_keywords", []) if str(x).strip()][:16],
            positive_keywords=[str(x).strip() for x in item.get("positive_keywords", []) if str(x).strip()][:12],
            negative_keywords=[str(x).strip() for x in item.get("negative_keywords", []) if str(x).strip()][:12],
        )
    except Exception:
        return None


def feature_to_candidate(feature: FeatureDefinition) -> NamedFeatureCandidate:
    return NamedFeatureCandidate(
        name=feature.name,
        description=feature.description,
        seed_keywords=list(feature.seed_keywords),
        positive_keywords=list(feature.positive_keywords),
        negative_keywords=list(feature.negative_keywords),
    )


class DynamicCandidateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def load(self) -> list[NamedFeatureCandidate]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        candidates: list[NamedFeatureCandidate] = []
        if not isinstance(raw, list):
            return candidates
        for item in raw:
            if isinstance(item, dict):
                candidate = candidate_from_any(item)
                if candidate:
                    candidates.append(candidate)
        return candidates

    def merge_and_save(self, candidates: list[NamedFeatureCandidate]) -> list[NamedFeatureCandidate]:
        merged = {candidate.name: candidate for candidate in self.load()}
        for candidate in candidates:
            merged[candidate.name] = candidate
        ordered = sorted(merged.values(), key=lambda item: item.name)
        self.path.write_text(json.dumps([asdict(item) for item in ordered], indent=2, ensure_ascii=False), encoding="utf-8")
        return ordered


class SemanticRunLogger:
    """Writes structured JSON logs while the run is still in progress."""

    def __init__(self, path: str | Path, metadata: dict[str, Any]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = {"metadata": metadata, "global_events": [], "reviews": []}
        self._review_index: dict[str, dict[str, Any]] = {}
        self.flush()

    def global_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.data["global_events"].append({"event_type": event_type, **payload})
        self.flush()

    def start_review(self, review: ReviewRecord, evaluation: dict[str, Any], threshold: float) -> None:
        record = {
            "review_id": review.review_id,
            "rating": review.rating,
            "text_preview": review.text[:320],
            "available_features_before_glm": evaluation["features"],
            "score_before_glm": round(evaluation["score"], 4),
            "threshold": threshold,
            "passed_initial_threshold": evaluation["score"] >= threshold,
            "events": [],
            "available_features_final": None,
            "score_final": None,
            "passed_final_threshold": None,
        }
        self.data["reviews"].append(record)
        self._review_index[review.review_id] = record
        self.flush()

    def event(self, review_id: str, event_type: str, payload: dict[str, Any]) -> None:
        record = self._review_index.get(review_id)
        if record is None:
            return
        record["events"].append({"event_type": event_type, **payload})
        self.flush()

    def finish_review(self, review_id: str, evaluation: dict[str, Any], passed: bool) -> None:
        record = self._review_index.get(review_id)
        if record is None:
            return
        record["available_features_final"] = evaluation["features"]
        record["score_final"] = round(evaluation["score"], 4)
        record["passed_final_threshold"] = passed
        self.flush()

    def flush(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)


class SemanticCandidateAgent:
    def __init__(self, glm: GLMClient):
        self.glm = glm

    def suggest_from_review(
        self,
        review: ReviewRecord,
        existing_names: set[str],
        banned_names: set[str],
        n: int,
    ) -> list[NamedFeatureCandidate]:
        prompt = f"""
You are the Main Agent in EchoInsight. A customer review did not pass the current active feature threshold.
Suggest up to {n} reusable AirPods customer-experience features that could explain the review.

Rules:
- Return JSON only as a list.
- Each item must include: name, description, seed_keywords, positive_keywords, negative_keywords.
- Use short snake_case names.
- Do not repeat or paraphrase existing feature names too closely.
- Prefer features that could apply to multiple reviews, not one-off labels.

Existing feature names:
{sorted(existing_names)}

Already attempted for this review:
{sorted(banned_names)}

Review:
{review.text[:1800]}
""".strip()
        return self._parse_candidates(self.glm.chat_json(prompt), existing_names | banned_names)

    def suggest_from_sample(
        self,
        sampled_reviews: list[ReviewRecord],
        existing_names: set[str],
        n: int,
    ) -> list[NamedFeatureCandidate]:
        review_payload = [
            {"review_id": review.review_id, "text": review.text[:900]}
            for review in sampled_reviews
        ]
        prompt = f"""
You are building the initialized feature corpus for EchoInsight.
Read these sampled AirPods reviews and suggest up to {n} reusable customer-experience features.

Rules:
- Return JSON only as a list.
- Each item must include: name, description, seed_keywords, positive_keywords, negative_keywords.
- Use short snake_case names.
- Avoid existing features and near-duplicates.
- Features should represent semantic topics customers discuss, even if exact words vary.

Existing feature names:
{sorted(existing_names)}

Sampled reviews JSON:
{json.dumps(review_payload, ensure_ascii=False)}
""".strip()
        return self._parse_candidates(self.glm.chat_json(prompt), existing_names)

    def _parse_candidates(self, parsed: Any, forbidden_names: set[str]) -> list[NamedFeatureCandidate]:
        if not isinstance(parsed, list):
            return []
        candidates: list[NamedFeatureCandidate] = []
        seen: set[str] = set()
        for item in parsed:
            if not isinstance(item, dict):
                continue
            candidate = candidate_from_any(item)
            if not candidate or candidate.name in forbidden_names or candidate.name in seen:
                continue
            candidates.append(candidate)
            seen.add(candidate.name)
        return candidates


class SemanticEquivalenceAgent:
    def __init__(self, glm: GLMClient):
        self.glm = glm

    def check(self, candidate: NamedFeatureCandidate, corpus: list[NamedFeatureCandidate]) -> dict[str, Any]:
        compact_corpus = [
            {
                "name": item.name,
                "description": item.description,
                "seed_keywords": item.seed_keywords[:8],
            }
            for item in corpus
        ]
        prompt = f"""
You are the feature deduplication agent in EchoInsight.
Decide whether the candidate feature is semantically equivalent to any existing feature.

Equivalent means it describes the same customer-experience dimension, even if the words are different.
Do not use a numeric score.

Return JSON only with this schema:
{{
  "equivalent": true or false,
  "equivalent_feature_name": string or null,
  "reason": "short reason"
}}

Candidate feature:
{json.dumps(asdict(candidate), ensure_ascii=False)}

Existing feature corpus:
{json.dumps(compact_corpus, ensure_ascii=False)}
""".strip()
        parsed = self.glm.chat_json(prompt)
        if not isinstance(parsed, dict):
            return {
                "equivalent": False,
                "equivalent_feature_name": None,
                "reason": "GLM returned a non-object response; treated as non-equivalent so the run can continue.",
            }
        return {
            "equivalent": bool(parsed.get("equivalent", False)),
            "equivalent_feature_name": parsed.get("equivalent_feature_name"),
            "reason": str(parsed.get("reason", ""))[:500],
        }


class SemanticGLMContinuationWorkflow:
    def __init__(
        self,
        feature_catalog_path: str | Path,
        info_path: str | Path,
        dynamic_pool_path: str | Path,
        request_delay: float = 0.2,
        glm_rpm: float = 60.0,
        glm_timeout: float = 100.0,
        disable_thinking: bool = True,
        sglang_disable_thinking: bool = False,
    ):
        self.feature_catalog_path = Path(feature_catalog_path)
        self.base_features = load_feature_catalog(feature_catalog_path)
        self.threshold_calibrator = ThresholdCalibrator()
        self.glm = GLMClient(
            info_path=info_path,
            request_delay=request_delay,
            rpm=glm_rpm,
            timeout=glm_timeout,
            disable_thinking=disable_thinking,
            sglang_disable_thinking=sglang_disable_thinking,
        )
        self.suggester = SemanticCandidateAgent(self.glm)
        self.equivalence = SemanticEquivalenceAgent(self.glm)
        self.dynamic_store = DynamicCandidateStore(dynamic_pool_path)

    def run(
        self,
        input_csv: str | Path,
        output_dir: str | Path,
        max_reviews: int = 50,
        init_sample_size: int = 100,
        random_seed: int = 584,
        init_batch_size: int = 20,
        init_features_per_batch: int = 8,
        glm_suggestion_turns: int = 1,
        max_candidates_per_turn: int = 4,
        persist_initialized_corpus: bool = True,
    ) -> dict[str, Any]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        all_reviews = self._load_reviews(input_csv, max_reviews=None)
        reviews = all_reviews[:max_reviews] if max_reviews else all_reviews
        run_logger = SemanticRunLogger(
            output_dir / "semantic_glm_run_log.json",
            {
                "input_csv": str(input_csv),
                "max_reviews": max_reviews,
                "init_sample_size": init_sample_size,
                "random_seed": random_seed,
                "init_batch_size": init_batch_size,
                "init_features_per_batch": init_features_per_batch,
                "glm_suggestion_turns": glm_suggestion_turns,
                "max_candidates_per_turn": max_candidates_per_turn,
                "workflow": "sample_initial_corpus_then_per_review_semantic_glm_backflow",
            },
        )

        sampled_reviews = self._sample_initial_reviews(all_reviews, init_sample_size, random_seed)
        self._write_sample(output_dir, sampled_reviews)
        run_logger.global_event("initial_review_sample_selected", {
            "sampled_review_ids": [review.review_id for review in sampled_reviews],
            "sample_size": len(sampled_reviews),
        })

        base_candidates = [feature_to_candidate(feature) for feature in self.base_features]
        existing_dynamic = self.dynamic_store.load()
        corpus = self._dedupe_candidates(base_candidates + existing_dynamic)
        initial_added, candidate_decisions = self._build_initialized_corpus(
            sampled_reviews=sampled_reviews,
            corpus=corpus,
            init_batch_size=init_batch_size,
            init_features_per_batch=init_features_per_batch,
            run_logger=run_logger,
        )
        corpus = self._dedupe_candidates(corpus + initial_added)
        if persist_initialized_corpus:
            self.dynamic_store.merge_and_save(existing_dynamic + initial_added)
        self._write_initialized_corpus(output_dir, corpus)

        initial_evaluations = [self._evaluate_review(review, corpus) for review in reviews]
        threshold_info = self.threshold_calibrator.calibrate([item["score"] for item in initial_evaluations])
        threshold = threshold_info["threshold"]
        run_logger.global_event("threshold_calibrated", threshold_info)

        rows: list[dict[str, Any]] = []
        accepted_counter: Counter[str] = Counter()
        generated_counter: Counter[str] = Counter()

        for index, review in enumerate(reviews, start=1):
            print(f"[semantic-glm] review {index}/{len(reviews)} id={review.review_id}", flush=True)
            evaluation = initial_evaluations[index - 1]
            final_evaluation = evaluation
            accepted_new_features: list[str] = []
            rejected_equivalent: list[str] = []
            evaluated_candidate_names: set[str] = set(final_evaluation["features"])
            run_logger.start_review(review, evaluation, threshold)

            if final_evaluation["score"] < threshold:
                for turn in range(1, glm_suggestion_turns + 1):
                    existing_names = {item.name for item in corpus}
                    banned_names = evaluated_candidate_names | set(accepted_new_features) | set(rejected_equivalent)
                    run_logger.event(review.review_id, "glm_failed_review_suggestion_request", {
                        "turn": turn,
                        "current_score": round(final_evaluation["score"], 4),
                        "threshold": threshold,
                        "available_features": final_evaluation["features"],
                        "existing_feature_count": len(existing_names),
                        "banned_names": sorted(banned_names),
                    })
                    print(f"[semantic-glm] requesting new GLM candidates for review {review.review_id}", flush=True)
                    generated = self.suggester.suggest_from_review(
                        review=review,
                        existing_names=existing_names,
                        banned_names=banned_names,
                        n=max_candidates_per_turn,
                    )
                    generated_counter.update(candidate.name for candidate in generated)
                    run_logger.event(review.review_id, "glm_failed_review_suggestion_result", {
                        "turn": turn,
                        "generated_features": [asdict(candidate) for candidate in generated],
                    })

                    if not generated:
                        break

                    forced_names: list[str] = []
                    for candidate in generated:
                        if candidate.name in evaluated_candidate_names:
                            continue
                        evaluated_candidate_names.add(candidate.name)
                        decision = self._check_and_maybe_add_candidate(
                            candidate=candidate,
                            corpus=corpus,
                            source="per_review_backflow",
                            review_id=review.review_id,
                            run_logger=run_logger,
                            candidate_decisions=candidate_decisions,
                        )
                        if decision["added_to_corpus"]:
                            corpus.append(candidate)
                            corpus = self._dedupe_candidates(corpus)
                            accepted_new_features.append(candidate.name)
                            accepted_counter[candidate.name] += 1
                            forced_names.append(candidate.name)
                        else:
                            rejected_equivalent.append(candidate.name)

                    if forced_names:
                        final_evaluation = self._evaluate_review(review, corpus, forced_feature_names=set(forced_names))
                        run_logger.event(review.review_id, "review_re_evaluated_after_glm_additions", {
                            "turn": turn,
                            "forced_new_features": forced_names,
                            "new_available_features": final_evaluation["features"],
                            "new_score": round(final_evaluation["score"], 4),
                            "threshold": threshold,
                            "passed_threshold": final_evaluation["score"] >= threshold,
                        })
                    if final_evaluation["score"] >= threshold:
                        break

            passed = final_evaluation["score"] >= threshold
            run_logger.finish_review(review.review_id, final_evaluation, passed)
            rows.append({
                "review_id": review.review_id,
                "rating": review.rating,
                "text_preview": review.text[:260].replace("\n", " "),
                "available_features_before_glm": "|".join(evaluation["features"]),
                "feature_scores_before_glm": json.dumps(evaluation["feature_scores"], ensure_ascii=False),
                "score_before_glm": round(evaluation["score"], 4),
                "threshold": threshold,
                "passed_initial_threshold": evaluation["score"] >= threshold,
                "accepted_new_features": "|".join(accepted_new_features),
                "rejected_equivalent_features": "|".join(rejected_equivalent),
                "available_features_final": "|".join(final_evaluation["features"]),
                "feature_scores_final": json.dumps(final_evaluation["feature_scores"], ensure_ascii=False),
                "score_final": round(final_evaluation["score"], 4),
                "passed_final_threshold": passed,
            })

        if persist_initialized_corpus:
            dynamic_only = [
                candidate for candidate in corpus
                if candidate.name not in {feature.name for feature in self.base_features}
            ]
            self.dynamic_store.merge_and_save(dynamic_only)
        all_passed = all(row["passed_final_threshold"] for row in rows)
        self._write_outputs(
            output_dir=output_dir,
            rows=rows,
            candidate_decisions=candidate_decisions,
            threshold_info=threshold_info,
            accepted_counter=accepted_counter,
            generated_counter=generated_counter,
            initial_added=initial_added,
            corpus=corpus,
            all_passed=all_passed,
        )
        return {
            "reviews_processed": len(rows),
            "threshold": threshold,
            "final_pass_count": sum(row["passed_final_threshold"] for row in rows),
            "all_reviews_passed": all_passed,
            "accepted_new_feature_counts": dict(accepted_counter.most_common()),
            "generated_new_feature_counts": dict(generated_counter.most_common()),
            "initialized_feature_count": len(corpus),
            "initial_glm_features_added": len(initial_added),
            "output_dir": str(output_dir),
        }

    def _load_reviews(self, input_csv: str | Path, max_reviews: int | None) -> list[ReviewRecord]:
        reviews: list[ReviewRecord] = []
        with Path(input_csv).open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for idx, row in enumerate(reader):
                if max_reviews is not None and idx >= max_reviews:
                    break
                text = (row.get("text") or row.get("content") or "").strip()
                if not text:
                    continue
                reviews.append(ReviewRecord(
                    review_id=str(idx),
                    rating=self._resolve_rating(row, text),
                    text=text,
                ))
        return reviews

    def _sample_initial_reviews(self, reviews: list[ReviewRecord], sample_size: int, random_seed: int) -> list[ReviewRecord]:
        if sample_size <= 0:
            return []
        rng = random.Random(random_seed)
        target_size = min(sample_size, len(reviews))
        by_rating: dict[int, list[ReviewRecord]] = {}
        for review in reviews:
            by_rating.setdefault(round(review.rating), []).append(review)
        if len(by_rating) <= 1:
            return rng.sample(reviews, target_size)

        sampled: list[ReviewRecord] = []
        buckets = sorted(by_rating.items(), key=lambda item: item[0])
        base_take = max(1, target_size // len(buckets))
        for _, bucket in buckets:
            take = min(base_take, len(bucket), target_size - len(sampled))
            if take > 0:
                sampled.extend(rng.sample(bucket, take))
        remaining = [review for review in reviews if review.review_id not in {item.review_id for item in sampled}]
        if len(sampled) < target_size and remaining:
            sampled.extend(rng.sample(remaining, target_size - len(sampled)))
        rng.shuffle(sampled)
        return sampled

    def _resolve_rating(self, row: dict[str, str], text: str) -> float:
        for column in RATING_COLUMN_CANDIDATES:
            value = row.get(column)
            if value in (None, ""):
                continue
            try:
                rating = float(value)
            except ValueError:
                continue
            if column != "rating" or rating != 3.0:
                return self._normalize_rating(rating)

        # The AirPods pipeline input was generated with neutral placeholder ratings.
        # When that is the only usable rating, infer a lightweight sentiment rating
        # from the review text so sampling and exports are not artificially all 3.0.
        return self._infer_rating_from_text(text)

    def _normalize_rating(self, rating: float) -> float:
        if rating > 5 and rating <= 10:
            rating = rating / 2
        if rating > 10 and rating <= 100:
            rating = rating / 20
        return max(1.0, min(5.0, rating))

    def _infer_rating_from_text(self, text: str) -> float:
        tokens = re.findall(r"[a-zA-Z']+", text.lower())
        positive = sum(1 for token in tokens if token in POSITIVE_TEXT_HINTS)
        negative = sum(1 for token in tokens if token in NEGATIVE_TEXT_HINTS)
        lowered = text.lower()
        positive += sum(1 for phrase in ("works great", "sound quality is great", "love these", "highly recommend") if phrase in lowered)
        negative += sum(1 for phrase in ("not good", "isn't good", "doesn't work", "do not recommend", "too much", "no name brands") if phrase in lowered)
        if positive >= negative + 2:
            return 5.0
        if positive > negative:
            return 4.0
        if negative >= positive + 2:
            return 1.0
        if negative > positive:
            return 2.0
        return 3.0

    def _write_sample(self, output_dir: Path, sampled_reviews: list[ReviewRecord]) -> None:
        payload = [
            {
                "review_id": review.review_id,
                "rating": review.rating,
                "text_preview": review.text[:500],
            }
            for review in sampled_reviews
        ]
        (output_dir / "initial_sample_reviews.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _build_initialized_corpus(
        self,
        sampled_reviews: list[ReviewRecord],
        corpus: list[NamedFeatureCandidate],
        init_batch_size: int,
        init_features_per_batch: int,
        run_logger: SemanticRunLogger,
    ) -> tuple[list[NamedFeatureCandidate], list[dict[str, Any]]]:
        added: list[NamedFeatureCandidate] = []
        decisions: list[dict[str, Any]] = []
        if not sampled_reviews:
            return added, decisions
        for start in range(0, len(sampled_reviews), max(init_batch_size, 1)):
            batch = sampled_reviews[start:start + max(init_batch_size, 1)]
            existing_names = {item.name for item in corpus + added}
            run_logger.global_event("glm_initial_corpus_generation_request", {
                "batch_start": start,
                "batch_review_ids": [review.review_id for review in batch],
                "existing_feature_count": len(existing_names),
            })
            print(f"[semantic-glm] requesting initialized corpus features for sample batch {start // max(init_batch_size, 1) + 1}", flush=True)
            generated = self.suggester.suggest_from_sample(batch, existing_names, init_features_per_batch)
            run_logger.global_event("glm_initial_corpus_generation_result", {
                "batch_start": start,
                "generated_features": [asdict(candidate) for candidate in generated],
            })
            for candidate in generated:
                decision = self._check_and_maybe_add_candidate(
                    candidate=candidate,
                    corpus=corpus + added,
                    source="initial_sample_corpus",
                    review_id=None,
                    run_logger=run_logger,
                    candidate_decisions=decisions,
                )
                if decision["added_to_corpus"]:
                    added.append(candidate)
        return added, decisions

    def _check_and_maybe_add_candidate(
        self,
        candidate: NamedFeatureCandidate,
        corpus: list[NamedFeatureCandidate],
        source: str,
        review_id: str | None,
        run_logger: SemanticRunLogger,
        candidate_decisions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        existing_names = {item.name for item in corpus}
        if candidate.name in existing_names:
            equivalence = {
                "equivalent": True,
                "equivalent_feature_name": candidate.name,
                "reason": "Candidate name already exists in the feature corpus.",
            }
        else:
            equivalence = self.equivalence.check(candidate, corpus)
        added = not equivalence["equivalent"]
        decision = {
            "source": source,
            "review_id": review_id,
            "candidate": asdict(candidate),
            "equivalence": equivalence,
            "added_to_corpus": added,
        }
        candidate_decisions.append(decision)
        event_type = "candidate_added_to_corpus" if added else "candidate_rejected_as_equivalent"
        payload = {
            "source": source,
            "candidate": asdict(candidate),
            "equivalence": equivalence,
            "added_to_corpus": added,
        }
        if review_id is None:
            run_logger.global_event(event_type, payload)
        else:
            run_logger.event(review_id, event_type, payload)
        return decision

    def _evaluate_review(
        self,
        review: ReviewRecord,
        corpus: list[NamedFeatureCandidate],
        forced_feature_names: set[str] | None = None,
    ) -> dict[str, Any]:
        features = [candidate.to_feature_definition() for candidate in corpus]
        feature_by_name = {feature.name: feature for feature in features}
        main_agent = MainLayerAgent(init_feature_count=len(features), top_n_after_growth=8)
        classifier = ClassificationAgent()
        validator = ValidationLayer()
        suggestions = main_agent.suggest_features(review, features)
        suggestion_by_name = {item["feature"]: item for item in suggestions}
        for name in forced_feature_names or set():
            if name in feature_by_name and name not in suggestion_by_name:
                suggestion_by_name[name] = {
                    "feature": name,
                    "main_score": 0.35,
                    "main_reasons": {
                        "forced_by_glm_backflow": True,
                    },
                }
        classifications = []
        for suggestion in suggestion_by_name.values():
            feature = feature_by_name[suggestion["feature"]]
            classification = classifier.classify(review, feature, suggestion["main_score"])
            classifications.append({
                "feature": feature.name,
                "main_score": suggestion["main_score"],
                "main_reasons": suggestion["main_reasons"],
                "classification": classification,
            })
        validation = validator.validate(review, classifications)
        feature_scores = self._score_related_features(classifications)
        return {
            "features": validation["validated_feature_bundle"],
            "feature_scores": feature_scores,
            "score": validation["preliminary_overall_score"],
            "validation": validation,
            "classifications": classifications,
        }

    def _score_related_features(self, classifications: list[dict[str, Any]]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for item in classifications:
            feature_name = item["feature"]
            classification = item["classification"]
            if not classification["is_related"]:
                scores[feature_name] = 0.0
                continue
            evidence = classification["evidence"]
            evidence_hits = (
                len(evidence.get("seed_hits", []))
                + len(evidence.get("positive_hits", []))
                + len(evidence.get("negative_hits", []))
            )
            evidence_score = min(evidence_hits / 4.0, 1.0)
            main_reasons = item.get("main_reasons", {})
            semantic_similarity = float(main_reasons.get("description_similarity", item.get("main_score", 0.0)) or 0.0)
            score = (
                0.45 * float(classification["classification_confidence"])
                + 0.35 * semantic_similarity
                + 0.20 * evidence_score
            )
            scores[feature_name] = round(bounded_score(score), 4)
        return scores

    def _dedupe_candidates(self, candidates: list[NamedFeatureCandidate]) -> list[NamedFeatureCandidate]:
        deduped: dict[str, NamedFeatureCandidate] = {}
        for candidate in candidates:
            deduped[candidate.name] = candidate
        return list(deduped.values())

    def _write_initialized_corpus(self, output_dir: Path, corpus: list[NamedFeatureCandidate]) -> None:
        (output_dir / "initialized_feature_corpus.json").write_text(
            json.dumps([asdict(candidate) for candidate in corpus], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _write_outputs(
        self,
        output_dir: Path,
        rows: list[dict[str, Any]],
        candidate_decisions: list[dict[str, Any]],
        threshold_info: dict[str, Any],
        accepted_counter: Counter[str],
        generated_counter: Counter[str],
        initial_added: list[NamedFeatureCandidate],
        corpus: list[NamedFeatureCandidate],
        all_passed: bool,
    ) -> None:
        feature_score_rows = self._build_feature_score_rows(rows, corpus)
        trial_path = output_dir / "semantic_active_feature_map_trial.csv"
        fieldnames = list(feature_score_rows[0].keys()) if feature_score_rows else [
            "review_id", "rating", "text_preview", "threshold",
            "score_before_glm", "score_after_glm", "passed_final_threshold",
        ]
        with trial_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(feature_score_rows)

        detailed_path = output_dir / "semantic_active_feature_map_detailed.csv"
        detailed_fieldnames = list(rows[0].keys()) if rows else []
        if detailed_fieldnames:
            with detailed_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=detailed_fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        final_path: Path | None = None
        if all_passed:
            final_path = output_dir / "final_active_feature_map.csv"
            with final_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(feature_score_rows)

        (output_dir / "semantic_support_records.json").write_text(
            json.dumps(candidate_decisions, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        failed = [row for row in rows if not row["passed_final_threshold"]]
        summary = {
            "scope": "revised_semantic_glm_sample_initialized_feature_corpus",
            "threshold_calibration": threshold_info,
            "reviews_processed": len(rows),
            "final_pass_count": len(rows) - len(failed),
            "all_reviews_passed_before_final_active_map": all_passed,
            "final_active_feature_map_exported": bool(final_path),
            "trial_active_feature_map": str(trial_path),
            "final_active_feature_map": str(final_path) if final_path else "not_exported_because_some_reviews_failed_threshold",
            "detailed_trial_active_feature_map": str(detailed_path),
            "semantic_glm_run_log": str(output_dir / "semantic_glm_run_log.json"),
            "semantic_support_records": str(output_dir / "semantic_support_records.json"),
            "initialized_feature_corpus": str(output_dir / "initialized_feature_corpus.json"),
            "initial_sample_reviews": str(output_dir / "initial_sample_reviews.json"),
            "initial_glm_features_added": [candidate.name for candidate in initial_added],
            "initialized_feature_count": len(corpus),
            "accepted_new_feature_counts": dict(accepted_counter.most_common()),
            "generated_new_feature_counts": dict(generated_counter.most_common()),
            "failed_review_ids": [row["review_id"] for row in failed],
        }
        (output_dir / "semantic_glm_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        self._write_report(output_dir, summary, rows)

    def _build_feature_score_rows(self, rows: list[dict[str, Any]], corpus: list[NamedFeatureCandidate]) -> list[dict[str, Any]]:
        feature_names = [candidate.name for candidate in self._dedupe_candidates(corpus)]
        feature_score_rows: list[dict[str, Any]] = []
        for row in rows:
            feature_scores = json.loads(row.get("feature_scores_final") or "{}")
            output_row: dict[str, Any] = {
                "review_id": row["review_id"],
                "rating": row["rating"],
                "text_preview": row["text_preview"],
            }
            for feature_name in feature_names:
                output_row[feature_name] = round(float(feature_scores.get(feature_name, 0.0) or 0.0), 4)
            output_row.update({
                "threshold": row["threshold"],
                "score_before_glm": row["score_before_glm"],
                "score_after_glm": row["score_final"],
                "passed_final_threshold": row["passed_final_threshold"],
            })
            feature_score_rows.append(output_row)
        return feature_score_rows

    def _write_report(self, output_dir: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        lines = [
            "# Revised Semantic GLM Continuation Report",
            "",
            f"- Reviews processed: {summary['reviews_processed']}",
            f"- Final pass count: {summary['final_pass_count']}",
            f"- All reviews passed before final active map: {summary['all_reviews_passed_before_final_active_map']}",
            f"- Final active feature map exported: {summary['final_active_feature_map_exported']}",
            f"- Initialized feature count: {summary['initialized_feature_count']}",
            "",
            "## Initial GLM Features Added",
            "",
        ]
        if summary["initial_glm_features_added"]:
            for feature in summary["initial_glm_features_added"]:
                lines.append(f"- {feature}")
        else:
            lines.append("- None")
        lines.extend(["", "## Per-Review New Feature Counts", ""])
        if summary["accepted_new_feature_counts"]:
            for feature, count in summary["accepted_new_feature_counts"].items():
                lines.append(f"- {feature}: {count}")
        else:
            lines.append("- None")
        lines.extend(["", "## Sample Rows", ""])
        for row in rows[:12]:
            lines.extend([
                f"### Review {row['review_id']}",
                f"- Score before GLM: {row['score_before_glm']}",
                f"- Threshold: {row['threshold']}",
                f"- Passed initial threshold: {row['passed_initial_threshold']}",
                f"- Accepted new features: {row['accepted_new_features'] or 'None'}",
                f"- Score final: {row['score_final']}",
                f"- Passed final threshold: {row['passed_final_threshold']}",
                f"- Text: {row['text_preview']}",
                "",
            ])
        (output_dir / "semantic_glm_report.md").write_text("\n".join(lines), encoding="utf-8")
