"""EchoInsightV2Pipeline: orchestrates the full V2 workflow."""

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
from .validation_agent import ValidationAgent
from .feature_fusion import FeatureFusion

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
            text_col = next((c for c in row if "text" in c.lower()), None)
            rating_col = next((c for c in row if "rating" in c.lower()), None)
            if not text_col:
                continue
            rows.append({
                "review_id": str(i),
                "review_text": row[text_col].strip(),
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
        max_dynamic_iterations: int = 3,
        classification_temperature: float = 0.1,
        validation_temperature: float = 0.0,
        dynamic_temperature: float = 0.2,
        min_feature_score_to_keep: float = 0.5,
        csv_path: str | Path = "",
        model_alias: str | None = None,
        registry_path: str | Path | None = None,
    ):
        profile = load_model_profile(registry_path, model_alias)
        active_model = profile.get("model") or "Qwen/Qwen3.5-35B-A3B"
        active_base_url = profile.get("base_url")  # None → qwen_api reads from info.md
        print(f"[V2] Model profile: {model_alias or 'default'} → {active_model}")

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
        self.fusion = FeatureFusion(min_score_to_keep=min_feature_score_to_keep)

        self.sample_size_init = sample_size_init
        self.max_reviews = max_reviews
        self.max_features = max_features
        self.max_dynamic_iterations = max_dynamic_iterations
        self.min_feature_score_to_keep = min_feature_score_to_keep
        self.classification_temperature = classification_temperature
        self.validation_temperature = validation_temperature
        self.dynamic_temperature = dynamic_temperature
        self._csv_path = str(csv_path)

        self.out_dir = Path(output_root) / run_name
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self._log_events: list[dict] = []

    # ── public entry point ────────────────────────────────────────────────

    def run(self, csv_path: str | Path) -> dict:
        self._csv_path = str(csv_path)
        t0 = time.time()

        print(f"[V2] Loading reviews from {csv_path}")
        reviews = _load_csv(csv_path)
        if not reviews:
            raise ValueError(f"No reviews loaded from {csv_path}")

        self._log("run_start", {
            "input_csv": str(csv_path),
            "total_reviews_in_file": len(reviews),
            "max_reviews": self.max_reviews,
            "sample_size_init": self.sample_size_init,
            "max_dynamic_iterations": self.max_dynamic_iterations,
            "min_feature_score_to_keep": self.min_feature_score_to_keep,
        })

        print(f"[V2] Loaded {len(reviews)} reviews. Running init with sample_size={self.sample_size_init}")
        sampled = self.master.sample_reviews(reviews, self.sample_size_init)
        self._log("init_sample_selected", {"sampled_ids": [r["review_id"] for r in sampled]})

        raw_features = self.master.extract_initial_features(sampled)
        deduped = self.master.dedupe_features(raw_features)
        feature_catalog = deduped[: self.max_features]
        if len(deduped) > self.max_features:
            print(f"[V2] Feature catalog capped at {self.max_features} (extracted {len(deduped)})")
        self.master.feature_catalog = feature_catalog
        self._log("init_catalog_built", {
            "feature_count": len(feature_catalog),
            "features": [f["name"] for f in feature_catalog],
        })
        print(f"[V2] Initial feature catalog: {len(feature_catalog)} features")
        self._save_json("initialized_feature_corpus.json", feature_catalog)

        batch = reviews[: self.max_reviews]
        review_records: list[dict] = []

        diag_path = self.out_dir / "review_level_diagnostics.jsonl"
        diag_path.write_text("", encoding="utf-8")  # truncate / create

        for review in batch:
            rid = review["review_id"]
            print(f"[V2] Processing review {rid}: {review['review_text'][:60]}...")
            record = self._process_review(review)
            review_records.append(record)
            active = sum(1 for v in record["accepted_features"].values() if v["has_feature"])
            print(f"[V2]   -> pass={record['validation_pass']} | active={active} features | iters={record['iterations_used']}")

            # flush this record immediately
            with diag_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            # refresh feature_map and summary after every record
            self._export_feature_map(review_records)
            self._save_json("feature_scores_detail.json", [
                {"review_id": r["review_id"], "features": r["accepted_features"]}
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
        print(f"[V2] Saved {diag_path.name} ({len(review_records)} records)")

        print(f"[V2] Done. Results in {self.out_dir}")
        return summary

    # ── per-review processing ─────────────────────────────────────────────

    def _process_review(self, review: dict) -> dict:
        payload = self.master.route_review(review)
        all_features = list(self.master.feature_catalog)

        accepted: dict = {}
        dynamic_added: list[str] = []
        iterations_used = 0
        validation_pass = False
        iter_log: list[dict] = []

        for iteration in range(1 + self.max_dynamic_iterations):
            iterations_used = iteration + 1

            payload["default_fixed_features"] = [
                {"name": f["name"], "description": f.get("description", "")}
                for f in all_features
            ]
            outputs = self.classifier.classify(payload)
            accepted = self.fusion.fuse(accepted, outputs)

            positive_bundle = self.fusion.filter_positive(accepted)
            val_result = self.validator.validate(review["review_text"], positive_bundle)

            iter_entry = {
                "iteration": iteration + 1,
                "features_classified": len(outputs),
                "positive_features": list(positive_bundle.keys()),
                "validation_pass": val_result["pass"],
                "validation_reason": val_result.get("reason", ""),
                "validation_confidence": val_result.get("confidence", 1.0),
                "missing_features": val_result.get("missing_features", []),
            }
            iter_log.append(iter_entry)

            if val_result["pass"]:
                validation_pass = True
                break

            if iteration >= self.max_dynamic_iterations:
                break

            new_features = self.master.generate_dynamic_features(review, val_result, all_features)
            for nf in new_features:
                if nf.get("name") and nf["name"] not in {f["name"] for f in all_features}:
                    all_features.append(nf)
                    dynamic_added.append(nf["name"])
            iter_entry["dynamic_features_generated"] = [nf.get("name") for nf in new_features]

        self._log("review_processed", {
            "review_id": review["review_id"],
            "iterations_used": iterations_used,
            "validation_pass": validation_pass,
            "dynamic_features_added": dynamic_added,
            "iteration_detail": iter_log,
        })

        return {
            "review_id": review["review_id"],
            "review_text": review["review_text"],
            "rating": review.get("rating"),
            "accepted_features": self.fusion.filter_positive(accepted),
            "validation_pass": validation_pass,
            "dynamic_features_added": dynamic_added,
            "iterations_used": iterations_used,
        }

    # ── output: single CSV ────────────────────────────────────────────────

    def _export_feature_map(self, records: list[dict]) -> None:
        """Single CSV: review metadata + binary feature columns."""
        all_names: list[str] = []
        seen: set[str] = set()
        for r in records:
            for name in r["accepted_features"]:
                if name not in seen:
                    seen.add(name)
                    all_names.append(name)

        meta_cols = ["review_id", "rating", "validation_pass", "iterations_used",
                     "dynamic_features_added", "review_preview"]
        fieldnames = meta_cols + all_names

        rows = []
        for r in records:
            row: dict = {
                "review_id": r["review_id"],
                "rating": r.get("rating", ""),
                "validation_pass": int(r["validation_pass"]),
                "iterations_used": r["iterations_used"],
                "dynamic_features_added": "|".join(r["dynamic_features_added"]),
                "review_preview": r["review_text"][:80].replace("\n", " "),
            }
            for name in all_names:
                feat = r["accepted_features"].get(name, {})
                row[name] = int(feat.get("has_feature", False))
            rows.append(row)

        self._save_csv("feature_map.csv", rows, fieldnames)

    # ── output: log + report ──────────────────────────────────────────────

    def _build_run_log(self, catalog: list[dict]) -> dict:
        return {
            "metadata": {
                "input_csv": self._csv_path,
                "max_reviews": self.max_reviews,
                "sample_size_init": self.sample_size_init,
                "max_dynamic_iterations": self.max_dynamic_iterations,
                "min_feature_score_to_keep": self.min_feature_score_to_keep,
                "classification_temperature": self.classification_temperature,
                "validation_temperature": self.validation_temperature,
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
        lines.append(f"- **Validation pass rate:** {summary['validation_pass_rate']:.1%}")
        lines.append(f"- **Avg iterations per review:** {summary['avg_iterations']}")
        lines.append(f"- **Initial catalog size:** {summary['initial_catalog_size']}")
        lines.append(f"- **Elapsed:** {summary.get('elapsed_seconds', '?')}s")
        lines.append("")

        lines.append("## Initial Feature Catalog")
        lines.append("")
        lines.append("Each feature includes verbatim quotes from sampled reviews as evidence.")
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

        dynamic_all: list[str] = sorted({
            name for r in records for name in r["dynamic_features_added"]
        })
        if dynamic_all:
            lines.append("## Dynamically Discovered Features")
            lines.append("")
            for name in dynamic_all:
                lines.append(f"- {name}")
            lines.append("")

        lines.append("## Per-Review Summary")
        lines.append("")
        for r in records:
            active_feats = [k for k, v in r["accepted_features"].items() if v["has_feature"]]
            lines.append(f"### Review {r['review_id']} (rating: {r.get('rating', '?')})")
            lines.append(f"- **Text:** {r['review_text'][:120]}{'...' if len(r['review_text']) > 120 else ''}")
            lines.append(f"- **Validation pass:** {r['validation_pass']}")
            lines.append(f"- **Iterations used:** {r['iterations_used']}")
            if r["dynamic_features_added"]:
                lines.append(f"- **Dynamic features added:** {', '.join(r['dynamic_features_added'])}")
            lines.append(f"- **Active features ({len(active_feats)}):** {', '.join(active_feats) if active_feats else 'none'}")
            # top scored
            top = sorted(r["accepted_features"].items(), key=lambda x: -x[1].get("feature_score", 0))[:3]
            if top:
                lines.append("- **Top scored:**")
                for name, data in top:
                    lines.append(f"  - `{name}` score={data.get('feature_score', 0):.2f} | {data.get('evidence_span', '')[:60]}")
            lines.append("")

        path = self.out_dir / "report.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"[V2] Saved {path}")

    # ── helpers ───────────────────────────────────────────────────────────

    def _build_summary(self, catalog: list[dict], records: list[dict], elapsed: float) -> dict:
        total = len(records)
        passed = sum(1 for r in records if r["validation_pass"])
        avg_iters = sum(r["iterations_used"] for r in records) / max(total, 1)
        dynamic_names: set[str] = set()
        for r in records:
            dynamic_names.update(r["dynamic_features_added"])
        return {
            "total_reviews": total,
            "validation_pass_rate": round(passed / max(total, 1), 3),
            "avg_iterations": round(avg_iters, 2),
            "initial_catalog_size": len(catalog),
            "dynamic_features_discovered": sorted(dynamic_names),
            "elapsed_seconds": elapsed,
        }

    def _log(self, event_type: str, data: dict) -> None:
        self._log_events.append({"event_type": event_type, **data})

    def _save_json(self, filename: str, data: Any) -> None:
        path = self.out_dir / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[V2] Saved {path}")

    def _save_csv(self, filename: str, rows: list[dict], fieldnames: list[str]) -> None:
        path = self.out_dir / filename
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"[V2] Saved {path}")
