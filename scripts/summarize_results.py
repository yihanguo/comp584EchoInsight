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


def load_dynamic_added_counts(diagnostics: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in diagnostics:
        for name in record.get("dynamic_features_added", []) or []:
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


def write_simple_bar_svg(
    results_dir: Path,
    filename: str,
    title: str,
    subtitle: str,
    rows: list[tuple[str, int]],
    color: str = "#3b82a0",
) -> str | None:
    rows = [(label, int(value)) for label, value in rows if int(value) > 0]
    if not rows:
        content = "\n".join([
            f'<text x="40" y="34" class="title">{svg_text(title)}</text>',
            f'<text x="40" y="56" class="subtitle">{svg_text(subtitle)}</text>',
            '<text x="40" y="96" class="label">No data for this run.</text>',
        ])
        write_svg(results_dir / filename, content, 900, 140)
        return filename
    width = 900
    row_h = 30
    top = 78
    left = 230
    right = 80
    chart_w = width - left - right
    height = top + row_h * len(rows) + 54
    max_value = max(value for _, value in rows) or 1
    parts = [
        f'<text x="40" y="34" class="title">{svg_text(title)}</text>',
        f'<text x="40" y="56" class="subtitle">{svg_text(subtitle)}</text>',
    ]
    for idx, (label, value) in enumerate(rows):
        y = top + idx * row_h
        bar_w = chart_w * value / max_value
        parts.append(f'<text x="{left - 14}" y="{y + 16}" text-anchor="end" class="label">{svg_text(label)}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_w:.1f}" height="18" rx="2" fill="{color}"/>')
        parts.append(f'<text x="{left + bar_w + 8:.1f}" y="{y + 14}" class="small">{value}</text>')
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
        t_total = timing.get("classify_total")
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

    validation = [float((r.get("agent_timing", {}) or {}).get("validation_agent", 0.0) or 0.0) for r in records]
    master_dynamic = [float((r.get("agent_timing", {}) or {}).get("master_agent_dynamic", 0.0) or 0.0) for r in records]

    return [
        _row("Review total", review_totals),
        _row("ClassifyAgent total per review", classify_totals),
        _row("ClassifyAgent per feature", per_feature),
        _row("ValidationAgent per review", validation),
        _row("MasterAgent dynamic per review", master_dynamic),
    ]


def validation_summary(records: list[dict]) -> dict:
    values = [record.get("validation_pass") for record in records if record.get("validation_pass") is not None]
    pass_count = sum(1 for value in values if bool(value))
    fail_count = sum(1 for value in values if not bool(value))
    iterations = [int(record.get("validation_iterations_used", 0) or 0) for record in records]
    seconds = [float((record.get("agent_timing", {}) or {}).get("validation_agent", 0.0) or 0.0) for record in records]
    return {
        "enabled_records": len(values),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate": round(pass_count / max(len(values), 1), 3),
        "avg_iterations": round(sum(iterations) / max(len(records), 1), 2),
        "avg_seconds": round(sum(seconds) / max(len(records), 1), 2),
    }


def write_dashboard(
    results_dir: Path,
    total_reviews: int,
    stats_rows: list[dict],
    validation: dict,
    svg_files: list[str],
) -> None:
    top_features = stats_rows[:10]
    links = "\n".join(
        f'<section><h2>{html.escape(name)}</h2><img src="{html.escape(name)}" alt="{html.escape(name)}"></section>'
        for name in svg_files
        if name
    )
    feature_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row['feature']))}</td>"
        f"<td>{row['origin']}</td>"
        f"<td>{row['relevant_count']}</td>"
        f"<td>{row['avg_score_when_relevant']:+.3f}</td>"
        "</tr>"
        for row in top_features
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>EchoInsight Visual Dashboard</title>
<style>
body{{font-family:Arial,sans-serif;margin:32px;color:#1f2933;background:#f7f8fa}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:24px}}
.metric{{background:#fff;border:1px solid #d9e2ec;border-radius:8px;padding:14px}}
.metric b{{display:block;font-size:24px;margin-top:8px}}
section{{background:#fff;border:1px solid #d9e2ec;border-radius:8px;padding:18px;margin:16px 0}}
img{{max-width:100%;height:auto}}
table{{border-collapse:collapse;width:100%;background:#fff}}
th,td{{border-bottom:1px solid #e5e7eb;text-align:left;padding:8px}}
</style>
</head>
<body>
<h1>EchoInsight Visual Dashboard</h1>
<div class="metrics">
<div class="metric">Reviews<b>{total_reviews}</b></div>
<div class="metric">Validation pass rate<b>{validation['pass_rate']}</b></div>
<div class="metric">Validation failed<b>{validation['fail_count']}</b></div>
<div class="metric">Avg validation iterations<b>{validation['avg_iterations']}</b></div>
<div class="metric">Avg validation seconds<b>{validation['avg_seconds']}s</b></div>
</div>
{links}
<section>
<h2>Top Relevant Features</h2>
<table><thead><tr><th>Feature</th><th>Origin</th><th>Relevant</th><th>Avg Score</th></tr></thead><tbody>{feature_rows}</tbody></table>
</section>
</body>
</html>
"""
    (results_dir / "visual_dashboard.html").write_text(page, encoding="utf-8")


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
    dynamic_added_counts = load_dynamic_added_counts(diagnostics)

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
    validation = validation_summary(diagnostics)
    validation_svg = write_simple_bar_svg(
        results_dir,
        "validation_distribution.svg",
        "Validation Pass/Fail Distribution",
        "Coverage validation result across processed reviews.",
        [("pass", validation["pass_count"]), ("fail", validation["fail_count"])],
        "#427f4a",
    )
    iteration_counts: dict[str, int] = {}
    for record in diagnostics:
        key = str(record.get("validation_iterations_used", 0) or 0)
        iteration_counts[key] = iteration_counts.get(key, 0) + 1
    iteration_svg = write_simple_bar_svg(
        results_dir,
        "validation_iteration_distribution.svg",
        "Validation Iteration Distribution",
        "How many validation passes each review needed.",
        sorted(iteration_counts.items(), key=lambda kv: int(kv[0])),
        "#7c6f2b",
    )
    candidates_svg = write_simple_bar_svg(
        results_dir,
        "new_feature_candidate_frequency.svg",
        "New Feature Candidate Frequency",
        "MasterAgent candidates proposed after validation failure.",
        sorted(new_feature_counts.items(), key=lambda kv: (-kv[1], kv[0]))[: args.top_n],
        "#8b5a2b",
    )
    dynamic_svg = write_simple_bar_svg(
        results_dir,
        "dynamic_feature_added_frequency.svg",
        "Dynamic Feature Added Frequency",
        "Accepted dynamic features classified for current reviews.",
        sorted(dynamic_added_counts.items(), key=lambda kv: (-kv[1], kv[0]))[: args.top_n],
        "#7b4aa0",
    )
    latency_svg = write_simple_bar_svg(
        results_dir,
        "agent_latency_summary.svg",
        "Agent Latency Summary",
        "Total seconds by agent role.",
        [(row["agent"], int(round(float(row["total_seconds"])))) for row in timing_rows],
        "#4f7898",
    )
    svg_files = [top_svg, validation_svg, iteration_svg, latency_svg, candidates_svg, dynamic_svg]
    write_dashboard(results_dir, total_reviews, stats_rows, validation, [f for f in svg_files if f])

    lines = [
        f"# Feature Statistics: {results_dir.name}",
        "",
        f"- Reviews processed: {total_reviews}",
        f"- Initial features: {len(initial_names)}",
        f"- New feature candidates observed: {len(new_feature_counts)}",
        f"- Dynamic features added: {len(dynamic_added_counts)}",
        f"- Validation pass rate: {validation['pass_rate']}",
        f"- Validation failed reviews: {validation['fail_count']}",
        f"- Avg validation iterations: {validation['avg_iterations']}",
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
        "## Validation Visualizations",
        "",
    ])
    for svg in [validation_svg, iteration_svg, latency_svg, candidates_svg, dynamic_svg]:
        if svg:
            lines.extend([f"![{svg}]({svg})", ""])
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
