"""Re-score frozen experiment reports without Provider or semantic Judge calls."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.run_independent_judges import JudgeCandidate, collect_judge_candidates

from county_research_ai.evaluation.claim_verification import deterministic_claim_check
from county_research_ai.evaluation.ground_truth import GroundTruthClaim, GroundTruthStore
from county_research_ai.evaluation.metrics import ClaimEvaluation, ClaimStatus, MetricsCalculator
from county_research_ai.evidence.source_contract import serialize_source_documents
from county_research_ai.models import RawDoc

FORMAL_ROOT = Path(__file__).resolve().parents[1] / "experiments" / "independent_comparison"
CONTINUATION_GROUND_TRUTH_PATH = (
    FORMAL_ROOT / "ground_truth" / "continuation_ground_truth_20261019.jsonl"
)
CONTINUATION_GROUND_TRUTH_MANIFEST_PATH = (
    FORMAL_ROOT / "ground_truth" / "continuation_ground_truth_20261019_manifest.json"
)


def _raw_source_contract(run_dir: Path) -> str:
    raw_paths = sorted(run_dir.glob("data/raw/**/raw_docs.json"))
    documents: list[RawDoc] = []
    for raw_path in raw_paths:
        try:
            values = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if not isinstance(values, list):
            continue
        documents.extend(RawDoc(**value) for value in values if isinstance(value, dict))
    if not documents:
        return ""
    return json.dumps(serialize_source_documents(documents), ensure_ascii=False, sort_keys=True)


def source_material_for_offline_rescore(candidate: JudgeCandidate) -> tuple[str, str]:
    """Load source text, rebuilding a contract from saved RawDocs when necessary."""
    source_path = candidate.run_dir / "sources.json"
    if not source_path.is_file():
        return "", "missing_source_archive"
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", "invalid_source_archive"
    if isinstance(payload, list) and any(
        isinstance(item, dict) and item.get("content") for item in payload
    ):
        return json.dumps(payload, ensure_ascii=False, sort_keys=True), "archived_source_contract"
    rebuilt = _raw_source_contract(candidate.run_dir)
    if rebuilt:
        return rebuilt, "rebuilt_from_saved_raw_docs"
    return source_path.read_text(encoding="utf-8"), "metadata_only_source_archive"


def _baseline_index(path: Path | None) -> dict[tuple[str, str], dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        rows[(str(value.get("run_id", "")), str(value.get("claim_id", "")))] = value
    return rows


def _claims_by_region_task(claims: list[GroundTruthClaim]) -> dict[tuple[str, str], list[GroundTruthClaim]]:
    grouped: dict[tuple[str, str], list[GroundTruthClaim]] = defaultdict(list)
    for claim in claims:
        grouped[(claim.region, claim.research_mode)].append(claim)
    return grouped


def _offline_evaluation(
    *, report: str, source_material: str, claim: GroundTruthClaim
) -> tuple[ClaimEvaluation, dict[str, Any]]:
    checked = deterministic_claim_check(
        report=report,
        source_material=source_material,
        claim=claim,
    )
    if checked is None:
        return (
            ClaimEvaluation(
                claim_id=claim.claim_id,
                status=ClaimStatus.UNVERIFIED,
                error_types=("offline_semantic_pending",),
            ),
            {
                "reason": "该 Claim 没有足够结构化字段，离线重评分不调用 semantic Judge。",
                "checks": {},
                "verification_method": "offline_deterministic_only",
                "source_material_status": "loaded",
            },
        )
    return (
        checked.evaluation,
        {
            "reason": checked.reason,
            "checks": checked.checks,
            "verification_method": "offline_deterministic_only",
            "source_material_status": "loaded",
        },
    )


def run_offline_claim_batch(
    *,
    runs_root: Path,
    output_dir: Path,
    batch_id: str,
    baseline_path: Path | None = None,
    max_runs: int | None = None,
    run_id_prefixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    claims = GroundTruthStore.freeze_continuation_verified(
        CONTINUATION_GROUND_TRUTH_PATH,
        CONTINUATION_GROUND_TRUTH_MANIFEST_PATH,
    ).claims
    by_region_task = _claims_by_region_task(claims)
    candidates = [
        candidate
        for candidate in collect_judge_candidates(
            runs_root,
            max_runs=max_runs,
            run_id_prefixes=run_id_prefixes or None,
        )
        if (candidate.county, candidate.task_id) in by_region_task
    ]
    output_dir.mkdir(parents=True, exist_ok=False)
    baseline = _baseline_index(baseline_path)
    rows: list[dict[str, Any]] = []
    source_status_counts: Counter[str] = Counter()
    change_counts: Counter[str] = Counter()
    for candidate in candidates:
        source_material, source_status = source_material_for_offline_rescore(candidate)
        source_status_counts[source_status] += 1
        task_claims = by_region_task[(candidate.county, candidate.task_id)]
        evaluations: list[ClaimEvaluation] = []
        details: dict[str, dict[str, Any]] = {}
        for claim in task_claims:
            evaluation, detail = _offline_evaluation(
                report=candidate.anonymous_report.text,
                source_material=source_material,
                claim=claim,
            )
            evaluations.append(evaluation)
            details[claim.claim_id] = detail
        task_metrics = MetricsCalculator.calculate(
            [claim.claim_id for claim in task_claims], evaluations
        ).to_dict()
        for claim, evaluation in zip(task_claims, evaluations, strict=True):
            key = (candidate.run_id, claim.claim_id)
            previous = baseline.get(key, {})
            previous_evaluation = previous.get("claim_evaluation") or {}
            previous_status = str(previous_evaluation.get("status", ""))
            changed = previous_status != evaluation.status.value
            change_reason = "unchanged"
            if changed:
                if details[claim.claim_id]["source_material_status"] == "loaded":
                    change_reason = "offline_contract_or_comparison_rule_changed"
                else:
                    change_reason = "offline_comparison_rule_changed"
                change_counts[f"{previous_status or 'MISSING'}->{evaluation.status.value}"] += 1
            detail = details[claim.claim_id]
            rows.append(
                {
                    "rescore_version": batch_id,
                    "status": "VALID_OFFLINE",
                    "run_id": candidate.run_id,
                    "group": candidate.group,
                    "region": candidate.county,
                    "task_id": candidate.task_id,
                    "repeat": candidate.repeat,
                    "duration_seconds": candidate.duration_seconds,
                    "resource_usage": candidate.research_resource_usage or {},
                    "claim_id": claim.claim_id,
                    "claim_evaluation": {
                        "claim_id": evaluation.claim_id,
                        "status": evaluation.status.value,
                        "evidence_supported": evaluation.evidence_supported,
                        "error_types": list(evaluation.error_types),
                        "reason": detail["reason"],
                        "checks": detail["checks"],
                    },
                    "task_metrics": task_metrics,
                    "metrics": MetricsCalculator.calculate(
                        [claim.claim_id], [evaluation]
                    ).to_dict(),
                    "verification_method": detail["verification_method"],
                    "source_material_status": source_status,
                    "baseline_status": previous_status or None,
                    "classification_changed": changed,
                    "classification_change_reason": change_reason,
                    "provider_calls": 0,
                }
            )
    output_dir.joinpath("claim_observations.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary = {
        "status": "OK_OFFLINE",
        "rescore_version": batch_id,
        "runs": len(candidates),
        "valid_observations": len(rows),
        "provider_calls": 0,
        "source_material_status_counts": dict(sorted(source_status_counts.items())),
        "classification_changes": sum(change_counts.values()),
        "classification_change_counts": dict(sorted(change_counts.items())),
        "baseline_path": str(baseline_path) if baseline_path else None,
    }
    output_dir.joinpath("summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output_dir.joinpath("rescore_manifest.json").write_text(
        json.dumps(
            {
                "status": "FROZEN_OFFLINE_RESCORE",
                "rescore_version": batch_id,
                "ground_truth": str(CONTINUATION_GROUND_TRUTH_PATH),
                "runs_root": str(runs_root),
                "baseline_claim_observations": str(baseline_path) if baseline_path else None,
                "provider_calls": 0,
                "semantic_judge_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--batch-id", default="continuation_offline_rescore_v4")
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--run-id-prefix", action="append", dest="run_id_prefixes")
    args = parser.parse_args()
    print(
        json.dumps(
            run_offline_claim_batch(
                runs_root=args.runs_root,
                output_dir=args.output_dir,
                batch_id=args.batch_id,
                baseline_path=args.baseline,
                max_runs=args.max_runs,
                run_id_prefixes=tuple(args.run_id_prefixes or ()),
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
