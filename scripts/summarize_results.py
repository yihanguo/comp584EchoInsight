"""Generate feature frequency statistics for an EchoInsight V2 results folder."""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path


META_COLUMNS = {
    "review_id",
    "rating",
    "validation_pass",
    "iterations_used",
    "dynamic_features_added",
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


def load_dynamic_counts(results_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    diag_path = results_dir / "review_level_diagnostics.jsonl"
    if not diag_path.exists():
        return counts

    for line in diag_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        for name in record.get("dynamic_features_added", []):
            counts[name] = counts.get(name, 0) + 1
    return counts


def load_diagnostics(results_dir: Path) -> list[dict]:
    diag_path = results_dir / "review_level_diagnostics.jsonl"
    if not diag_path.exists():
        return []

    records = []
    for line in diag_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


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
    max_value = max(int(row["frequency"]) for row in top_rows) or 1
    parts = [
        '<text x="40" y="34" class="title">Top Feature Frequencies</text>',
        f'<text x="40" y="56" class="subtitle">Top {len(top_rows)} features by review-level occurrence; color encodes feature origin.</text>',
    ]
    for tick in range(0, 6):
        x = left + chart_w * tick / 5
        value = round(max_value * tick / 5)
        parts.append(f'<line x1="{x:.1f}" y1="{top - 12}" x2="{x:.1f}" y2="{height - 46}" class="grid"/>')
        parts.append(f'<text x="{x:.1f}" y="{height - 24}" text-anchor="middle" class="axis">{value}</text>')
    parts.append(f'<line x1="{left}" y1="{height - 46}" x2="{left + chart_w}" y2="{height - 46}" class="rule"/>')

    for idx, row in enumerate(top_rows):
        y = top + idx * row_h
        frequency = int(row["frequency"])
        bar_w = chart_w * frequency / max_value
        color = "#2f6f9f" if row["origin"] == "initial" else "#6f8f2f"
        parts.append(f'<text x="{left - 14}" y="{y + 16}" text-anchor="end" class="label">{svg_text(row["feature"])}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_w:.1f}" height="18" rx="2" fill="{color}"/>')
        parts.append(f'<text x="{left + bar_w + 8:.1f}" y="{y + 14}" class="small">{frequency} ({row["percentage"]}%)</text>')
    parts.extend([
        f'<rect x="{left}" y="{height - 14}" width="12" height="12" fill="#2f6f9f"/>',
        f'<text x="{left + 18}" y="{height - 4}" class="small">initial catalog</text>',
        f'<rect x="{left + 132}" y="{height - 14}" width="12" height="12" fill="#6f8f2f"/>',
        f'<text x="{left + 150}" y="{height - 4}" class="small">dynamic discovery</text>',
    ])
    filename = "feature_frequency_top20.svg"
    write_svg(results_dir / filename, "\n".join(parts), width, height)
    return filename


def write_origin_svg(results_dir: Path, origin_rows: list[dict]) -> str:
    width = 820
    height = 310
    left = 95
    top = 80
    chart_w = 620
    row_h = 54
    max_value = max(int(row["total_positive_assignments"]) for row in origin_rows) or 1
    colors = {"initial": "#2f6f9f", "dynamic": "#6f8f2f"}
    parts = [
        '<text x="40" y="34" class="title">Feature-Origin Contribution</text>',
        '<text x="40" y="56" class="subtitle">Total positive feature assignments grouped by source.</text>',
    ]
    for tick in range(0, 6):
        x = left + chart_w * tick / 5
        value = round(max_value * tick / 5)
        parts.append(f'<line x1="{x:.1f}" y1="{top - 16}" x2="{x:.1f}" y2="{top + row_h * len(origin_rows)}" class="grid"/>')
        parts.append(f'<text x="{x:.1f}" y="{height - 36}" text-anchor="middle" class="axis">{value}</text>')
    for idx, row in enumerate(origin_rows):
        y = top + idx * row_h
        value = int(row["total_positive_assignments"])
        bar_w = chart_w * value / max_value
        origin = row["origin"]
        parts.append(f'<text x="{left - 14}" y="{y + 23}" text-anchor="end" class="label">{origin}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_w:.1f}" height="28" rx="2" fill="{colors.get(origin, "#7b8794")}"/>')
        parts.append(
            f'<text x="{left + bar_w + 10:.1f}" y="{y + 19}" class="small">'
            f'{value} assignments, {row["features_with_positive_frequency"]}/{row["features_present"]} active features</text>'
        )
    filename = "feature_origin_contribution.svg"
    write_svg(results_dir / filename, "\n".join(parts), width, height)
    return filename


def timing_summary(records: list[dict]) -> tuple[list[dict], list[dict]]:
    totals = {
        "ClassifyAgent": [],
        "ValidationAgent": [],
        "MasterAgent dynamic": [],
        "Review total": [],
    }
    iter_rows: list[dict] = []
    for record in records:
        review_id = record.get("review_id", "")
        if "elapsed_seconds" in record:
            totals["Review total"].append(float(record.get("elapsed_seconds") or 0.0))
        for iteration in record.get("iteration_detail", []):
            timing = iteration.get("timing_seconds", {})
            row = {
                "review_id": review_id,
                "iteration": iteration.get("iteration", ""),
                "classify_agent": float(timing.get("classify_agent") or 0.0),
                "validation_agent": float(timing.get("validation_agent") or 0.0),
                "master_agent_dynamic": float(timing.get("master_agent_dynamic") or 0.0),
                "iteration_elapsed": float(iteration.get("elapsed_seconds") or 0.0),
            }
            iter_rows.append(row)
            if row["classify_agent"]:
                totals["ClassifyAgent"].append(row["classify_agent"])
            if row["validation_agent"]:
                totals["ValidationAgent"].append(row["validation_agent"])
            if row["master_agent_dynamic"]:
                totals["MasterAgent dynamic"].append(row["master_agent_dynamic"])

    summary = []
    for agent, values in totals.items():
        if values:
            summary.append({
                "agent": agent,
                "calls": len(values),
                "avg_seconds": round(sum(values) / len(values), 2),
                "total_seconds": round(sum(values), 2),
                "max_seconds": round(max(values), 2),
            })
        else:
            summary.append({"agent": agent, "calls": 0, "avg_seconds": 0.0, "total_seconds": 0.0, "max_seconds": 0.0})
    return summary, iter_rows


def write_timing_svg(results_dir: Path, timing_rows: list[dict]) -> str | None:
    rows = [row for row in timing_rows if row["calls"] > 0 and row["agent"] != "Review total"]
    if not rows:
        return None
    width = 840
    height = 330
    left = 180
    top = 84
    chart_w = 560
    row_h = 50
    max_value = max(float(row["avg_seconds"]) for row in rows) or 1.0
    colors = ["#2f6f9f", "#7a4eab", "#6f8f2f"]
    parts = [
        '<text x="40" y="34" class="title">Mean Agent Latency</text>',
        '<text x="40" y="56" class="subtitle">Average wall-clock seconds per agent call from review diagnostics.</text>',
    ]
    for tick in range(0, 6):
        x = left + chart_w * tick / 5
        value = max_value * tick / 5
        parts.append(f'<line x1="{x:.1f}" y1="{top - 16}" x2="{x:.1f}" y2="{top + row_h * len(rows)}" class="grid"/>')
        parts.append(f'<text x="{x:.1f}" y="{height - 34}" text-anchor="middle" class="axis">{value:.1f}s</text>')
    for idx, row in enumerate(rows):
        y = top + idx * row_h
        value = float(row["avg_seconds"])
        bar_w = chart_w * value / max_value
        parts.append(f'<text x="{left - 14}" y="{y + 22}" text-anchor="end" class="label">{svg_text(row["agent"])}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_w:.1f}" height="28" rx="2" fill="{colors[idx % len(colors)]}"/>')
        parts.append(f'<text x="{left + bar_w + 10:.1f}" y="{y + 19}" class="small">{value:.2f}s avg, n={row["calls"]}</text>')
    filename = "agent_latency_summary.svg"
    write_svg(results_dir / filename, "\n".join(parts), width, height)
    return filename


def write_iteration_svg(results_dir: Path, records: list[dict]) -> str | None:
    if not records:
        return None
    counts: dict[int, int] = {}
    for record in records:
        iters = int(record.get("iterations_used") or 0)
        counts[iters] = counts.get(iters, 0) + 1
    width = 760
    height = 330
    left = 72
    bottom = 258
    chart_h = 170
    bar_w = 64
    gap = 34
    max_count = max(counts.values()) or 1
    parts = [
        '<text x="40" y="34" class="title">Validation Iteration Distribution</text>',
        '<text x="40" y="56" class="subtitle">Number of dynamic refinement rounds needed per review.</text>',
    ]
    for tick in range(0, 5):
        y = bottom - chart_h * tick / 4
        value = round(max_count * tick / 4)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - 48}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end" class="axis">{value}</text>')
    for idx, iteration in enumerate(sorted(counts)):
        x = left + 34 + idx * (bar_w + gap)
        value = counts[iteration]
        h = chart_h * value / max_count
        y = bottom - h
        parts.append(f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" rx="2" fill="#2f6f9f"/>')
        parts.append(f'<text x="{x + bar_w / 2}" y="{y - 8:.1f}" text-anchor="middle" class="small">{value}</text>')
        parts.append(f'<text x="{x + bar_w / 2}" y="{bottom + 24}" text-anchor="middle" class="axis">{iteration} iter</text>')
    filename = "iteration_distribution.svg"
    write_svg(results_dir / filename, "\n".join(parts), width, height)
    return filename


def write_visual_dashboard(results_dir: Path, visual_files: list[str], summary: dict, timing_rows: list[dict]) -> str | None:
    if not visual_files:
        return None
    timing_cards = []
    for row in timing_rows:
        timing_cards.append(
            f"""
            <div class="metric">
              <div class="metric-label">{svg_text(row['agent'])}</div>
              <div class="metric-value">{row['avg_seconds']}s</div>
              <div class="metric-sub">avg, n={row['calls']}</div>
            </div>
            """
        )
    figures = []
    for filename in visual_files:
        title = filename.removesuffix(".svg").replace("_", " ").title()
        figures.append(
            f"""
            <section class="figure">
              <h2>{svg_text(title)}</h2>
              <img src="{svg_text(filename)}" alt="{svg_text(title)}">
            </section>
            """
        )
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>EchoInsight Visual Summary - {svg_text(results_dir.name)}</title>
  <style>
    body {{
      margin: 0;
      background: #f6f8fa;
      color: #1f2933;
      font-family: Arial, sans-serif;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 28px 48px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      letter-spacing: 0;
    }}
    .subtitle {{
      margin: 0 0 24px;
      color: #52616b;
      font-size: 14px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }}
    .metric {{
      background: #fff;
      border: 1px solid #d9e2ec;
      border-radius: 6px;
      padding: 14px 16px;
    }}
    .metric-label {{
      font-size: 12px;
      color: #52616b;
    }}
    .metric-value {{
      font-size: 24px;
      font-weight: 700;
      margin-top: 6px;
    }}
    .metric-sub {{
      font-size: 12px;
      color: #7b8794;
      margin-top: 4px;
    }}
    .figure {{
      background: #fff;
      border: 1px solid #d9e2ec;
      border-radius: 6px;
      padding: 18px 20px 22px;
      margin-bottom: 18px;
    }}
    h2 {{
      font-size: 17px;
      margin: 0 0 12px;
    }}
    img {{
      width: 100%;
      height: auto;
      display: block;
    }}
  </style>
</head>
<body>
  <main>
    <h1>EchoInsight Visual Summary: {svg_text(results_dir.name)}</h1>
    <p class="subtitle">Reviews={summary.get('total_reviews', '?')} · pass rate={summary.get('validation_pass_rate', '?')} · elapsed={summary.get('elapsed_seconds', '?')}s</p>
    <div class="metrics">
      {''.join(timing_cards)}
    </div>
    {''.join(figures)}
  </main>
</body>
</html>
"""
    filename = "visual_dashboard.html"
    (results_dir / filename).write_text(html_doc, encoding="utf-8")
    return filename


def main() -> int:
    args = parse_args()
    results_dir = Path(args.results_dir).expanduser().resolve()
    feature_map_path = results_dir / "feature_map.csv"

    feature_names, rows = load_feature_map(feature_map_path)
    total_reviews = len(rows)
    run_log = read_json(results_dir / "v2_run_log.json", {})
    initial_catalog = run_log.get("initial_catalog", [])
    initial_names = {str(item.get("name")).strip() for item in initial_catalog if is_valid_feature_name(item.get("name"))}
    dynamic_counts = {
        str(name).strip(): count
        for name, count in load_dynamic_counts(results_dir).items()
        if is_valid_feature_name(name)
    }
    diagnostics = load_diagnostics(results_dir)

    stats_rows: list[dict] = []
    for raw_name in feature_names:
        name = str(raw_name).strip()
        if not is_valid_feature_name(name):
            continue
        frequency = sum(1 for row in rows if str(row.get(name, "")).strip() in {"1", "true", "True"})
        percentage = round((frequency / total_reviews * 100.0), 1) if total_reviews else 0.0
        origin = "initial" if name in initial_names else "dynamic"
        stats_rows.append({
            "feature": name,
            "origin": origin,
            "frequency": frequency,
            "percentage": percentage,
            "dynamic_generated_rows": dynamic_counts.get(name, 0),
        })

    stats_rows.sort(key=lambda row: (-int(row["frequency"]), row["origin"], row["feature"]))
    write_csv(
        results_dir / "feature_frequency_stats.csv",
        stats_rows,
        ["feature", "origin", "frequency", "percentage", "dynamic_generated_rows"],
    )

    origin_rows = []
    for origin in ("initial", "dynamic"):
        origin_features = [row for row in stats_rows if row["origin"] == origin]
        origin_rows.append({
            "origin": origin,
            "features_present": len(origin_features),
            "features_with_positive_frequency": sum(1 for row in origin_features if int(row["frequency"]) > 0),
            "total_positive_assignments": sum(int(row["frequency"]) for row in origin_features),
        })
    write_csv(
        results_dir / "feature_origin_stats.csv",
        origin_rows,
        ["origin", "features_present", "features_with_positive_frequency", "total_positive_assignments"],
    )

    timing_rows, timing_detail_rows = timing_summary(diagnostics)
    write_csv(
        results_dir / "agent_timing_summary.csv",
        timing_rows,
        ["agent", "calls", "avg_seconds", "total_seconds", "max_seconds"],
    )
    write_csv(
        results_dir / "agent_timing_detail.csv",
        timing_detail_rows,
        ["review_id", "iteration", "classify_agent", "validation_agent", "master_agent_dynamic", "iteration_elapsed"],
    )

    visual_files = [
        write_top_feature_svg(results_dir, stats_rows, args.top_n),
        write_origin_svg(results_dir, origin_rows),
        write_timing_svg(results_dir, timing_rows),
        write_iteration_svg(results_dir, diagnostics),
    ]
    visual_files = [filename for filename in visual_files if filename]
    dashboard_file = write_visual_dashboard(
        results_dir,
        visual_files,
        read_json(results_dir / "v2_summary.json", {}),
        timing_rows,
    )

    dynamic_names = [row["feature"] for row in stats_rows if row["origin"] == "dynamic"]
    lines = [
        f"# Feature Statistics: {results_dir.name}",
        "",
        f"- Reviews processed: {total_reviews}",
        f"- Initial features: {len(initial_names)}",
        f"- Dynamic features generated: {len(dynamic_counts)}",
        f"- Features present in feature_map: {len(feature_names)}",
        f"- Initial features with positive frequency: {sum(1 for row in stats_rows if row['origin'] == 'initial' and int(row['frequency']) > 0)}",
        f"- Dynamic features with positive frequency: {sum(1 for row in stats_rows if row['origin'] == 'dynamic' and int(row['frequency']) > 0)}",
    ]
    if visual_files:
        lines.extend(["", "## Visual Summary", ""])
        if dashboard_file:
            lines.extend([f"- Dashboard: [{dashboard_file}]({dashboard_file})", ""])
        for filename in visual_files:
            title = filename.removesuffix(".svg").replace("_", " ").title()
            lines.extend([f"### {title}", "", f"![{title}]({filename})", ""])
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
        "## Top Feature Frequencies",
        "",
        "| feature | origin | frequency | percentage |",
        "|---|---:|---:|---:|",
    ])
    for row in stats_rows[: args.top_n]:
        lines.append(f"| `{row['feature']}` | {row['origin']} | {row['frequency']} | {row['percentage']}% |")

    lines.extend(["", "## Initial Features", "", "| feature | frequency | percentage |", "|---|---:|---:|"])
    for name in sorted(initial_names):
        row = next((item for item in stats_rows if item["feature"] == name), None)
        frequency = row["frequency"] if row else 0
        percentage = row["percentage"] if row else 0.0
        lines.append(f"| `{name}` | {frequency} | {percentage}% |")

    lines.extend([
        "",
        "## Dynamic Features",
        "",
        "| feature | frequency | percentage | generated rows |",
        "|---|---:|---:|---:|",
    ])
    for name in sorted(dynamic_names):
        row = next(item for item in stats_rows if item["feature"] == name)
        lines.append(
            f"| `{name}` | {row['frequency']} | {row['percentage']}% | {row['dynamic_generated_rows']} |"
        )

    (results_dir / "feature_stats_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[stats] Wrote feature stats to {results_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
