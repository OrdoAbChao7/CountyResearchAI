"""Summarize independent verifier audit labels into a confusion matrix."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("experiments/quality/20261026_q7_verifier_audit")
SUPPORTED = "SUPPORTED"
REJECTED = {"INSUFFICIENT", "NEEDS_REVIEW", "NOT_COMPARABLE", "OUTDATED"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    sample = [
        json.loads(line)
        for line in (args.root / "audit_sample.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    labels = {
        int(row["sample_index"]): row
        for row in (
            json.loads(line)
            for line in (args.root / "audit_labels.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    missing = [row["sample_index"] for row in sample if row["sample_index"] not in labels]
    if missing:
        raise SystemExit(f"missing labels for sample indexes: {missing}")
    rows = []
    for row in sample:
        label = labels[row["sample_index"]]
        if label.get("label") not in {"correct", "incorrect"}:
            raise SystemExit(f"invalid label at {row['sample_index']}")
        rows.append({**row, **label})

    matrix: dict[str, Counter[str]] = {}
    error_types: Counter[str] = Counter()
    labelers: Counter[str] = Counter()
    for row in rows:
        matrix.setdefault(row["status"], Counter())[row["label"]] += 1
        labelers[row.get("labeler", "")] += 1
        if row["label"] == "incorrect":
            error_types[row.get("error_type", "unspecified")] += 1

    supported = [row for row in rows if row["status"] == SUPPORTED]
    rejected = [row for row in rows if row["status"] in REJECTED]
    fs_bad = sum(1 for row in supported if row["label"] == "incorrect")
    fr_bad = sum(1 for row in rejected if row["label"] == "incorrect")
    human = any("assistant" not in (labeler or "").lower() for labeler in labelers)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "INDEPENDENT_SAMPLE_AUDIT",
        "sample_size": len(rows),
        "labelers": dict(labelers),
        "human_ground_truth": human,
        "human_annotation_status": "PRESENT" if human else "BLOCKED_HUMAN_ANNOTATION",
        "confusion_matrix": {
            status: dict(counts) for status, counts in sorted(matrix.items())
        },
        "false_support": {
            "sample": len(supported),
            "incorrect": fs_bad,
            "rate": round(fs_bad / len(supported), 4) if supported else None,
            "wilson_95": wilson(fs_bad, len(supported)),
        },
        "false_rejection": {
            "sample": len(rejected),
            "incorrect": fr_bad,
            "rate": round(fr_bad / len(rejected), 4) if rejected else None,
            "wilson_95": wilson(fr_bad, len(rejected)),
        },
        "error_types": dict(sorted(error_types.items())),
        "caveats": [
            "Labels are assistant manual review, not human ground truth.",
            "Stratified sample (10 SUPPORTED, 15 rejected); not population-weighted.",
            "Rates describe this sample and do not estimate the full claim population.",
            "The sample frame had no OUTDATED or NOT_COMPARABLE claims.",
        ],
    }
    (args.root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Verifier audit",
        "",
        f"Sample: {len(rows)} · labelers: {dict(labelers)}",
        f"Human ground truth: {summary['human_ground_truth']}",
        "",
        "| Status | correct | incorrect |",
        "| --- | ---: | ---: |",
    ]
    for status, counts in summary["confusion_matrix"].items():
        lines.append(f"| {status} | {counts.get('correct', 0)} | {counts.get('incorrect', 0)} |")
    lines += [
        "",
        f"- False support: {fs_bad}/{len(supported)} = {summary['false_support']['rate']} "
        f"(Wilson {summary['false_support']['wilson_95']})",
        f"- False rejection: {fr_bad}/{len(rejected)} = {summary['false_rejection']['rate']} "
        f"(Wilson {summary['false_rejection']['wilson_95']})",
        f"- Error types: `{summary['error_types']}`",
        "",
        "## Caveats",
        "",
    ]
    lines += [f"- {caveat}" for caveat in summary["caveats"]]
    lines.append("")
    (args.root / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
