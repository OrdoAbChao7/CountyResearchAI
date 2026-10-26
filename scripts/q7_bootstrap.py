"""Task-clustered bootstrap for the dev Strategy D comparisons.

Facts within one research task are correlated, so resample tasks, not facts.
This is dev-replay only; no sealed holdout exists.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

Q3 = Path("experiments/quality/20261026_q3_strategy_d/per_case.jsonl")
POOLED = Path("experiments/quality/20261026_q7_pooled_eval/per_case.jsonl")
POOLED_FREE = Path("experiments/quality/20261026_q7_pooled_free_eval/per_case.jsonl")
OUTPUT = Path("experiments/quality/20261026_q7_bootstrap")


def _load(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def task_rates(rows: list[dict], key: str) -> dict[tuple[str, str], float]:
    groups: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in rows:
        task = (row.get("region") or row.get("county") or "", row.get("mode") or row.get("task_id") or "")
        groups[task].append(bool(row.get(key)))
    return {task: sum(values) / len(values) for task, values in groups.items()}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def paired_bootstrap(
    left: dict[tuple[str, str], float],
    right: dict[tuple[str, str], float],
    *,
    seed: int = 20261026,
    iterations: int = 4000,
) -> dict:
    tasks = sorted(set(left) & set(right))
    if not tasks:
        return {"tasks": 0}
    diffs = [left[task] - right[task] for task in tasks]
    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        sample = [diffs[rng.randrange(len(diffs))] for _ in diffs]
        means.append(sum(sample) / len(sample))
    return {
        "tasks": len(tasks),
        "mean_difference": round(sum(diffs) / len(diffs), 4),
        "bootstrap_95": [round(percentile(means, 0.025), 4), round(percentile(means, 0.975), 4)],
        "left_mean": round(sum(left[task] for task in tasks) / len(tasks), 4),
        "right_mean": round(sum(right[task] for task in tasks) / len(tasks), 4),
        "left_wins": sum(1 for diff in diffs if diff > 0),
        "ties": sum(1 for diff in diffs if diff == 0),
        "right_wins": sum(1 for diff in diffs if diff < 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    q3 = _load(Q3)
    pooled = _load(POOLED)
    pooled_free = _load(POOLED_FREE)
    c_rate = task_rates(q3, "c_e2e")
    d_archived = task_rates(q3, "d_new_e2e")
    d_pooled = task_rates(pooled, "answered")
    # per_case rows have funnel, not answered; derive e2e from funnel.
    d_pooled = {
        task: sum(1 for row in pooled if (row["region"], row["mode"]) == task and row["funnel"] == "success")
        / max(1, sum(1 for row in pooled if (row["region"], row["mode"]) == task))
        for task, _ in d_pooled.items()
    }
    d_pooled_free = {
        task: sum(1 for row in pooled_free if (row["region"], row["mode"]) == task and row["funnel"] == "success")
        / max(1, sum(1 for row in pooled_free if (row["region"], row["mode"]) == task))
        for task, _ in d_pooled.items()
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "TASK_CLUSTER_BOOTSTRAP_DEV",
        "iterations": 4000,
        "conditions": {
            "C_legacy": "legacy C report/status",
            "D_archived": "D on the C run's own archived docs",
            "D_pooled": "D on all archived docs for the region",
            "D_pooled_free": "D on pooled archived + autonomous free-web hits",
        },
        "comparisons": {
            "D_pooled_minus_C": paired_bootstrap(d_pooled, c_rate),
            "D_archived_minus_C": paired_bootstrap(d_archived, c_rate),
            "D_pooled_free_minus_C": paired_bootstrap(d_pooled_free, c_rate),
            "D_pooled_minus_D_archived": paired_bootstrap(d_pooled, d_archived),
            "D_pooled_free_minus_D_pooled": paired_bootstrap(d_pooled_free, d_pooled),
        },
        "task_rates": {
            "C": {f"{a}|{b}": value for (a, b), value in sorted(c_rate.items())},
            "D_archived": {f"{a}|{b}": value for (a, b), value in sorted(d_archived.items())},
            "D_pooled": {f"{a}|{b}": value for (a, b), value in sorted(d_pooled.items())},
        },
        "caveats": [
            "18 task clusters, dev replay only; not a sealed holdout.",
            "Task-level E2E is the mean of correlated facts within the task.",
            "Bootstrap over tasks; small n means intervals are wide.",
            "No paid provider or judge calls.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# Q7 task-clustered bootstrap", "", "Tasks: 18 · iterations 4000", ""]
    for name, item in report["comparisons"].items():
        lines.append(
            f"- **{name}**: mean {item.get('mean_difference')} "
            f"(95% {item.get('bootstrap_95')}), "
            f"{item.get('left_wins')} / {item.get('ties')} / {item.get('right_wins')}"
        )
    lines += ["", "## Caveats", ""]
    lines += [f"- {caveat}" for caveat in report["caveats"]]
    lines.append("")
    (args.output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report["comparisons"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
