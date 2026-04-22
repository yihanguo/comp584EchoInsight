"""Feature-level stats for an EchoInsight V2 results folder (continuous -1..1 scores)."""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path


META_COLUMNS = {
    "review_id",
    "rating",
    "review_preview",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize EchoInsight V2 result features.")
    parser.add_argument(
        "--results-dir",
        required=True,
        help="Run output directory, e.g. results_v2/ipad_glm_20.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Number of top features to include in the optional plot.",
    )
    return parser.parse_args()


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_diagnostics(results_dir: Path) -> list[dict]:
    diag_path = results_dir / "review_level_diagnostics.jsonl"
    if not diag_path.exists():
        return []

    records = []
    for line in diag_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def load_new_feature_counts(diagnostics: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in diagnostics:
        for name in record.get("new_feature_candidates", []) or []:
            counts[name] = counts.get(name, 0) + 1
    return counts


def load_feature_map(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing feature map: {path}")
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        feature_names = [name for name in (reader.fieldnames or []) if name not in META_COLUMNS]
    return feature_names, rows


def is_valid_feature_name(name: object) -> bool:
    text = str(name).strip()
    if not text:
        return False
    return any(char.isalpha() for char in text)


def _parse_score(cell: object) -> float:
    text = str(cell).strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def svg_text(text: object) -> str:
    return html.escape(str(text), quote=True)


def write_svg(path: Path, content: str, width: int, height: int) -> None:
    path.write_text(
        "\n".join([
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<style>'
            '.title{font:700 18px Arial, sans-serif;fill:#1f2933}'
            '.subtitle{font:12px Arial, sans-serif;fill:#52616b}'
            '.axis{font:11px Arial, sans-serif;fill:#52616b}'
            '.label{font:12px Arial, sans-serif;fill:#1f2933}'
            '.small{font:10px Arial, sans-serif;fill:#52616b}'
            '.grid{stroke:#e5e7eb;stroke-width:1}'
            '.rule{stroke:#9aa5b1;stroke-width:1}'
            '</style>',
            '<rect width="100%" height="100%" fill="#ffffff"/>',
            content,
            "</svg>",
        ]),
        encoding="utf-8",
    )


def write_top_feature_svg(results_dir: Path, stats_rows: list[dict], top_n: int) -> str | None:
    top_rows = stats_rows[:top_n]
    if not top_rows:
        return None

    width = 1100
    row_h = 28
    top = 84
    left = 260
    right = 70
    chart_w = width - left - right
    height = top + row_h * len(top_rows) + 58
    max_value = max(int(row["relevant_count"]) for row in top_rows) or 1
    parts = [
        '<text x="40" y="34" class="title">Most Relevant Features</text>',
        f'<text x="40" y="56" class="subtitle">Top {len(top_rows)} features by number of reviews that discuss them.</text>',
    ]
    for tick in range(0, 6):
        x = left + chart_w * tick / 5
        value = round(max_value * tick / 5)
        parts.append(f'<line x1="{x:.1f}" y1="{top - 12}" x2="{x:.1f}" y2="{height - 46}" class="grid"/>')
        parts.append(f'<text x="{x:.1f}" y="{height - 24}" text-anchor="middle" class="axis">{value}</text>')
    parts.append(f'<line x1="{left}" y1="{height - 46}" x2="{left + chart_w}" y2="{height - 46}" class="rule"/>')

    for idx, row in enumerate(top_rows):
        y = top + idx * row_h
        relevant = int(row["relevant_count"])
        bar_w = chart_w * relevant / max_value
        avg_score = float(row["avg_score_when_relevant"])
        color = "#6f8f2f" if avg_score > 0 else ("#c24949" if avg_score < 0 else "#7b8794")
        parts.append(f'<text x="{left - 14}" y="{y + 16}" text-anchor="end" class="label">{svg_text(row["feature"])}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_w:.1f}" height="18" rx="2" fill="{color}"/>')
        parts.append(
            f'<text x="{left + bar_w + 8:.1f}" y="{y + 14}" class="small">'
            f'{relevant} reviews, avg score {avg_score:+.2f}</text>'
        )
    filename = "feature_relevance_top.svg"
    write_svg(results_dir / filename, "\n".join(parts), width, height)
    return filename


def timing_summary(records: list[dict]) -> list[dict]:
    classify_totals: list[float] = []
    per_feature: list[float] = []
    review_totals: list[float] = []
    for record in records:
        if "elapsed_seconds" in record:
            review_totals.append(float(record.get("elapsed_seconds") or 0.0))
        timing = record.get("agent_timing", {}) or {}
        t_total = timing.get("classify_agent_total_seconds")
        if t_total is not None:
            classify_totals.append(float(t_total))
        t_avg = timing.get("classify_agent_avg_seconds_per_feature")
        if t_avg is not None:
            per_feature.append(float(t_avg))

    def _row(agent: str, values: list[float]) -> dict:
        if not values:
            return {"agent": agent, "calls": 0, "avg_seconds": 0.0, "total_seconds": 0.0, "max_seconds": 0.0}
        return {
            "agent": agent,
            "calls": len(values),
            "avg_seconds": round(sum(values) / len(values), 3),
            "total_seconds": round(sum(values), 2),
            "max_seconds": round(max(values), 2),
        }

    return [
        _row("Review total", review_totals),
        _row("ClassifyAgent total per review", classify_totals),
        _row("ClassifyAgent per feature", per_feature),
    ]


def main() -> int:
    args = parse_args()
    results_dir = Path(args.results_dir).expanduser().resolve()
    feature_map_path = results_dir / "feature_map.csv"

    feature_names, rows = load_feature_map(feature_map_path)
    total_reviews = len(rows)
    run_log = read_json(results_dir / "v2_run_log.json", {})
    initial_catalog = run_log.get("initial_catalog", [])
    initial_names = {
        str(item.get("name")).strip()
        for item in initial_catalog
        if is_valid_feature_name(item.get("name"))
    }
    diagnostics = load_diagnostics(results_dir)
    new_feature_counts = load_new_feature_counts(diagnostics)

    # per-feature relevance stats from diagnostics
    relevant_counts: dict[str, int] = {}
    positive_counts: dict[str, int] = {}
    negative_counts: dict[str, int] = {}
    neutral_counts: dict[str, int] = {}
    for record in diagnostics:
        for name in record.get("relevant_features", []) or []:
            relevant_counts[name] = relevant_counts.get(name, 0) + 1
        for name in record.get("positive_features", []) or []:
            positive_counts[name] = positive_counts.get(name, 0) + 1
        for name in record.get("negative_features", []) or []:
            negative_counts[name] = negative_counts.get(name, 0) + 1
        for name in record.get("neutral_features", []) or []:
            neutral_counts[name] = neutral_counts.get(name, 0) + 1

    # per-feature score aggregates from feature_map
    sum_abs_score: dict[str, float] = {}
    sum_score: dict[str, float] = {}
    nonzero_count: dict[str, int] = {}
    for raw_name in feature_names:
        name = str(raw_name).strip()
        if not is_valid_feature_name(name):
            continue
        sum_abs_score[name] = 0.0
        sum_score[name] = 0.0
        nonzero_count[name] = 0
        for row in rows:
            score = _parse_score(row.get(raw_name, ""))
            sum_abs_score[name] += abs(score)
            sum_score[name] += score
            if score != 0.0:
                nonzero_count[name] += 1

    stats_rows: list[dict] = []
    for raw_name in feature_names:
        name = str(raw_name).strip()
        if not is_valid_feature_name(name):
            continue
        rel = relevant_counts.get(name, 0)
        avg_when_rel = round(sum_score[name] / rel, 3) if rel else 0.0
        stats_rows.append({
            "feature": name,
            "origin": "initial" if name in initial_names else "dynamic",
            "relevant_count": rel,
            "positive_count": positive_counts.get(name, 0),
            "negative_count": negative_counts.get(name, 0),
            "neutral_count": neutral_counts.get(name, 0),
            "avg_score_when_relevant": avg_when_rel,
            "sum_score": round(sum_score[name], 3),
            "sum_abs_score": round(sum_abs_score[name], 3),
            "percentage_relevant": round((rel / total_reviews * 100.0), 1) if total_reviews else 0.0,
        })

    stats_rows.sort(key=lambda row: (-int(row["relevant_count"]), row["origin"], row["feature"]))
    write_csv(
        results_dir / "feature_frequency_stats.csv",
        stats_rows,
        [
            "feature", "origin", "relevant_count", "positive_count",
            "negative_count", "neutral_count", "avg_score_when_relevant",
            "sum_score", "sum_abs_score", "percentage_relevant",
        ],
    )

    timing_rows = timing_summary(diagnostics)
    write_csv(
        results_dir / "agent_timing_summary.csv",
        timing_rows,
        ["agent", "calls", "avg_seconds", "total_seconds", "max_seconds"],
    )

    top_svg = write_top_feature_svg(results_dir, stats_rows, args.top_n)

    lines = [
        f"# Feature Statistics: {results_dir.name}",
        "",
        f"- Reviews processed: {total_reviews}",
        f"- Initial features: {len(initial_names)}",
        f"- New feature candidates observed: {len(new_feature_counts)}",
        f"- Features present in feature_map: {len(feature_names)}",
    ]
    if top_svg:
        lines.extend(["", "## Most Relevant Features (plot)", "", f"![top]({top_svg})", ""])
    lines.extend([
        "## Agent Timing Summary",
        "",
        "| agent | calls | avg seconds | total seconds | max seconds |",
        "|---|---:|---:|---:|---:|",
    ])
    for row in timing_rows:
        lines.append(
            f"| {row['agent']} | {row['calls']} | {row['avg_seconds']} | "
            f"{row['total_seconds']} | {row['max_seconds']} |"
        )
    lines.extend([
        "",
        "## Top Features by Relevance",
        "",
        "| feature | origin | relevant | pos | neg | neu | avg score (relevant) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in stats_rows[: args.top_n]:
        lines.append(
            f"| `{row['feature']}` | {row['origin']} | {row['relevant_count']} | "
            f"{row['positive_count']} | {row['negative_count']} | {row['neutral_count']} | "
            f"{row['avg_score_when_relevant']:+.3f} |"
        )

    (results_dir / "feature_stats_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[stats] Wrote feature stats to {results_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
