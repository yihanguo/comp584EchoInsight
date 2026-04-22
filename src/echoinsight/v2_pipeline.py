"""EchoInsightV2Pipeline: per-feature classify flow (phase 1)."""

from __future__ import annotations

import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .qwen_api import QwenClient
from .master_agent import MasterAgent
from .classify_agent import ClassifyAgent
from .validation_agent import ValidationAgent

_DEFAULT_REGISTRY = Path(__file__).parent.parent.parent / "config" / "model_registry.json"


def load_model_profile(
    registry_path: str | Path | None,
    model_alias: str | None,
) -> dict:
    """Return the model profile dict for the given alias, or the registry default."""
    path = Path(registry_path) if registry_path else _DEFAULT_REGISTRY
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    models: dict = data.get("models", {})
    alias = model_alias or data.get("default", "")
    if alias not in models:
        available = ", ".join(models.keys())
        raise ValueError(f"Unknown model alias {alias!r}. Available: {available}")
    return models[alias]


def _load_csv(csv_path: str | Path) -> list[dict]:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            text_col = next(
                (
                    c for c in row
                    if any(token in c.lower() for token in ("text", "review", "content", "body", "comment"))
                ),
                None,
            )
            rating_col = next((c for c in row if "rating" in c.lower()), None)
            if not text_col:
                continue
            text = row[text_col].strip()
            if not text:
                continue
            rows.append({
                "review_id": str(i),
                "review_text": text,
                "rating": float(row[rating_col]) if rating_col and row.get(rating_col) else None,
            })
    return rows


class EchoInsightV2Pipeline:
    def __init__(
        self,
        info_path: str | Path,
        output_root: str | Path = "results_v2",
        run_name: str = "default",
        sample_size_init: int = 20,
        max_reviews: int = 20,
        max_features: int = 40,
        chunk_max_reviews: int = 4,
        chunk_max_chars: int = 6000,
        classification_temperature: float = 0.1,
        dynamic_temperature: float = 0.2,
        validation_temperature: float = 0.0,
        csv_path: str | Path = "",
        model_alias: str | None = None,
        registry_path: str | Path | None = None,
        classify_workers: int = 1,
        max_validation_iters: int = 2,
    ):
        profile = load_model_profile(registry_path, model_alias)
        active_model = profile.get("model") or "Qwen/Qwen3.5-35B-A3B"
        active_base_url = profile.get("base_url")  # None → qwen_api reads from info.md
        print(f"[V2] Model profile: {model_alias or 'default'} → {active_model}", flush=True)

        self.client = QwenClient(
            info_path=info_path,
            timeout=float(profile.get("timeout", 60.0)),
            request_delay=float(profile.get("request_delay", 3.0)),
            rpm=float(profile.get("rpm", 10.0)),
            disable_thinking=bool(profile.get("disable_thinking", True)),
            sglang_disable_thinking=bool(profile.get("sglang_disable_thinking", False)),
            enable_thinking=profile.get("enable_thinking"),
            extra_body=profile.get("extra_body", {}),
        )
        # override model/base_url from registry if provided
        if active_base_url:
            from dataclasses import replace as dc_replace
            self.client.settings = dc_replace(
                self.client.settings,
                model=active_model,
                base_url=active_base_url,
            )
        elif active_model:
            from dataclasses import replace as dc_replace
            self.client.settings = dc_replace(self.client.settings, model=active_model)
        self.master = MasterAgent(
            self.client,
            temperature=dynamic_temperature,
            chunk_max_reviews=chunk_max_reviews,
            chunk_max_chars=chunk_max_chars,
        )
        self.classifier = ClassifyAgent(self.client, temperature=classification_temperature)
        self.validator = ValidationAgent(self.client, temperature=validation_temperature)

        self.sample_size_init = sample_size_init
        self.max_reviews = max_reviews
        self.max_features = max_features
        self.classification_temperature = classification_temperature
        self.dynamic_temperature = dynamic_temperature
        self.validation_temperature = validation_temperature
        self.classify_workers = max(1, int(classify_workers))
        self.max_validation_iters = max(1, int(max_validation_iters))
        self._csv_path = str(csv_path)
        self.initial_feature_catalog_size = 0
        self.initial_feature_catalog: list[dict] = []

        self.out_dir = Path(output_root) / run_name
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self._log_events: list[dict] = []

    # ── public entry point ────────────────────────────────────────────────

    def run(self, csv_path: str | Path) -> dict:
        self._csv_path = str(csv_path)
        t0 = time.time()

        self._progress(f"Loading reviews from {csv_path}")
        reviews = _load_csv(csv_path)
        if not reviews:
            raise ValueError(f"No reviews loaded from {csv_path}")

        self._log("run_start", {
            "input_csv": str(csv_path),
            "total_reviews_in_file": len(reviews),
            "max_reviews": self.max_reviews,
            "sample_size_init": self.sample_size_init,
            "classify_workers": self.classify_workers,
            "max_validation_iters": self.max_validation_iters,
        })

        self._progress(
            f"Loaded {len(reviews)} reviews. classify_workers={self.classify_workers} "
            f"MasterAgent init sample_size={self.sample_size_init}"
        )
        sampled = self.master.sample_reviews(reviews, self.sample_size_init)
        self._log("init_sample_selected", {"sampled_ids": [r["review_id"] for r in sampled]})

        init_t0 = time.perf_counter()
        raw_features = self.master.extract_initial_features(sampled)
        init_seconds = round(time.perf_counter() - init_t0, 2)
        deduped = self.master.dedupe_features(raw_features)
        feature_catalog = deduped[: self.max_features]
        if len(deduped) > self.max_features:
            self._progress(f"Feature catalog capped at {self.max_features} (extracted {len(deduped)})")
        self.initial_feature_catalog_size = len(feature_catalog)
        self.initial_feature_catalog = [dict(f) for f in feature_catalog]
        self.master.feature_catalog = feature_catalog
        self._log("init_catalog_built", {
            "feature_count": len(feature_catalog),
            "features": [f["name"] for f in feature_catalog],
            "agent": "MasterAgent",
            "elapsed_seconds": init_seconds,
        })
        self._progress(f"MasterAgent init complete: {len(feature_catalog)} features in {init_seconds}s")
        self._save_json("initialized_feature_corpus.json", feature_catalog)

        batch = reviews[: self.max_reviews]
        review_records: list[dict] = []
        total_batch = len(batch)
        total_pairs_planned = total_batch * len(feature_catalog)
        self._progress(
            f"Classify plan: {total_batch} reviews x {len(feature_catalog)} initial features = {total_pairs_planned} pairs "
            f"({'serial' if self.classify_workers <= 1 else f'parallel workers={self.classify_workers}'})"
        )

        diag_path = self.out_dir / "review_level_diagnostics.jsonl"
        diag_path.write_text("", encoding="utf-8")  # truncate / create

        run_start = time.perf_counter()
        pairs_done = 0
        for index, review in enumerate(batch, start=1):
            rid = review["review_id"]
            self._progress(
                f"Review {index}/{total_batch} id={rid} start "
                f"({len(review['review_text'])} chars): {review['review_text'][:60]}..."
            )
            record = self._process_review(review, feature_catalog, index, total_batch)
            review_records.append(record)
            pairs_done += record["diagnostics"]["features_classified"]
            diag = record["diagnostics"]

            rate = pairs_done / max(time.perf_counter() - run_start, 1e-6)
            remaining = max(total_pairs_planned - pairs_done, 0)
            eta_s = remaining / rate if rate > 0 else 0.0
            err_n = len(diag.get("classify_errors", []))
            self._progress(
                f"Review {index}/{total_batch} id={rid} done in {record['elapsed_seconds']}s "
                f"| relevant={len(diag['relevant_features'])} "
                f"pos={len(diag['positive_features'])} neg={len(diag['negative_features'])} "
                f"neu={len(diag['neutral_features'])} errors={err_n} "
                f"validation={diag.get('validation_pass')} "
                f"| rate={rate:.2f} pair/s ETA {_fmt_eta(eta_s)}"
            )

            # flush diagnostics for this review immediately
            with diag_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(diag, ensure_ascii=False) + "\n")

            # refresh outputs after every record
            self._export_feature_map(review_records, feature_catalog)
            self._save_json("final_feature_catalog.json", feature_catalog)
            self._save_json("feature_scores_detail.json", [
                {"review_id": r["review_id"], "features": r["features"]}
                for r in review_records
            ])
            elapsed_so_far = round(time.time() - t0, 1)
            self._save_json("v2_summary.json", self._build_summary(feature_catalog, review_records, elapsed_so_far))

        elapsed = round(time.time() - t0, 1)
        self._log("run_complete", {"elapsed_seconds": elapsed, "reviews_processed": len(review_records)})

        self._save_json("v2_run_log.json", self._build_run_log(feature_catalog))
        self._save_json("final_feature_catalog.json", feature_catalog)
        summary = self._build_summary(feature_catalog, review_records, elapsed)
        self._save_json("v2_summary.json", summary)
        self._write_report(feature_catalog, review_records, summary)
        self._progress(f"Saved {diag_path.name} ({len(review_records)} records)")

        if pairs_done:
            avg_pair = elapsed / pairs_done
            self._progress(
                f"Wall-clock rate: {pairs_done} pairs in {elapsed}s "
                f"= {1.0 / avg_pair:.2f} pair/s (avg {avg_pair:.2f}s per pair, workers={self.classify_workers})"
            )
        self._progress(f"Done. Results in {self.out_dir}")
        return summary

    # ── per-review processing ─────────────────────────────────────────────

    def _process_review(
        self,
        review: dict,
        feature_catalog: list[dict],
        review_index: int = 1,
        total_reviews: int = 1,
    ) -> dict:
        """Single entry point. Dispatches to serial or parallel helper by classify_workers."""
        review_t0 = time.perf_counter()
        rid = review["review_id"]

        classify_t0 = time.perf_counter()
        per_feature = self._classify_features(review, feature_catalog, review_index, total_reviews)
        classify_seconds = round(time.perf_counter() - classify_t0, 2)

        features_result: dict[str, dict] = {}
        per_feature_seconds: list[float] = []
        classify_errors: list[dict] = []
        self._merge_classify_items(features_result, per_feature, per_feature_seconds, classify_errors)

        validation_seconds_total = 0.0
        master_dynamic_seconds_total = 0.0
        validation_iterations: list[dict] = []
        new_feature_candidates: list[str] = []
        dynamic_features_added: list[str] = []
        dynamic_errors: list[str] = []
        master_received_failure = False

        for iteration in range(1, self.max_validation_iters + 1):
            relevant_bundle = {
                name: data
                for name, data in features_result.items()
                if data.get("is_relevant")
            }
            validation_t0 = time.perf_counter()
            try:
                validation_result = self.validator.validate(review["review_text"], relevant_bundle)
            except Exception as exc:
                validation_result = {
                    "pass": None,
                    "suggest_feature": None,
                    "reason": f"validation error: {exc}",
                    "confidence": 0.0,
                }
            validation_seconds = round(time.perf_counter() - validation_t0, 2)
            validation_seconds_total += validation_seconds
            validation_iteration = {
                "iteration": iteration,
                "pass": validation_result.get("pass"),
                "suggest_feature": validation_result.get("suggest_feature"),
                "reason": validation_result.get("reason", ""),
                "confidence": validation_result.get("confidence", 0.0),
                "elapsed_seconds": validation_seconds,
                "relevant_feature_count": len(relevant_bundle),
            }
            validation_iterations.append(validation_iteration)

            if validation_result.get("pass") is not False:
                break

            master_received_failure = True
            self._progress(f"  validation failed r{review_index}/{total_reviews} id={rid}; asking MasterAgent for one suggested feature")
            master_t0 = time.perf_counter()
            try:
                candidates = self.master.generate_dynamic_features(
                    review,
                    validation_result,
                    feature_catalog,
                )
            except Exception as exc:
                candidates = []
                dynamic_errors.append(str(exc))
            master_dynamic_seconds_total += round(time.perf_counter() - master_t0, 2)
            accepted = self._filter_new_features(candidates, feature_catalog)[:1]
            candidate_names = [str(c.get("name", "")).strip() for c in candidates if str(c.get("name", "")).strip()]
            new_feature_candidates.extend(candidate_names[:1])

            if not accepted:
                break

            names = [str(f.get("name", "")).strip() for f in accepted]
            dynamic_features_added.extend(names)
            feature_catalog.extend(accepted)
            self.master.feature_catalog = feature_catalog
            self._progress(
                f"  MasterAgent added {len(accepted)} global features for id={rid}: {', '.join(names)}"
            )
            dynamic_t0 = time.perf_counter()
            dynamic_items = self._classify_features(review, accepted, review_index, total_reviews)
            classify_seconds += round(time.perf_counter() - dynamic_t0, 2)
            self._merge_classify_items(features_result, dynamic_items, per_feature_seconds, classify_errors)

        review_seconds = round(time.perf_counter() - review_t0, 2)

        relevant = [n for n, v in features_result.items() if v["is_relevant"]]
        positive = [n for n, v in features_result.items() if v["is_relevant"] and v["score"] > 0]
        negative = [n for n, v in features_result.items() if v["is_relevant"] and v["score"] < 0]
        neutral = [n for n, v in features_result.items() if v["is_relevant"] and v["score"] == 0.0]
        last_suggest_feature = next(
            (
                item.get("suggest_feature")
                for item in reversed(validation_iterations)
                if item.get("suggest_feature")
            ),
            None,
        )

        avg_feat = round(sum(per_feature_seconds) / max(len(per_feature_seconds), 1), 3)
        diagnostics = {
            "review_id": rid,
            "features_classified": len(features_result),
            "relevant_features": relevant,
            "positive_features": positive,
            "negative_features": negative,
            "neutral_features": neutral,
            "validation_pass": validation_iterations[-1].get("pass") if validation_iterations else None,
            "validation_reason": validation_iterations[-1].get("reason", "") if validation_iterations else "",
            "validation_confidence": validation_iterations[-1].get("confidence", 0.0) if validation_iterations else 0.0,
            "suggest_feature": last_suggest_feature,
            "new_feature_candidates": _unique_strings(new_feature_candidates),
            "dynamic_features_added": _unique_strings(dynamic_features_added),
            "dynamic_errors": dynamic_errors,
            "validation_iterations_used": len(validation_iterations),
            "validation_iteration_detail": validation_iterations,
            "master_agent_received_validation_failure": master_received_failure,
            "classify_errors": classify_errors,
            "elapsed_seconds": review_seconds,
            "agent_timing": {
                "classify_total": round(classify_seconds, 2),
                "validation_agent": round(validation_seconds_total, 2),
                "master_agent_dynamic": round(master_dynamic_seconds_total, 2),
                "classify_workers": self.classify_workers,
                "features_classified": len(features_result),
                "classify_agent_avg_seconds_per_feature": avg_feat,
                # Note: in parallel mode per-feature seconds do not sum to wall-clock.
                "classify_agent_sum_per_feature_seconds": round(sum(per_feature_seconds), 2),
            },
        }

        self._log("review_processed", {
            "review_id": rid,
            "features_classified": len(features_result),
            "relevant_count": len(relevant),
            "positive_count": len(positive),
            "negative_count": len(negative),
            "neutral_count": len(neutral),
            "error_count": len(classify_errors),
            "classify_workers": self.classify_workers,
            "validation_pass": diagnostics["validation_pass"],
            "validation_iterations_used": diagnostics["validation_iterations_used"],
            "dynamic_features_added": diagnostics["dynamic_features_added"],
            "elapsed_seconds": review_seconds,
        })

        return {
            "review_id": rid,
            "review_text": review["review_text"],
            "rating": review.get("rating"),
            "features": features_result,
            "elapsed_seconds": review_seconds,
            "diagnostics": diagnostics,
        }

    def _classify_features(
        self,
        review: dict,
        features: list[dict],
        review_index: int = 1,
        total_reviews: int = 1,
    ) -> list[dict]:
        if self.classify_workers <= 1:
            return self._classify_features_serial(review, features, review_index, total_reviews)
        return self._classify_features_parallel(review, features, review_index, total_reviews)

    @staticmethod
    def _merge_classify_items(
        features_result: dict[str, dict],
        items: list[dict],
        per_feature_seconds: list[float],
        classify_errors: list[dict],
    ) -> None:
        for item in items:
            fname = item["feature"]
            features_result[fname] = {
                "is_relevant": bool(item["is_relevant"]),
                "score": float(item["score"]),
                "evidence_span": item.get("evidence_span", ""),
                "reason": item.get("reason", ""),
            }
            dt = float(item.get("elapsed_seconds") or 0.0)
            per_feature_seconds.append(dt)
            if item.get("error"):
                classify_errors.append({"feature": fname, "error": item["error"]})

    @staticmethod
    def _filter_new_features(candidates: list[dict], existing_features: list[dict]) -> list[dict]:
        existing = {
            str(f.get("name", "")).strip().lower()
            for f in existing_features
            if str(f.get("name", "")).strip()
        }
        accepted: list[dict] = []
        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue
            name = str(candidate.get("name", "")).strip()
            if not name:
                continue
            key = name.lower()
            if key in existing:
                continue
            existing.add(key)
            accepted.append({
                "name": name,
                "description": str(candidate.get("description", "") or ""),
                "examples": candidate.get("examples", []) if isinstance(candidate.get("examples", []), list) else [],
            })
        return accepted

    def _classify_one_safely(self, review: dict, feature: dict) -> dict:
        """Wrap classify_one with uniform error shape + elapsed_seconds."""
        fname = str(feature.get("name", "")).strip()
        t_feat = time.perf_counter()
        try:
            result = self.classifier.classify_one(review, feature)
            err = None
        except Exception as exc:
            err = str(exc)
            result = {
                "feature": fname,
                "is_relevant": False,
                "score": 0.0,
                "evidence_span": "",
                "reason": f"classify error: {exc}",
            }
        dt = round(time.perf_counter() - t_feat, 2)
        return {
            "feature": fname,
            "is_relevant": bool(result.get("is_relevant", False)),
            "score": float(result.get("score", 0.0)),
            "evidence_span": result.get("evidence_span", ""),
            "reason": result.get("reason", ""),
            "elapsed_seconds": dt,
            "error": err,
        }

    def _classify_features_serial(
        self,
        review: dict,
        features: list[dict],
        review_index: int = 1,
        total_reviews: int = 1,
    ) -> list[dict]:
        """Run feature classify calls sequentially; print progress per feature."""
        rid = review["review_id"]
        total_features = len(features)
        out: list[dict] = []
        for fi, feat in enumerate(features, start=1):
            fname = str(feat.get("name", "")).strip()
            if not fname:
                continue
            item = self._classify_one_safely(review, feat)
            out.append(item)
            tag = "ERR" if item["error"] else (
                f"{item['score']:+.2f}" if item["is_relevant"] else "irrelevant"
            )
            self._progress(
                f"  [serial] r{review_index}/{total_reviews} id={rid} "
                f"f{fi}/{total_features} {fname}: {tag} t={item['elapsed_seconds']}s"
            )
        return out

    def _classify_features_parallel(
        self,
        review: dict,
        features: list[dict],
        review_index: int = 1,
        total_reviews: int = 1,
    ) -> list[dict]:
        """Fan out feature classify calls on a thread pool; return catalog-ordered list."""
        rid = review["review_id"]
        total_features = len(features)
        results_by_name: dict[str, dict] = {}
        # Keep a mapping feature_name -> order so we can restore catalog order.
        order = [str(f.get("name", "")).strip() for f in features]

        workers = min(self.classify_workers, max(total_features, 1))
        self._progress(
            f"  [parallel] r{review_index}/{total_reviews} id={rid} "
            f"launching {total_features} features with {workers} workers"
        )

        done_count = 0
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="classify") as pool:
            future_to_feature = {
                pool.submit(self._classify_one_safely, review, feature): feature
                for feature in features
                if str(feature.get("name", "")).strip()
            }
            for future in as_completed(future_to_feature):
                feature = future_to_feature[future]
                fname = str(feature.get("name", "")).strip()
                try:
                    item = future.result()
                except Exception as exc:  # should rarely trigger; _classify_one_safely catches
                    item = {
                        "feature": fname,
                        "is_relevant": False,
                        "score": 0.0,
                        "evidence_span": "",
                        "reason": f"classify error: {exc}",
                        "elapsed_seconds": 0.0,
                        "error": str(exc),
                    }
                results_by_name[fname] = item
                done_count += 1
                tag = "ERR" if item["error"] else (
                    f"{item['score']:+.2f}" if item["is_relevant"] else "irrelevant"
                )
                self._progress(
                    f"  [par {done_count}/{total_features}] r{review_index}/{total_reviews} id={rid} "
                    f"{fname}: {tag} t={item['elapsed_seconds']}s"
                )

        # Return in catalog order, skipping any names that were blank.
        ordered: list[dict] = []
        for fname in order:
            if fname and fname in results_by_name:
                ordered.append(results_by_name[fname])
        return ordered

    # ── output: single CSV ────────────────────────────────────────────────

    def _export_feature_map(self, records: list[dict], feature_catalog: list[dict]) -> None:
        """CSV: review metadata + per-feature continuous score column (-1..1)."""
        all_names: list[str] = []
        seen: set[str] = set()
        for f in feature_catalog:
            name = str(f.get("name", "")).strip()
            if name and name not in seen:
                seen.add(name)
                all_names.append(name)
        # Also include any extra feature names that showed up in records (defensive).
        for r in records:
            for raw_name in r["features"]:
                name = str(raw_name).strip()
                if name and name not in seen:
                    seen.add(name)
                    all_names.append(name)

        meta_cols = ["review_id", "rating", "review_preview"]
        fieldnames = meta_cols + all_names

        rows = []
        for r in records:
            row: dict = {
                "review_id": r["review_id"],
                "rating": r.get("rating", ""),
                "review_preview": r["review_text"][:80].replace("\n", " "),
            }
            for name in all_names:
                feat = r["features"].get(name, {})
                score = float(feat.get("score", 0.0))
                # stored rounded to keep CSV clean but still continuous
                row[name] = round(score, 3)
            rows.append(row)

        self._save_csv("feature_map.csv", rows, fieldnames)

    # ── output: log + report ──────────────────────────────────────────────

    def _build_run_log(self, catalog: list[dict]) -> dict:
        return {
            "metadata": {
                "input_csv": self._csv_path,
                "max_reviews": self.max_reviews,
                "sample_size_init": self.sample_size_init,
                "initial_feature_catalog_size": self.initial_feature_catalog_size,
                "final_feature_catalog_size": len(catalog),
                "classification_temperature": self.classification_temperature,
                "dynamic_temperature": self.dynamic_temperature,
                "validation_temperature": self.validation_temperature,
                "classify_workers": self.classify_workers,
                "max_validation_iters": self.max_validation_iters,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            },
            "initial_catalog_size": self.initial_feature_catalog_size,
            "initial_catalog": self.initial_feature_catalog,
            "final_catalog": catalog,
            "events": self._log_events,
        }

    def _write_report(self, catalog: list[dict], records: list[dict], summary: dict) -> None:
        lines: list[str] = []
        lines.append("# EchoInsight V2 Report")
        lines.append("")
        lines.append(f"- **Reviews processed:** {summary['total_reviews']}")
        lines.append(f"- **Initial catalog size:** {summary['initial_catalog_size']}")
        lines.append(f"- **Final catalog size:** {summary.get('final_catalog_size', summary['initial_catalog_size'])}")
        lines.append(f"- **Global dynamic features added:** {summary.get('dynamic_features_added_count', 0)}")
        lines.append(f"- **Avg relevant features per review:** {summary['avg_relevant_features_per_review']}")
        lines.append(f"- **Positive assignments:** {summary['positive_assignment_count']}")
        lines.append(f"- **Negative assignments:** {summary['negative_assignment_count']}")
        lines.append(f"- **Neutral assignments:** {summary['neutral_assignment_count']}")
        lines.append(f"- **Avg classify time per review:** {summary['avg_classify_seconds_per_review']}s")
        lines.append(f"- **Avg classify time per feature:** {summary['avg_classify_seconds_per_feature']}s")
        lines.append(f"- **Classify workers (local parallelism):** {summary.get('classify_workers', 1)}")
        lines.append(f"- **Avg features per review:** {summary.get('avg_features_per_review', 0)}")
        lines.append(f"- **Validation pass rate:** {summary.get('validation_pass_rate', 0)}")
        if summary.get("classify_error_count"):
            lines.append(f"- **Classify errors (non-fatal):** {summary['classify_error_count']}")
        lines.append(f"- **Elapsed:** {summary.get('elapsed_seconds', '?')}s")
        lines.append("")

        lines.append("## Validation Summary")
        lines.append("")
        lines.append("- Validation enabled: true")
        lines.append("- Validation mode: relevant-feature coverage only")
        lines.append(f"- Pass rate: {summary.get('validation_pass_rate', 0)}")
        lines.append(f"- Failed reviews: {summary.get('validation_fail_count', 0)}")
        lines.append(f"- Avg validation iterations: {summary.get('avg_validation_iterations', 0)}")
        lines.append(f"- Avg validation seconds per review: {summary.get('avg_validation_seconds_per_review', 0)}s")
        common_suggested = summary.get("common_suggested_feature_candidates", [])
        if common_suggested:
            lines.append("- Common suggested feature candidates: " + ", ".join(f"`{x['name']}` ({x['count']})" for x in common_suggested[:10]))
        else:
            lines.append("- Common suggested feature candidates: (none)")
        lines.append("")

        # Top positive / negative / most relevant features
        pos_totals: dict[str, float] = {}
        neg_totals: dict[str, float] = {}
        rel_counts: dict[str, int] = {}
        for r in records:
            for name, data in r["features"].items():
                if not data["is_relevant"]:
                    continue
                rel_counts[name] = rel_counts.get(name, 0) + 1
                s = float(data.get("score", 0.0))
                if s > 0:
                    pos_totals[name] = pos_totals.get(name, 0.0) + s
                elif s < 0:
                    neg_totals[name] = neg_totals.get(name, 0.0) + s

        def _top(d: dict, reverse: bool, n: int = 10) -> list[tuple[str, float]]:
            return sorted(d.items(), key=lambda kv: kv[1], reverse=reverse)[:n]

        lines.append("## Top Positive Features")
        lines.append("")
        for name, score in _top(pos_totals, reverse=True):
            lines.append(f"- `{name}`: +{score:.2f} total")
        if not pos_totals:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Top Negative Features")
        lines.append("")
        for name, score in _top(neg_totals, reverse=False):
            lines.append(f"- `{name}`: {score:.2f} total")
        if not neg_totals:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Most Frequently Relevant Features")
        lines.append("")
        for name, count in sorted(rel_counts.items(), key=lambda kv: -kv[1])[:10]:
            lines.append(f"- `{name}`: relevant in {count} reviews")
        if not rel_counts:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Final Feature Catalog")
        lines.append("")
        for f in catalog:
            lines.append(f"### `{f['name']}`")
            lines.append(f"> {f.get('description', '')}")
            examples = f.get("examples", [])
            if examples:
                lines.append("")
                lines.append("Real quotes from sampled reviews:")
                for ex in examples:
                    lines.append(f'- "{ex}"')
            lines.append("")

        lines.append("## Per-Review Summary")
        lines.append("")
        for r in records:
            diag = r["diagnostics"]
            lines.append(f"### Review {r['review_id']} (rating: {r.get('rating', '?')})")
            lines.append(f"- **Text:** {r['review_text'][:120]}{'...' if len(r['review_text']) > 120 else ''}")
            lines.append(
                f"- **Relevant:** {len(diag['relevant_features'])} "
                f"(pos={len(diag['positive_features'])}, "
                f"neg={len(diag['negative_features'])}, "
                f"neu={len(diag['neutral_features'])})"
            )
            lines.append(
                f"- **Validation:** pass={diag.get('validation_pass')} "
                f"iterations={diag.get('validation_iterations_used', 0)} "
                f"confidence={float(diag.get('validation_confidence') or 0.0):.2f}"
            )
            suggested = _feature_name(diag.get("suggest_feature"))
            added = diag.get("dynamic_features_added", []) or []
            if suggested:
                lines.append(f"- **Suggested feature feedback:** `{suggested}`")
            if added:
                lines.append("- **Dynamic features added:** " + ", ".join(f"`{name}`" for name in added))
            # top 3 strongest (by |score|)
            scored = [
                (n, d) for n, d in r["features"].items() if d["is_relevant"]
            ]
            scored.sort(key=lambda kv: -abs(float(kv[1].get("score", 0.0))))
            if scored:
                lines.append("- **Top scored:**")
                for name, data in scored[:3]:
                    lines.append(
                        f"  - `{name}` score={data.get('score', 0.0):+.2f} "
                        f"| {data.get('evidence_span', '')[:60]}"
                    )
            lines.append("")

        path = self.out_dir / "report.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        self._progress(f"Saved {path}")

    # ── helpers ───────────────────────────────────────────────────────────

    def _build_summary(self, catalog: list[dict], records: list[dict], elapsed: float) -> dict:
        total = len(records)
        relevant_counts: list[int] = []
        feature_counts: list[int] = []
        pos_count = 0
        neg_count = 0
        neu_count = 0
        err_count = 0
        validation_values: list[bool] = []
        validation_iterations: list[int] = []
        validation_seconds: list[float] = []
        suggested_counts: dict[str, int] = {}
        classify_totals: list[float] = []
        feature_seconds: list[float] = []
        for r in records:
            diag = r["diagnostics"]
            relevant_counts.append(len(diag["relevant_features"]))
            feature_counts.append(int(diag.get("features_classified", 0)))
            pos_count += len(diag["positive_features"])
            neg_count += len(diag["negative_features"])
            neu_count += len(diag["neutral_features"])
            err_count += len(diag.get("classify_errors", []) or [])
            if diag.get("validation_pass") is not None:
                validation_values.append(bool(diag.get("validation_pass")))
            validation_iterations.append(int(diag.get("validation_iterations_used", 0) or 0))
            validation_seconds.append(float(diag.get("agent_timing", {}).get("validation_agent", 0.0) or 0.0))
            name = _feature_name(diag.get("suggest_feature"))
            if name:
                suggested_counts[name] = suggested_counts.get(name, 0) + 1
            classify_totals.append(float(r.get("elapsed_seconds") or 0.0))
            per_feat = diag.get("agent_timing", {}).get("classify_agent_avg_seconds_per_feature", 0.0)
            if per_feat:
                feature_seconds.append(float(per_feat))

        avg_relevant = round(sum(relevant_counts) / max(total, 1), 2)
        avg_features = round(sum(feature_counts) / max(total, 1), 2)
        avg_classify = round(sum(classify_totals) / max(total, 1), 2)
        avg_per_feature = round(sum(feature_seconds) / max(len(feature_seconds), 1), 3)

        dynamic_candidates: set[str] = set()
        dynamic_added: set[str] = set()
        for r in records:
            for c in r["diagnostics"].get("new_feature_candidates", []) or []:
                dynamic_candidates.add(c)
            for c in r["diagnostics"].get("dynamic_features_added", []) or []:
                dynamic_added.add(c)

        pass_count = sum(1 for value in validation_values if value)
        fail_count = sum(1 for value in validation_values if not value)
        pass_rate = round(pass_count / max(len(validation_values), 1), 3)
        common_suggested = [
            {"name": name, "count": count}
            for name, count in sorted(suggested_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
        ]

        return {
            "total_reviews": total,
            "initial_catalog_size": self.initial_feature_catalog_size or len(catalog),
            "final_catalog_size": len(catalog),
            "dynamic_new_feature_candidates_count": len(dynamic_candidates),
            "dynamic_new_feature_candidates": sorted(dynamic_candidates),
            "dynamic_features_added_count": len(dynamic_added),
            "dynamic_features_added": sorted(dynamic_added),
            "validation_enabled": True,
            "validation_pass_rate": pass_rate,
            "validation_pass_count": pass_count,
            "validation_fail_count": fail_count,
            "avg_validation_iterations": round(sum(validation_iterations) / max(total, 1), 2),
            "avg_validation_seconds_per_review": round(sum(validation_seconds) / max(total, 1), 2),
            "common_suggested_feature_candidates": common_suggested,
            "avg_relevant_features_per_review": avg_relevant,
            "avg_features_per_review": avg_features,
            "positive_assignment_count": pos_count,
            "negative_assignment_count": neg_count,
            "neutral_assignment_count": neu_count,
            "classify_error_count": err_count,
            "avg_classify_seconds_per_review": avg_classify,
            "avg_classify_seconds_per_feature": avg_per_feature,
            "classify_workers": self.classify_workers,
            "elapsed_seconds": elapsed,
        }

    def _log(self, event_type: str, data: dict) -> None:
        self._log_events.append({"event_type": event_type, **data})

    def _progress(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[V2 {timestamp}] {message}", flush=True)

    def _save_json(self, filename: str, data: Any) -> None:
        path = self.out_dir / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self._progress(f"Saved {path}")

    def _save_csv(self, filename: str, rows: list[dict], fieldnames: list[str]) -> None:
        path = self.out_dir / filename
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        self._progress(f"Saved {path}")


def _fmt_eta(seconds: float) -> str:
    if seconds is None or seconds <= 0 or seconds != seconds:  # 0 / NaN guard
        return "?"
    return str(timedelta(seconds=int(seconds)))


def _unique_strings(values: list[object]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _feature_name(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    return ""
