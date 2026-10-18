"""从有效运行的声明级指标生成小样本统计和真实数据图表。"""
from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any

from county_research_ai.evaluation.experiment_models import RunStatus
from county_research_ai.evaluation.metrics import MetricsResult
from county_research_ai.evaluation.reporting import write_metrics_csv
from county_research_ai.evaluation.statistics import (
    MetricObservation,
    paired_difference,
    summarize_observations,
    summarize_observations_by_region,
)

_PAIRABLE_METRICS = (
    "fact_accuracy",
    "key_fact_coverage",
    "evidence_support_rate",
    "error_rate",
    "analysis_depth",
    "report_qa_accuracy",
    "duration_seconds",
    "llm_tokens",
    "search_requests",
    "coverage_per_llm_token",
)
_FIGURE_METRICS = (
    "fact_accuracy",
    "key_fact_coverage",
    "evidence_support_rate",
    "error_rate",
    "analysis_depth",
    "report_qa_accuracy",
    "duration_seconds",
    "llm_tokens",
    "search_requests",
)


def generate_stats(
    source: Path,
    *,
    summary_csv: Path,
    paired_csv: Path,
    summary_json: Path,
    figures_dir: Path,
) -> dict[str, Any]:
    observations = _load_observations(source)
    summary_rows = summarize_observations(observations)
    region_summary_rows = summarize_observations_by_region(observations)
    paired_rows = []
    for metric in _PAIRABLE_METRICS:
        for left, right in (("C", "A"), ("C", "B")):
            try:
                paired_rows.append(
                    paired_difference(
                        observations,
                        left_group=left,
                        right_group=right,
                        metric=metric,
                    ).to_dict()
                )
            except ValueError:
                continue

    status = "OK" if observations else "NO_VALID_METRICS"
    write_metrics_csv(summary_csv, [row.to_dict() for row in summary_rows])
    region_summary_csv = summary_csv.with_name("region_summary.csv")
    write_metrics_csv(region_summary_csv, [row.to_dict() for row in region_summary_rows])
    write_metrics_csv(paired_csv, paired_rows)
    payload = {
        "status": status,
        "valid_observations": len(observations),
        "summary_rows": len(summary_rows),
        "region_summary_rows": len(region_summary_rows),
        "paired_rows": len(paired_rows),
        "figures_generated": [],
    }
    if observations:
        figures_dir.mkdir(parents=True, exist_ok=True)
        for metric in _FIGURE_METRICS:
            path = figures_dir / f"{metric}.svg"
            _write_bar_svg(path, [row for row in summary_rows if row.metric == metric])
            payload["figures_generated"].append(str(path))
            region_path = figures_dir / f"region_{metric}.svg"
            _write_region_svg(
                region_path,
                [row for row in region_summary_rows if row.metric == metric],
            )
            payload["figures_generated"].append(str(region_path))
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def _load_observations(path: Path) -> list[MetricObservation]:
    observations: list[MetricObservation] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if value.get("status") != RunStatus.VALID.value:
            continue
        metrics = value.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError(f"VALID metric record missing metrics at line {line_number}")
        observations.append(
            MetricObservation(
                run_id=str(value["run_id"]),
                group=str(value["group"]),
                region=str(value["region"]),
                task_id=str(value["task_id"]),
                repeat=int(value.get("repeat", 1)),
                metrics=MetricsResult(**metrics),
                duration_seconds=value.get("duration_seconds"),
                resource_usage={
                    str(key): int(amount)
                    for key, amount in dict(value.get("resource_usage", {})).items()
                },
            )
        )
    return observations


def _write_bar_svg(path: Path, rows: list[Any]) -> None:
    width, height = 640, 300
    chart_top, chart_bottom = 32, 250
    bar_width = 100
    gap = 36
    bars = []
    scale = max((abs(float(row.mean)) for row in rows), default=1.0) or 1.0
    for index, row in enumerate(rows):
        x = 60 + index * (bar_width + gap)
        raw_value = float(row.mean)
        value = max(0.0, min(1.0, raw_value / scale))
        bar_height = value * (chart_bottom - chart_top)
        y = chart_bottom - bar_height
        label = escape(str(row.group))
        bars.append(
            f'<rect x="{x}" y="{y:.2f}" width="{bar_width}" height="{bar_height:.2f}" fill="#2563eb" />'
            f'<text x="{x + bar_width / 2}" y="270" text-anchor="middle">{label}</text>'
            f'<text x="{x + bar_width / 2}" y="{max(20, y - 6):.2f}" text-anchor="middle">{raw_value:.3f}</text>'
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                '<rect width="100%" height="100%" fill="white" />',
                '<line x1="40" y1="32" x2="40" y2="250" stroke="#111827" />',
                '<line x1="40" y1="250" x2="600" y2="250" stroke="#111827" />',
                *bars,
                "</svg>",
            ]
        ),
        encoding="utf-8",
    )


def _write_region_svg(path: Path, rows: list[Any]) -> None:
    width, height = 960, 360
    chart_top, chart_bottom = 32, 290
    bar_width = 72
    gap = 20
    bars = []
    scale = max((abs(float(row.mean)) for row in rows), default=1.0) or 1.0
    for index, row in enumerate(rows):
        x = 40 + index * (bar_width + gap)
        raw_value = float(row.mean)
        value = max(0.0, min(1.0, raw_value / scale))
        bar_height = value * (chart_bottom - chart_top)
        y = chart_bottom - bar_height
        label = escape(f"{row.region}/{row.group}")
        bars.append(
            f'<rect x="{x}" y="{y:.2f}" width="{bar_width}" height="{bar_height:.2f}" fill="#059669" />'
            f'<text x="{x + bar_width / 2}" y="310" text-anchor="middle" transform="rotate(-35 {x + bar_width / 2} 310)">{label}</text>'
            f'<text x="{x + bar_width / 2}" y="{max(20, y - 6):.2f}" text-anchor="middle">{raw_value:.3f}</text>'
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                '<rect width="100%" height="100%" fill="white" />',
                f'<line x1="24" y1="{chart_top}" x2="24" y2="{chart_bottom}" stroke="#111827" />',
                f'<line x1="24" y1="{chart_bottom}" x2="930" y2="{chart_bottom}" stroke="#111827" />',
                *bars,
                "</svg>",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--summary-csv", type=Path, required=True)
    parser.add_argument("--paired-csv", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--figures-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            generate_stats(
                args.source,
                summary_csv=args.summary_csv,
                paired_csv=args.paired_csv,
                summary_json=args.summary_json,
                figures_dir=args.figures_dir,
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
