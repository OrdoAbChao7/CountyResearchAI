"""Offline Strategy D evaluation on the frozen dev-replay corpus.

Conditions:
  C_legacy_report   legacy C report + legacy claim status
  D_old_grouping    extractive answer from verified claims, coarse identity
  D_measure_aware   extractive answer, context-aware measure identity

D answers are deterministic extracts of SUPPORTED findings; no LLM or provider
call is involved. The blind pilot is not read here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from scripts.diagnose_quality_funnel import (
    GROUND_TRUTH,
    answer_present,
    match_extracted_claim,
    retrieval_for_docs,
)
from scripts.evaluate_adaptive_retrieval_offline import load_docs
from scripts.evaluate_evidence_verifier_offline import discover_cases

from county_research_ai.application.verified_answer import build_verified_answer
from county_research_ai.evaluation.ground_truth import GroundTruthClaim, GroundTruthStore
from county_research_ai.evidence.graph import EvidenceGraphStore, VerificationStatus
from county_research_ai.evidence.ledger import build_evidence_ledger
from county_research_ai.models import CountyInfo
from county_research_ai.processor import DocumentProcessor

RUNS_ROOT = Path(
    "experiments/independent_comparison/runs/"
    "continuation_matched_budget_deepseek_flash_20261019"
)
OUTPUT = Path("experiments/quality/20261026_q3_strategy_d")


def task_window(claims: list[GroundTruthClaim]) -> tuple[date | None, date | None] | None:
    years = sorted(
        int(claim.metric_year)
        for claim in claims
        if str(claim.metric_year).isdigit() and len(str(claim.metric_year)) == 4
    )
    if not years:
        return None
    return (date(years[0], 1, 1), date(years[-1], 12, 31))


def run_window_status(graph: EvidenceGraphStore, run_id: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for claim in graph.list_run_claims(run_id):
        chain = graph.get_chain(claim.claim_id, run_id=run_id)
        status = (
            chain.verification.status
            if chain.verification is not None
            else VerificationStatus.INSUFFICIENT
        )
        counts[status.value] += 1
    return counts


def _status(graph: EvidenceGraphStore, claim_id: str, run_id: str) -> str:
    if not claim_id:
        return ""
    chain = graph.get_chain(claim_id, run_id=run_id)
    return (
        chain.verification.status.value
        if chain.verification is not None
        else VerificationStatus.INSUFFICIENT.value
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if not total:
        return {"claims": 0}
    def rate(key: str) -> float:
        return round(sum(1 for row in rows if row[key]) / total, 4)
    return {
        "claims": total,
        "retrieved": sum(1 for row in rows if row["retrieved"]),
        "retrieval_rate": rate("retrieved"),
        "c_legacy_verified": sum(1 for row in rows if row["c_legacy_verified"]),
        "c_answered": sum(1 for row in rows if row["c_answer"]),
        "c_e2e": rate("c_e2e"),
        "d_old_supported": sum(1 for row in rows if row["d_old_supported"]),
        "d_old_answered": sum(1 for row in rows if row["d_old_answer"]),
        "d_old_e2e": rate("d_old_e2e"),
        "d_new_supported": sum(1 for row in rows if row["d_new_supported"]),
        "d_new_answered": sum(1 for row in rows if row["d_new_answer"]),
        "d_new_e2e": rate("d_new_e2e"),
        "d_new_funnel": dict(
            sorted(Counter(row["d_new_funnel"] for row in rows).items())
        ),
        "nv_answered": sum(1 for row in rows if row["nv_answer"]),
        "nv_answer_rate": rate("nv_answer"),
        "nv_unsupported_included": sum(
            {
                row["case_id"]: row["nv_unsupported_included"]
                for row in rows
            }.values()
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    claims = GroundTruthStore.load(GROUND_TRUTH)
    grouped: dict[tuple[str, str], list[GroundTruthClaim]] = defaultdict(list)
    for claim in claims:
        grouped[(claim.region, claim.research_mode)].append(claim)
    cases = discover_cases(args.runs_root)
    rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    withheld_counts: dict[str, Counter[str]] = {}
    with tempfile.TemporaryDirectory(prefix="q3-d-") as tmp:
        graph = EvidenceGraphStore(Path(tmp) / "graph.sqlite")
        for case in cases:
            task_claims = grouped.get((case["region"], case["mode"]), [])
            if not task_claims:
                continue
            docs = load_docs(case["raw_docs"])
            processed = DocumentProcessor().process(
                docs,
                county=CountyInfo.from_name(case["region"]),
                focus=case["focus"],
            )
            ledger = build_evidence_ledger(processed)
            window = task_window(task_claims)
            run_new = f"{case['run_id']}_Dnew"
            run_old = f"{case['run_id']}_Dold"
            graph.save_ledger(
                ledger,
                run_id=run_new,
                window=window,
                use_measure_identity=True,
            )
            graph.save_ledger(
                ledger,
                run_id=run_old,
                window=window,
                use_measure_identity=False,
            )
            answer_new = build_verified_answer(graph, run_new)
            answer_old = build_verified_answer(graph, run_old)
            no_verifier_lines: list[str] = []
            unsupported_included = 0
            for claim in ledger.claims.values():
                chain = graph.get_chain(claim.claim_id, run_id=run_new)
                status = (
                    chain.verification.status
                    if chain.verification is not None
                    else VerificationStatus.INSUFFICIENT
                )
                if status is not VerificationStatus.SUPPORTED:
                    unsupported_included += 1
                no_verifier_lines.append(
                    f"- {claim.measure_id or claim.metric_id}: {claim.statement}"
                )
            no_verifier_text = "\n".join(no_verifier_lines)
            withheld_counts[case["mode"]] = run_window_status(graph, run_new)
            run_dir = case["raw_docs"].parents[4]
            report_path = run_dir / "report.md"
            report = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
            case_funnel = Counter()
            for ground_truth in task_claims:
                retrieval = retrieval_for_docs(ground_truth, docs)
                matched = match_extracted_claim(ground_truth, list(ledger.claims.values()), ledger)
                claim_id = matched[0].claim_id if matched else ""
                legacy_status = matched[0].verification_status if matched else ""
                status_new = _status(graph, claim_id, run_new)
                status_old = _status(graph, claim_id, run_old)
                c_answer = answer_present(ground_truth, report)
                d_new_answer = answer_present(ground_truth, answer_new["text"])
                d_old_answer = answer_present(ground_truth, answer_old["text"])
                nv_answer = answer_present(ground_truth, no_verifier_text)
                d_new_supported = status_new == VerificationStatus.SUPPORTED.value
                d_old_supported = status_old == VerificationStatus.SUPPORTED.value
                if not retrieval["retrieved"]:
                    funnel = "not_retrieved"
                elif not matched:
                    funnel = "not_extracted"
                elif not d_new_supported:
                    funnel = "not_supported"
                elif not d_new_answer["present"]:
                    funnel = "not_in_answer"
                else:
                    funnel = "success"
                case_funnel[funnel] += 1
                row = {
                    "case_id": case["run_id"],
                    "region": case["region"],
                    "mode": case["mode"],
                    "claim_id": ground_truth.claim_id,
                    "metric": ground_truth.metric,
                    "retrieved": retrieval["retrieved"],
                    "matched_claim_id": claim_id,
                    "c_legacy_status": legacy_status,
                    "c_legacy_verified": legacy_status == "verified",
                    "c_answer": c_answer["present"],
                    "c_e2e": legacy_status == "verified" and c_answer["present"],
                    "d_old_status": status_old,
                    "d_old_supported": d_old_supported,
                    "d_old_answer": d_old_answer["present"],
                    "d_old_e2e": d_old_supported and d_old_answer["present"],
                    "d_new_status": status_new,
                    "d_new_supported": d_new_supported,
                    "d_new_answer": d_new_answer["present"],
                    "d_new_e2e": d_new_supported and d_new_answer["present"],
                    "nv_answer": nv_answer["present"],
                    "nv_e2e": nv_answer["present"],
                    "nv_unsupported_included": unsupported_included,
                    "d_new_funnel": funnel,
                }
                rows.append(row)
            case_rows.append(
                {
                    "run_id": case["run_id"],
                    "region": case["region"],
                    "mode": case["mode"],
                    "claims": len(task_claims),
                    "documents": len(docs),
                    "extracted_claims": len(ledger.claims),
                    "d_new_supported_total": answer_new["supported_count"],
                    "d_old_supported_total": answer_old["supported_count"],
                    "d_new_status_counts": answer_new["status_counts"],
                    "d_old_status_counts": answer_old["status_counts"],
                    "funnel": dict(case_funnel),
                }
            )
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_mode[row["mode"]].append(row)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "OFFLINE_STRATEGY_D",
        "provider_calls": 0,
        "ground_truth_sha256": hashlib.sha256(
            GROUND_TRUTH.read_bytes()
        ).hexdigest(),
        "conditions": {
            "C_legacy_report": "legacy C report and legacy claim status",
            "D_old_grouping": "verified extractive answer, measure identity disabled",
            "D_measure_aware": "verified extractive answer, context-aware measure identity",
            "D_no_verifier": "extractive answer over all extracted claims (precision-risk upper bound)",
        },
        "overall": summarize(rows),
        "by_mode": {mode: summarize(items) for mode, items in sorted(by_mode.items())},
        "withheld_by_mode": {
            mode: dict(counts) for mode, counts in sorted(withheld_counts.items())
        },
        "cases": case_rows,
        "caveats": [
            "D answers are deterministic extracts, not fluent reports; this measures fact coverage, not prose quality.",
            "Retrieval is fixed to the archived documents; D cannot recover facts the collector never fetched.",
            "Dev replay only; the blind pilot was not read and cannot be used for tuning.",
            "No provider or semantic judge was used.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "per_case.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    (args.output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Strategy D offline evaluation",
        "",
        f"Generated: {report['generated_at']} · provider calls 0",
        "",
        "| Condition | Retrieved | Supported | Answered | E2E |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    overall = report["overall"]
    lines.append(
        f"| C legacy report | {overall['retrieved']} | "
        f"{overall['c_legacy_verified']} | {overall['c_answered']} | "
        f"{overall['c_e2e']:.3f} |"
    )
    lines.append(
        f"| D old grouping | {overall['retrieved']} | "
        f"{overall['d_old_supported']} | {overall['d_old_answered']} | "
        f"{overall['d_old_e2e']:.3f} |"
    )
    lines.append(
        f"| D measure-aware | {overall['retrieved']} | "
        f"{overall['d_new_supported']} | {overall['d_new_answered']} | "
        f"{overall['d_new_e2e']:.3f} |"
    )
    lines.append(
        f"| D no verifier | {overall['retrieved']} | "
        f"— ({overall['nv_unsupported_included']} unsupported included) | "
        f"{overall['nv_answered']} | {overall['nv_answer_rate']:.3f}* |"
    )
    lines += [
        "",
        "*No-verifier answer coverage is not comparable to verified E2E: it includes "
        "unsupported statements and is shown as a precision-risk upper bound.",
    ]
    lines += ["", "## D measure-aware funnel", "", f"`{overall['d_new_funnel']}`", ""]
    lines += ["## Caveats", ""]
    lines += [f"- {caveat}" for caveat in report["caveats"]]
    lines.append("")
    (args.output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report["overall"], ensure_ascii=False, indent=2))
    print(f"wrote {args.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
