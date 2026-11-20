"""Aggregate the frozen matched-budget corpus into an honest offline A/B/C report.

This script does **not** call any provider. It reads the frozen claim
observations, recomputes run-level and paired summaries, and writes a
machine-readable report plus a Markdown companion. Strategy D (full
AxiomScope v2) and live evaluation are reported as NOT_MEASURED, never inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_OBSERVATIONS = Path(
    "experiments/independent_comparison/claim_scores/"
    "continuation_matched_budget_deepseek_flash_20261019_v5_replay_20261019/"
    "claim_observations.jsonl"
)
GROUND_TRUTH = Path(
    "experiments/independent_comparison/ground_truth/"
    "continuation_ground_truth_20261019.jsonl"
)
GROUP_LABELS = {
    "A": "传统检索模拟 + 单次 LLM 合成",
    "B": "通用联网 AI",
    "C": "CountyResearchAI 旧管线",
    "D": "AxiomScope v2（未测）",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_runs(path: Path) -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            runs.setdefault(str(row["run_id"]), row)
    return runs


def _valid(run: dict[str, Any]) -> bool:
    return str(run.get("status", "")).startswith("VALID")


def _key(run: dict[str, Any]) -> tuple[str, str, int]:
    return (str(run.get("region", "")), str(run.get("task_id", "")), int(run.get("repeat", 1)))


def _numbers(values: list[Any]) -> list[float]:
    return [float(value) for value in values if isinstance(value, (int, float))]


def _mean(values: list[Any]) -> float | None:
    numbers = _numbers(values)
    return round(sum(numbers) / len(numbers), 4) if numbers else None


def _units(run: dict[str, Any], resource: str) -> int:
    return int(run.get("resource_usage", {}).get(resource, 0))


def group_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [run for run in runs if _valid(run)]
    metrics = [run.get("task_metrics", {}) for run in valid]
    supported = sum(int(item.get("supported_claims", 0)) for item in metrics)
    verifiable = sum(int(item.get("verifiable_report_claims", 0)) for item in metrics)
    report_claims = sum(int(item.get("report_claim_count", 0)) for item in metrics)
    gt_claims = sum(int(item.get("total_ground_truth_claims", 0)) for item in metrics)
    return {
        "runs": len(runs),
        "valid_runs": len(valid),
        "excluded_runs": len(runs) - len(valid),
        "ground_truth_recall_mean": _mean(
            [item.get("ground_truth_recall") for item in metrics]
        ),
        "evidence_support_rate_mean": _mean(
            [item.get("evidence_support_rate") for item in metrics]
        ),
        "fact_accuracy_mean": _mean([item.get("fact_accuracy") for item in metrics]),
        "factual_error_rate_mean": _mean(
            [item.get("factual_error_rate") for item in metrics]
        ),
        "supported_claims": supported,
        "verifiable_report_claims": verifiable,
        "support_precision_pooled": round(supported / verifiable, 4)
        if verifiable
        else None,
        "report_claim_count": report_claims,
        "total_ground_truth_claims": gt_claims,
        "llm_units_total": sum(
            _units(run, "deepseek:deepseek-flash:llm") for run in valid
        ),
        "llm_units_per_run": round(
            sum(_units(run, "deepseek:deepseek-flash:llm") for run in valid)
            / len(valid),
            1,
        )
        if valid
        else None,
        "search_units_total": sum(
            _units(run, "tavily:search:search") for run in valid
        ),
        "seconds_total": round(
            sum(float(run.get("duration_seconds", 0.0)) for run in valid), 2
        ),
        "seconds_per_run": round(
            sum(float(run.get("duration_seconds", 0.0)) for run in valid)
            / len(valid),
            2,
        )
        if valid
        else None,
    }


def paired_summary(
    left: dict[str, dict[str, Any]],
    right: dict[str, dict[str, Any]],
    *,
    left_name: str,
    right_name: str,
) -> dict[str, Any]:
    shared = sorted(set(left) & set(right))
    comparisons: list[dict[str, Any]] = []
    for key in shared:
        left_metrics = left[key].get("task_metrics", {})
        right_metrics = right[key].get("task_metrics", {})
        left_recall = float(left_metrics.get("ground_truth_recall") or 0.0)
        right_recall = float(right_metrics.get("ground_truth_recall") or 0.0)
        comparisons.append(
            {
                "key": list(key),
                "ground_truth_recall": {
                    left_name: left_recall,
                    right_name: right_recall,
                    "delta": round(left_recall - right_recall, 4),
                },
                "llm_units": {
                    left_name: _units(left[key], "deepseek:deepseek-flash:llm"),
                    right_name: _units(right[key], "deepseek:deepseek-flash:llm"),
                },
                "seconds": {
                    left_name: float(left[key].get("duration_seconds", 0.0)),
                    right_name: float(right[key].get("duration_seconds", 0.0)),
                },
            }
        )
    deltas = [item["ground_truth_recall"]["delta"] for item in comparisons]
    return {
        "left": left_name,
        "right": right_name,
        "paired_cases": len(comparisons),
        "recall_delta_mean": round(sum(deltas) / len(deltas), 4) if deltas else None,
        "left_wins": sum(1 for value in deltas if value > 0),
        "ties": sum(1 for value in deltas if value == 0),
        "right_wins": sum(1 for value in deltas if value < 0),
        "cases": comparisons,
    }


def build_report(observations: Path) -> dict[str, Any]:
    runs = load_runs(observations)
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs.values():
        by_group[str(run.get("group", "?"))].append(run)
    summaries = {
        group: group_summary(items) for group, items in sorted(by_group.items())
    }
    valid_by_group = {
        group: {_key(run): run for run in items if _valid(run)}
        for group, items in by_group.items()
    }
    paired = {}
    if "C" in valid_by_group:
        for other in ("A", "B"):
            if other in valid_by_group:
                paired[f"{other}_vs_C"] = paired_summary(
                    valid_by_group[other],
                    valid_by_group["C"],
                    left_name=other,
                    right_name="C",
                )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "OFFLINE_REPLAY",
        "provider_calls": 0,
        "semantic_judge_calls": 0,
        "observations_path": str(observations),
        "observations_sha256": sha256_file(observations),
        "ground_truth_path": str(GROUND_TRUTH),
        "ground_truth_sha256": sha256_file(GROUND_TRUTH)
        if GROUND_TRUTH.is_file()
        else None,
        "unique_runs": len(runs),
        "groups": {
            group: GROUP_LABELS.get(group, group) for group in sorted(by_group)
        },
        "summaries": summaries,
        "paired": paired,
        "not_measured": {
            "D": "full AxiomScope v2 not run on this corpus",
            "live": "BLOCKED_EXTERNAL: no new provider/Judge cost authorization",
            "ablations": "NOT_RUN: no graph/semantic-verifier/gap-research/hybrid ablation",
            "independent_task_set": "NOT_RUN: this corpus is the inherited frozen set, not a newly curated 40-60 task holdout",
        },
        "caveats": [
            "Small sample; no statistical significance is claimed.",
            "C has 12 valid runs; six long-history runs exceeded the 120s budget and are excluded from means.",
            "All metrics are deterministic offline rescoring of frozen outputs.",
            "The report cannot establish that AxiomScope v2 beats any baseline.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Multi-baseline offline comparison",
        "",
        f"Generated: {report['generated_at']}",
        f"Evidence kind: `{report['evidence_kind']}` · provider calls: {report['provider_calls']}",
        f"Observations SHA-256: `{report['observations_sha256']}`",
        "",
        "| Group | Valid runs | GT recall (mean) | Support precision (pooled) | Fact accuracy | Error rate | LLM units/run | Seconds/run |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group, item in report["summaries"].items():
        lines.append(
            "| {group} {label} | {valid} | {recall} | {precision} ({sup}/{ver}) | "
            "{fact} | {error} | {units} | {seconds} |".format(
                group=group,
                label=report["groups"].get(group, ""),
                valid=item["valid_runs"],
                recall=item["ground_truth_recall_mean"],
                precision=item["support_precision_pooled"],
                sup=item["supported_claims"],
                ver=item["verifiable_report_claims"],
                fact=item["fact_accuracy_mean"],
                error=item["factual_error_rate_mean"],
                units=item["llm_units_per_run"],
                seconds=item["seconds_per_run"],
            )
        )
    lines += ["", "## Paired comparisons", ""]
    for item in report["paired"].values():
        lines.append(
            f"- **{item['left']} vs {item['right']}**: {item['paired_cases']} paired cases, "
            f"mean recall delta {item['recall_delta_mean']}, "
            f"{item['left_wins']} wins / {item['ties']} ties / {item['right_wins']} losses "
            f"for {item['left']}."
        )
    lines += ["", "## Not measured", ""]
    for key, value in report["not_measured"].items():
        lines.append(f"- `{key}`: {value}")
    lines += ["", "## Caveats", ""]
    for caveat in report["caveats"]:
        lines.append(f"- {caveat}")
    lines.append("")
    return "\n".join(lines)


def build_dataset_manifest(
    runs: dict[str, dict[str, Any]], observations: Path
) -> dict[str, Any]:
    rows = [
        {
            "run_id": run_id,
            "group": run.get("group"),
            "region": run.get("region"),
            "task_id": run.get("task_id"),
            "repeat": run.get("repeat"),
            "status": run.get("status"),
            "duration_seconds": run.get("duration_seconds"),
            "resource_usage": run.get("resource_usage", {}),
        }
        for run_id, run in sorted(runs.items())
    ]
    return {
        "evidence_kind": "OFFLINE_REPLAY",
        "observations_path": str(observations),
        "observations_sha256": sha256_file(observations),
        "ground_truth_path": str(GROUND_TRUTH),
        "ground_truth_sha256": sha256_file(GROUND_TRUTH)
        if GROUND_TRUTH.is_file()
        else None,
        "task_keys": sorted(
            {
                (str(run.get("region")), str(run.get("task_id")), int(run.get("repeat", 1)))
                for run in runs.values()
            }
        ),
        "groups": sorted({str(run.get("group")) for run in runs.values()}),
        "runs": rows,
        "note": (
            "Inherited frozen corpus, not a newly curated independent holdout. "
            "Task keys are reused across strategies for pairing."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/evaluation/20261026_multi_baseline_offline"),
    )
    args = parser.parse_args()
    report = build_report(args.observations)
    runs = load_runs(args.observations)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "dataset_manifest.json").write_text(
        json.dumps(build_dataset_manifest(runs, args.observations), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "summary.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["summaries"], ensure_ascii=False, indent=2))
    print(f"wrote {args.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
