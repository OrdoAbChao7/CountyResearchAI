"""Audit continuation benchmark inputs, run manifests, and resource settlement."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.run_continuation_experiment import (
    GROUND_TRUTH_MANIFEST_PATH,
    GROUND_TRUTH_PATH,
    validate_continuation_benchmark,
)

from county_research_ai.evaluation.ground_truth import GroundTruthStore


def audit_batch(batch_root: Path) -> dict[str, Any]:
    batch_root = Path(batch_root).resolve()
    summary_path = batch_root / "summary.json"
    batch_manifest_path = batch_root / "batch_manifest.json"
    if not summary_path.is_file() or not batch_manifest_path.is_file():
        raise ValueError(f"continuation batch manifest or summary is missing: {batch_root}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    batch_manifest = json.loads(batch_manifest_path.read_text(encoding="utf-8"))
    benchmark = validate_continuation_benchmark()
    frozen = GroundTruthStore.freeze_continuation_verified(
        GROUND_TRUTH_PATH,
        GROUND_TRUTH_MANIFEST_PATH,
    )
    frozen_task_keys = {(claim.region, claim.research_mode) for claim in frozen.claims}
    planned = list(batch_manifest.get("planned_runs", []))
    manifests = sorted(batch_root.glob("*/manifest.json"))
    rows: list[dict[str, Any]] = []
    for path in manifests:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(payload)
        if payload.get("formal_target") is not True:
            raise ValueError(f"continuation run is not formal_target: {path}")
        if payload.get("task_id") not in {"snapshot", "rise-fall", "long-history"}:
            raise ValueError(f"continuation run has unknown task: {path}")
    statuses = Counter(str(row.get("status")) for row in rows)
    task_mismatches = [
        {
            "run_id": row.get("run_id"),
            "region": row.get("county"),
            "task_id": row.get("task_id"),
        }
        for row in rows
        if (row.get("county"), row.get("task_id")) not in frozen_task_keys
    ]
    planned_set = set(planned)
    actual_set = {str(row.get("run_id")) for row in rows}
    missing = sorted(planned_set - actual_set)
    recorded_resource_db = Path(batch_manifest.get("resource_db", ""))
    resource_db, resource_path_source = _resolve_recorded_path(
        recorded_resource_db,
        search_dir=batch_root.parent,
        repo_root=batch_root.parents[3],
    )
    resource = _audit_resource_db(
        resource_db,
        recorded_path=recorded_resource_db,
        path_source=resource_path_source,
    )
    failed_rows = [
        {
            "run_id": row.get("run_id"),
            "status": row.get("status"),
            "error": row.get("error"),
            "resource_usage": row.get("resource_usage", {}),
        }
        for row in rows
        if row.get("status") != "VALID"
    ]
    audit_status = "VALID_BATCH" if not missing and not failed_rows else "DATASET_AND_RESOURCE_AUDITED"
    return {
        "status": audit_status,
        "batch_id": batch_manifest.get("batch_id"),
        "benchmark": benchmark,
        "source_hash_verified": frozen.source_hash == benchmark["source_hash"],
        "task_matching": {
            "status": "PASS" if not task_mismatches else "FAIL",
            "frozen_task_keys": len(frozen_task_keys),
            "run_task_mismatches": task_mismatches,
        },
        "planned_runs": len(planned),
        "manifest_runs": len(rows),
        "statuses": dict(sorted(statuses.items())),
        "missing_runs": missing,
        "failed_runs": failed_rows,
        "resource": resource,
        "summary_status": summary.get("status"),
    }


def _resolve_recorded_path(
    recorded: Path,
    *,
    search_dir: Path,
    repo_root: Path,
) -> tuple[Path, str]:
    """Resolve a path stored in a frozen manifest against the current checkout.

    Committed experiment manifests record absolute paths from the machine that
    produced them. When the repository is relocated or renamed those absolute
    paths no longer exist even though the artifact is present. Resolve in order:
    as recorded, relative to the current checkout, then by matching the
    ``experiments/...`` suffix or the bare file name inside the current runs
    directory. The returned source label keeps the audit honest about which
    path was used.
    """
    recorded = Path(recorded)
    if recorded.is_file():
        return recorded.resolve(), "recorded"
    if not recorded.is_absolute():
        candidate = (Path.cwd() / recorded).resolve()
        if candidate.is_file():
            return candidate, "relative_to_cwd"
    parts = recorded.parts
    for index, part in enumerate(parts):
        if part.lower() == "experiments":
            candidate = (repo_root / Path(*parts[index:])).resolve()
            if candidate.is_file():
                return candidate, "relocated_repo_relative"
    candidate = (search_dir / recorded.name).resolve()
    if candidate.is_file():
        return candidate, "relocated_by_name"
    return recorded, "missing"


def _audit_resource_db(
    path: Path,
    *,
    recorded_path: Path | None = None,
    path_source: str = "recorded",
) -> dict[str, Any]:
    if not path.is_file():
        return {
            "status": "MISSING",
            "path": str(path),
            "recorded_path": str(recorded_path) if recorded_path is not None else str(path),
            "path_source": "missing",
        }
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT status, COUNT(*), COALESCE(SUM(consumed_units),0) FROM leases GROUP BY status"
        ).fetchall()
        limits = connection.execute(
            "SELECT provider, model, kind, capacity_units, billing_class "
            "FROM resource_limits ORDER BY provider, model, kind"
        ).fetchall()
    finally:
        connection.close()
    by_status = {
        str(status): {"leases": int(count), "consumed_units": int(units)}
        for status, count, units in rows
    }
    active = int(by_status.get("reserved", {}).get("leases", 0))
    result = {
        "status": "CLOSED" if active == 0 else "ACTIVE_LEASES",
        "path": str(path),
        "path_source": path_source,
        "by_status": by_status,
        "active_leases": active,
        "limits": {
            f"{provider}|{model}|{kind}": {
                "capacity_units": int(capacity_units),
                "billing_class": str(billing_class),
            }
            for provider, model, kind, capacity_units, billing_class in limits
        },
    }
    if recorded_path is not None and Path(recorded_path) != path:
        result["recorded_path"] = str(recorded_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_batch(args.batch_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
