"""用独立 Claim Verifier 将 VALID 报告转换为声明级 metrics observation。"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.run_independent_judges import JudgeCandidate, collect_judge_candidates

from county_research_ai.config import load_settings
from county_research_ai.evaluation.claim_verification import (
    build_claim_verification_prompt,
    deterministic_claim_check,
    parse_claim_verification,
)
from county_research_ai.evaluation.gate import require_formal_api_gate
from county_research_ai.evaluation.ground_truth import GroundTruthStore
from county_research_ai.evaluation.metrics import MetricsCalculator
from county_research_ai.evaluation.providers import ResourceManagedLLMClient
from county_research_ai.evaluation.resource_manager import ResourceLimit, ResourceManager
from county_research_ai.llm.client import OpenAICompatibleClient

FORMAL_ROOT = Path(__file__).resolve().parents[1] / "experiments" / "independent_comparison"
FORMAL_GATE_PATH = FORMAL_ROOT / "manifests" / "continuation_resource_gate_20261018.json"
CONTINUATION_GROUND_TRUTH_PATH = (
    FORMAL_ROOT / "ground_truth" / "continuation_ground_truth_20261019.jsonl"
)
CONTINUATION_GROUND_TRUTH_MANIFEST_PATH = (
    FORMAL_ROOT / "ground_truth" / "continuation_ground_truth_20261019_manifest.json"
)


def _source_material(candidate: JudgeCandidate) -> str:
    source_path = candidate.run_dir / "sources.json"
    if not source_path.is_file():
        return ""
    return source_path.read_text(encoding="utf-8")[:16000]


def _resource_usage(manager: ResourceManager, run_id: str) -> dict[str, int]:
    usage: dict[str, int] = {}
    for event in manager.snapshot().events:
        if event["run_id"] != run_id or event["status"] == "reserved":
            continue
        key = f"{event['provider']}:{event['model']}:{event['kind']}"
        usage[key] = usage.get(key, 0) + int(event["units"])
    return dict(sorted(usage.items()))


def run_claim_batch(
    *,
    runs_root: Path,
    output_dir: Path,
    batch_id: str,
    max_runs: int | None = None,
    run_id_prefixes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    require_formal_api_gate(FORMAL_GATE_PATH)
    claims = GroundTruthStore.freeze_continuation_verified(
        CONTINUATION_GROUND_TRUTH_PATH,
        CONTINUATION_GROUND_TRUTH_MANIFEST_PATH,
    ).claims
    by_region_task: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for claim in claims:
        by_region_task[(claim.region, claim.research_mode)].append(claim)
    candidates = [
        candidate
        for candidate in collect_judge_candidates(
            runs_root,
            max_runs=max_runs,
            run_id_prefixes=run_id_prefixes,
        )
        if (candidate.county, candidate.task_id) in by_region_task
    ]
    if not candidates:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {"status": "NO_VALID_CLAIM_INPUTS", "runs": 0, "valid_observations": 0}
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return summary

    output_dir.mkdir(parents=True, exist_ok=False)
    settings = load_settings()
    manager = ResourceManager(
        output_dir / "resources.sqlite",
        limits={
            (settings.llm.provider, settings.llm.model, "claim_verifier"): ResourceLimit(
                max(len(candidates) * 16384, 250000),
                billing_class=(
                    "paid_authorized"
                    if settings.llm.provider.lower() == "deepseek"
                    else "free_confirmed"
                ),
            )
        },
    )
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        if not candidate.anonymous_report.text.strip():
            rows.append(
                {
                    "status": "FAILED_EMPTY_REPORT",
                    "run_id": candidate.run_id,
                    "group": candidate.group,
                    "region": candidate.county,
                    "task_id": candidate.task_id,
                    "repeat": candidate.repeat,
                    "duration_seconds": candidate.duration_seconds,
                    "resource_usage": candidate.research_resource_usage or {},
                    "claim_id": None,
                    "claim_count": len(by_region_task[(candidate.county, candidate.task_id)]),
                    "claim_evaluation": None,
                    "metrics": None,
                    "verifier_resource_usage": {},
                    "raw_response": "",
                    "parse_error": "anonymous report is empty",
                }
            )
            continue
        source_material = _source_material(candidate)
        task_claims = by_region_task[(candidate.county, candidate.task_id)]
        evaluations = []
        pending: list[tuple[Any, str]] = []
        for claim in task_claims:
            deterministic = deterministic_claim_check(
                report=candidate.anonymous_report.text,
                source_material=source_material,
                claim=claim,
            )
            if deterministic is not None:
                evaluations.append((claim, deterministic.evaluation, {
                    "reason": deterministic.reason,
                    "checks": deterministic.checks,
                    "verification_method": "deterministic_offline",
                    "raw_response": "",
                    "parse_error": None,
                    "verifier_resource_usage": {},
                }))
            else:
                pending.append((claim, source_material))
        for claim, claim_source in pending:
            verifier_run_id = f"{batch_id}_{candidate.anonymous_report.report_hash}_{claim.claim_id}"
            client = ResourceManagedLLMClient(
                OpenAICompatibleClient(settings=settings),
                manager=manager,
                provider=settings.llm.provider,
                model=settings.llm.model,
                run_id=verifier_run_id,
                artifact_dir=output_dir / "raw_responses" / candidate.run_id / claim.claim_id,
                resource_kind="claim_verifier",
            )
            response = client.chat(
                [{
                    "role": "user",
                    "content": build_claim_verification_prompt(
                        report=candidate.anonymous_report.text,
                        source_material=claim_source,
                        claim=claim,
                    ),
                }],
                max_tokens=1024,
                temperature=0.0,
            )
            evaluation = None
            reason = ""
            parse_error = None
            try:
                evaluation, reason = parse_claim_verification(
                    response.content,
                    claim_id=claim.claim_id,
                )
            except ValueError as exc:
                parse_error = str(exc)
            if evaluation is not None:
                evaluations.append((claim, evaluation, {
                    "reason": reason,
                    "checks": {},
                    "verification_method": "llm_semantic_review",
                    "raw_response": response.content,
                    "parse_error": parse_error,
                    "verifier_resource_usage": _resource_usage(manager, verifier_run_id),
                }))
            else:
                evaluations.append((claim, None, {
                    "reason": reason,
                    "checks": {},
                    "verification_method": "llm_semantic_review",
                    "raw_response": response.content,
                    "parse_error": parse_error,
                    "verifier_resource_usage": _resource_usage(manager, verifier_run_id),
                    "usage_known": client.usage_known,
                }))
        valid_evaluations = [evaluation for _, evaluation, _ in evaluations if evaluation is not None]
        metrics = MetricsCalculator.calculate(
            [claim.claim_id for claim in task_claims], valid_evaluations
        ).to_dict()
        for claim, evaluation, detail in evaluations:
            rows.append(
                {
                    "status": "VALID" if evaluation is not None and detail.get("usage_known", True) else (
                        "INVALID_USAGE_UNKNOWN" if not detail.get("usage_known", True) else "FAILED"
                    ),
                    "run_id": candidate.run_id,
                    "group": candidate.group,
                    "region": candidate.county,
                    "task_id": candidate.task_id,
                    "repeat": candidate.repeat,
                    "duration_seconds": candidate.duration_seconds,
                    "resource_usage": candidate.research_resource_usage or {},
                    "claim_id": claim.claim_id,
                    "claim_evaluation": (
                        {
                            "claim_id": evaluation.claim_id,
                            "status": evaluation.status.value,
                            "evidence_supported": evaluation.evidence_supported,
                            "error_types": list(evaluation.error_types),
                            "reason": detail["reason"],
                            "checks": detail["checks"],
                        }
                        if evaluation is not None
                        else None
                    ),
                    "task_metrics": metrics,
                    "metrics": MetricsCalculator.calculate(
                        [claim.claim_id], [evaluation]
                    ).to_dict() if evaluation is not None else None,
                    "verifier_resource_usage": detail["verifier_resource_usage"],
                    "raw_response": detail["raw_response"],
                    "parse_error": detail["parse_error"],
                    "verification_method": detail["verification_method"],
                }
            )
    (output_dir / "claim_observations.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary = {
        "status": "OK",
        "runs": len(candidates),
        "valid_observations": sum(1 for row in rows if row["status"] == "VALID"),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-id", default="claims_20261018")
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--run-id-prefix", action="append", dest="run_id_prefixes")
    args = parser.parse_args()
    print(
        json.dumps(
            run_claim_batch(
                runs_root=args.runs_root,
                output_dir=args.output_dir,
                batch_id=args.batch_id,
                max_runs=args.max_runs,
                run_id_prefixes=tuple(args.run_id_prefixes or ()),
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
