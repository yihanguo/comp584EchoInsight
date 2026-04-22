"""EchoInsightV2Pipeline: per-feature classify flow (phase 1)."""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .qwen_api import QwenClient
from .master_agent import MasterAgent
from .classify_agent import ClassifyAgent

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
        csv_path: str | Path = "",
        model_alias: str | None = None,
        registry_path: str | Path | None = None,
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

        self.sample_size_init = sample_size_init
        self.max_reviews = max_reviews
        self.max_features = max_features
        self.classification_temperature = classification_temperature
        self.dynamic_temperature = dynamic_temperature
        self._csv_path = str(csv_path)

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
        })

        self._progress(f"Loaded {len(reviews)} reviews. MasterAgent init sample_size={self.sample_size_init}")
        sampled = self.master.sample_reviews(reviews, self.sample_size_init)
        self._log("init_sample_selected", {"sampled_ids": [r["review_id"] for r in sampled]})

        init_t0 = time.perf_counter()
        raw_features = self.master.extract_initial_features(sampled)
        init_seconds = round(time.perf_counter() - init_t0, 2)
        deduped = self.master.dedupe_features(raw_features)
        feature_catalog = deduped[: self.max_features]
        if len(deduped) > self.max_features:
            self._progress(f"Feature catalog capped at {self.max_features} (extracted {len(deduped)})")
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

        diag_path = self.out_dir / "review_level_diagnostics.jsonl"
        diag_path.write_text("", encoding="utf-8")  # truncate / create

        for index, review in enumerate(batch, start=1):
            rid = review["review_id"]
            self._progress(f"Review {index}/{total_batch} id={rid} start: {review['review_text'][:60]}...")
            record = self._process_review(review, feature_catalog)
            review_records.append(record)
            diag = record["diagnostics"]
            self._progress(
                f"Review {index}/{total_batch} id={rid} done in {record['elapsed_seconds']}s "
                f"| relevant={diag['relevant_features']} "
                f"| pos={diag['positive_features']} neg={diag['negative_features']} neu={diag['neutral_features']}"
            )

            # flush diagnostics for this review immediately
            with diag_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(diag, ensure_ascii=False) + "\n")

            # refresh outputs after every record
            self._export_feature_map(review_records, feature_catalog)
            self._save_json("feature_scores_detail.json", [
                {"review_id": r["review_id"], "features": r["features"]}
                for r in review_records
            ])
            elapsed_so_far = round(time.time() - t0, 1)
            self._save_json("v2_summary.json", self._build_summary(feature_catalog, review_records, elapsed_so_far))

        elapsed = round(time.time() - t0, 1)
        self._log("run_complete", {"elapsed_seconds": elapsed, "reviews_processed": len(review_records)})

        self._save_json("v2_run_log.json", self._build_run_log(feature_catalog))
        summary = self._build_summary(feature_catalog, review_records, elapsed)
        self._save_json("v2_summary.json", summary)
        self._write_report(feature_catalog, review_records, summary)
        self._progress(f"Saved {diag_path.name} ({len(review_records)} records)")

        self._progress(f"Done. Results in {self.out_dir}")
        return summary

    # ── per-review processing ─────────────────────────────────────────────

    def _process_review(self, review: dict, feature_catalog: list[dict]) -> dict:
        """Loop over every feature in the catalog; one classify_one() call per pair."""
        review_t0 = time.perf_counter()
        rid = review["review_id"]
        features_result: dict[str, dict] = {}
        per_feature_seconds: list[float] = []

        for feat in feature_catalog:
            fname = str(feat.get("name", "")).strip()
            if not fname:
                continue
            t_feat = time.perf_counter()
            try:
                result = self.classifier.classify_one(review, feat)
            except Exception as exc:
                self._progress(f"  Review {rid} feature={fname} ERROR: {exc}")
                result = {
                    "feature": fname,
                    "is_relevant": False,
                    "score": 0.0,
                    "evidence_span": "",
                    "reason": f"error: {exc}",
                }
            dt = round(time.perf_counter() - t_feat, 2)
            per_feature_seconds.append(dt)
            # Store under the catalog feature name (authoritative), not whatever the model echoed.
            features_result[fname] = {
                "is_relevant": bool(result.get("is_relevant", False)),
                "score": float(result.get("score", 0.0)),
                "evidence_span": result.get("evidence_span", ""),
                "reason": result.get("reason", ""),
            }

        review_seconds = round(time.perf_counter() - review_t0, 2)

        relevant = [n for n, v in features_result.items() if v["is_relevant"]]
        positive = [n for n, v in features_result.items() if v["is_relevant"] and v["score"] > 0]
        negative = [n for n, v in features_result.items() if v["is_relevant"] and v["score"] < 0]
        neutral = [n for n, v in features_result.items() if v["is_relevant"] and v["score"] == 0.0]

        avg_feat = round(sum(per_feature_seconds) / max(len(per_feature_seconds), 1), 3)
        diagnostics = {
            "review_id": rid,
            "features_classified": len(features_result),
            "relevant_features": relevant,
            "positive_features": positive,
            "negative_features": negative,
            "neutral_features": neutral,
            "new_feature_candidates": [],  # phase 1: discovery deferred
            "elapsed_seconds": review_seconds,
            "agent_timing": {
                "classify_agent_total_seconds": round(sum(per_feature_seconds), 2),
                "classify_agent_avg_seconds_per_feature": avg_feat,
            },
        }

        self._log("review_processed", {
            "review_id": rid,
            "features_classified": len(features_result),
            "relevant_count": len(relevant),
            "positive_count": len(positive),
            "negative_count": len(negative),
            "neutral_count": len(neutral),
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
                "classification_temperature": self.classification_temperature,
                "dynamic_temperature": self.dynamic_temperature,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            },
            "initial_catalog": catalog,
            "events": self._log_events,
        }

    def _write_report(self, catalog: list[dict], records: list[dict], summary: dict) -> None:
        lines: list[str] = []
        lines.append("# EchoInsight V2 Report")
        lines.append("")
        lines.append(f"- **Reviews processed:** {summary['total_reviews']}")
        lines.append(f"- **Initial catalog size:** {summary['initial_catalog_size']}")
        lines.append(f"- **Avg relevant features per review:** {summary['avg_relevant_features_per_review']}")
        lines.append(f"- **Positive assignments:** {summary['positive_assignment_count']}")
        lines.append(f"- **Negative assignments:** {summary['negative_assignment_count']}")
        lines.append(f"- **Neutral assignments:** {summary['neutral_assignment_count']}")
        lines.append(f"- **Avg classify time per review:** {summary['avg_classify_seconds_per_review']}s")
        lines.append(f"- **Avg classify time per feature:** {summary['avg_classify_seconds_per_feature']}s")
        lines.append(f"- **Elapsed:** {summary.get('elapsed_seconds', '?')}s")
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

        lines.append("## Initial Feature Catalog")
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
        pos_count = 0
        neg_count = 0
        neu_count = 0
        classify_totals: list[float] = []
        feature_seconds: list[float] = []
        for r in records:
            diag = r["diagnostics"]
            relevant_counts.append(len(diag["relevant_features"]))
            pos_count += len(diag["positive_features"])
            neg_count += len(diag["negative_features"])
            neu_count += len(diag["neutral_features"])
            classify_totals.append(float(r.get("elapsed_seconds") or 0.0))
            per_feat = diag.get("agent_timing", {}).get("classify_agent_avg_seconds_per_feature", 0.0)
            if per_feat:
                feature_seconds.append(float(per_feat))

        avg_relevant = round(sum(relevant_counts) / max(total, 1), 2)
        avg_classify = round(sum(classify_totals) / max(total, 1), 2)
        avg_per_feature = round(sum(feature_seconds) / max(len(feature_seconds), 1), 3)

        dynamic_candidates: set[str] = set()
        for r in records:
            for c in r["diagnostics"].get("new_feature_candidates", []) or []:
                dynamic_candidates.add(c)

        return {
            "total_reviews": total,
            "initial_catalog_size": len(catalog),
            "dynamic_new_feature_candidates_count": len(dynamic_candidates),
            "dynamic_new_feature_candidates": sorted(dynamic_candidates),
            "avg_relevant_features_per_review": avg_relevant,
            "positive_assignment_count": pos_count,
            "negative_assignment_count": neg_count,
            "neutral_assignment_count": neu_count,
            "avg_classify_seconds_per_review": avg_classify,
            "avg_classify_seconds_per_feature": avg_per_feature,
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
