"""Q1 failure attribution for the frozen Strategy C runs.

Builds a per-claim funnel:

    required fact -> retrieved in raw docs -> extracted as a claim
    -> deterministically supported -> present in the final report

No provider calls. The funnel uses the frozen ground truth as the expected
fact list and the archived raw documents/reports as the system output. A
"candidate false rejection" is reported only when the exact ground-truth
evidence excerpt is present in the matched claim's own span; everything else
is labelled unlabelled/withheld and requires review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from scripts.evaluate_adaptive_retrieval_offline import load_docs
from scripts.evaluate_evidence_verifier_offline import discover_cases

from county_research_ai.evaluation.ground_truth import GroundTruthClaim, GroundTruthStore
from county_research_ai.evidence.graph import (
    EvidenceGraphStore,
    VerificationStatus,
    _quote_contains_value,
    _unit_multiplier,
)
from county_research_ai.evidence.ledger import EvidenceLedger, build_evidence_ledger
from county_research_ai.models import CountyInfo
from county_research_ai.processor import DocumentProcessor

GROUND_TRUTH = Path(
    "experiments/independent_comparison/ground_truth/continuation_ground_truth_20261019.jsonl"
)
RUNS_ROOT = Path(
    "experiments/independent_comparison/runs/"
    "continuation_matched_budget_deepseek_flash_20261019"
)
OUTPUT = Path("experiments/quality/20261026_q3_measure_identity_funnel")

_NUMBER_RE = re.compile(
    r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*(亿元|万元|亿|万|%|‰|亩|万人|人|万吨|万)?"
)
_WS_RE = re.compile(r"\s+")


def norm(text: str) -> str:
    return _WS_RE.sub("", text or "").lower()


def decimal(value: str) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def values_equal(left: str, left_unit: str, right: str, right_unit: str) -> bool:
    left_value, right_value = decimal(left), decimal(right)
    if left_value is None or right_value is None:
        return False
    left_multiplier = _unit_multiplier(left_unit)
    right_multiplier = _unit_multiplier(right_unit)
    if left_multiplier is not None and right_multiplier is not None:
        return left_value * left_multiplier == right_value * right_multiplier
    if left_unit or right_unit:
        return left_value == right_value and left_unit == right_unit
    return left_value == right_value


def numbers_in(text: str, default_unit: str = "") -> list[tuple[str, str]]:
    numbers: list[tuple[str, str]] = []
    for match in _NUMBER_RE.finditer(text or ""):
        raw = match.group(1)
        plain = raw.replace(",", "")
        if re.fullmatch(r"(?:19|20)\d{2}", plain):
            # Calendar years are not metric values; metric_year carries them.
            continue
        unit = match.group(2) or default_unit
        numbers.append((plain, unit))
    return numbers


def metric_tokens(claim: GroundTruthClaim) -> list[str]:
    raw = claim.metric or ""
    tokens = [
        token.strip()
        for token in re.split(r"[（）()/、,，;；\s]+", raw)
        if len(token.strip()) >= 2
    ]
    if claim.claim:
        tokens.append(claim.claim)
    return list(dict.fromkeys(tokens))


def linked_text(claim, ledger: EvidenceLedger) -> str:
    parts = []
    for chunk_id in claim.evidence_chunk_ids:
        chunk = ledger.chunks.get(chunk_id)
        if chunk is not None:
            parts.append(chunk.text)
    return "\n".join(parts)


def match_extracted_claim(
    ground_truth: GroundTruthClaim,
    claims: list,
    ledger: EvidenceLedger,
) -> tuple[Any, int, dict[str, Any]] | None:
    text = ground_truth.expected_answer or ground_truth.claim
    expected_numbers = numbers_in(text, ground_truth.unit)
    primary = expected_numbers[0] if expected_numbers else None
    excerpt = norm(ground_truth.evidence_excerpt)
    tokens = metric_tokens(ground_truth)
    year = ground_truth.metric_year or ""
    best: tuple[Any, int, dict[str, Any]] | None = None
    for claim in claims:
        quotes = linked_text(claim, ledger)
        haystack = f"{quotes}\n{claim.statement}\n{claim.metric_id}"
        score = 0
        details: dict[str, Any] = {
            "excerpt_in_span": bool(excerpt and len(excerpt) >= 8 and excerpt in norm(quotes)),
            "value_match": False,
            "metric_match": False,
            "period_match": False,
        }
        if details["excerpt_in_span"]:
            score += 4
        if primary is not None:
            candidate_value = claim.value
            candidate_unit = claim.unit
            if not candidate_value:
                for found_value, found_unit in numbers_in(claim.statement):
                    if values_equal(found_value, found_unit, primary[0], primary[1]):
                        candidate_value, candidate_unit = found_value, found_unit
                        break
            if candidate_value and values_equal(
                candidate_value, candidate_unit, primary[0], primary[1]
            ):
                details["value_match"] = True
                score += 2
        if any(token and token.lower() in haystack.lower() for token in tokens):
            details["metric_match"] = True
            score += 2
        if year and year in (claim.period or ""):
            details["period_match"] = True
            score += 1
        if ground_truth.region and (
            claim.region_id == ground_truth.region or not claim.region_id
        ):
            score += 1
        period_ok = not year or not claim.period or year in claim.period
        numeric = primary is not None
        accepted = (
            numeric
            and details["value_match"]
            and period_ok
            and (details["excerpt_in_span"] or details["metric_match"])
        ) or (not numeric and details["excerpt_in_span"])
        if accepted and (best is None or score > best[1]):
            best = (claim, score, details)
    return best


def retrieval_for_docs(
    ground_truth: GroundTruthClaim, docs: list
) -> dict[str, Any]:
    excerpt = norm(ground_truth.evidence_excerpt)
    text = ground_truth.expected_answer or ground_truth.claim
    expected_numbers = numbers_in(text, ground_truth.unit)
    primary = expected_numbers[0] if expected_numbers else None
    tokens = metric_tokens(ground_truth)
    for rank, doc in enumerate(docs):
        haystack = norm(f"{doc.title}\n{doc.snippet}\n{doc.content}")
        excerpt_hit = bool(excerpt and len(excerpt) >= 8 and excerpt in haystack)
        value_hit = bool(
            primary
            and _quote_contains_value(
                f"{doc.title}\n{doc.snippet}\n{doc.content}",
                primary[0],
                primary[1],
            )
        )
        metric_hit = any(token and norm(token) in haystack for token in tokens)
        if excerpt_hit or (value_hit and metric_hit):
            return {
                "retrieved": True,
                "rank": rank + 1,
                "excerpt_hit": excerpt_hit,
                "value_metric_hit": value_hit and metric_hit,
            }
    return {
        "retrieved": False,
        "rank": None,
        "excerpt_hit": False,
        "value_metric_hit": False,
    }


def answer_present(ground_truth: GroundTruthClaim, report: str) -> dict[str, Any]:
    text = ground_truth.expected_answer or ground_truth.claim
    expected_numbers = numbers_in(text, ground_truth.unit)
    primary = expected_numbers[0] if expected_numbers else None
    tokens = metric_tokens(ground_truth)
    if primary is not None:
        value_hit = _quote_contains_value(report, primary[0], primary[1])
        metric_hit = any(token and token.lower() in report.lower() for token in tokens)
        return {
            "present": value_hit and metric_hit,
            "value_hit": value_hit,
            "metric_hit": metric_hit,
        }
    expected = norm(ground_truth.expected_answer)
    if expected:
        hit = expected in norm(report)
        return {"present": hit, "value_hit": hit, "metric_hit": hit}
    return {"present": False, "value_hit": False, "metric_hit": False}


def diagnose_run(
    case: dict[str, Any],
    ground_truth_claims: list[GroundTruthClaim],
    graph: EvidenceGraphStore,
) -> dict[str, Any]:
    run_dir = case["raw_docs"].parents[4]
    docs = load_docs(case["raw_docs"])
    processed = DocumentProcessor().process(
        docs,
        county=CountyInfo.from_name(case["region"]),
        focus=case["focus"],
    )
    ledger = build_evidence_ledger(processed)
    graph.save_ledger(ledger, run_id=case["run_id"])
    report_path = run_dir / "report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    claims = list(ledger.claims.values())
    rows = []
    for ground_truth in ground_truth_claims:
        retrieval = retrieval_for_docs(ground_truth, docs)
        matched = match_extracted_claim(ground_truth, claims, ledger)
        answer = answer_present(ground_truth, report)
        extracted = matched is not None
        status = ""
        reason = ""
        exact_evidence = False
        legacy_status = ""
        matched_claim_id = ""
        if matched is not None:
            claim, score, details = matched
            matched_claim_id = claim.claim_id
            legacy_status = claim.verification_status
            stored = graph.get_claim(claim.claim_id)
            status = (stored.verification_status.upper() if stored else "INSUFFICIENT")
            reason = stored.verification_reason if stored else ""
            exact_evidence = details["excerpt_in_span"]
        supported = status == VerificationStatus.SUPPORTED.value
        if not retrieval["retrieved"]:
            funnel = "not_retrieved"
        elif not extracted:
            funnel = "not_extracted"
        elif supported:
            funnel = "success" if answer["present"] else "not_in_answer"
        elif exact_evidence:
            funnel = "withheld_exact_evidence"
        else:
            funnel = "withheld_other"
        rows.append(
            {
                "claim_id": ground_truth.claim_id,
                "metric": ground_truth.metric,
                "value": numbers_in(
                    ground_truth.expected_answer or ground_truth.claim,
                    ground_truth.unit,
                )[:1],
                "metric_year": ground_truth.metric_year,
                "region": ground_truth.region,
                "retrieval": retrieval,
                "extracted": extracted,
                "matched_claim_id": matched_claim_id,
                "match_score": matched[1] if matched else 0,
                "match_details": matched[2] if matched else {},
                "legacy_status": legacy_status,
                "verification_status": status,
                "verification_reason": reason,
                "exact_evidence_in_span": exact_evidence,
                "answer": answer,
                "funnel": funnel,
            }
        )
    return {
        "run_id": case["run_id"],
        "region": case["region"],
        "mode": case["mode"],
        "documents": len(docs),
        "extracted_claims": len(claims),
        "report_chars": len(report),
        "ground_truth_claims": len(ground_truth_claims),
        "rows": rows,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    funnel = Counter(row["funnel"] for row in rows)
    retrieved = sum(1 for row in rows if row["retrieval"]["retrieved"])
    extracted = sum(1 for row in rows if row["extracted"])
    supported = sum(
        1 for row in rows if row["verification_status"] == "SUPPORTED"
    )
    answered = sum(1 for row in rows if row["answer"]["present"])
    ranks = [
        row["retrieval"]["rank"]
        for row in rows
        if row["retrieval"]["rank"] is not None
    ]
    reciprocal = [1.0 / rank for rank in ranks]
    return {
        "claims": total,
        "retrieved": retrieved,
        "retrieval_rate": round(retrieved / total, 4) if total else 0.0,
        "recall_at_1": round(sum(1 for rank in ranks if rank <= 1) / total, 4)
        if total
        else 0.0,
        "recall_at_3": round(sum(1 for rank in ranks if rank <= 3) / total, 4)
        if total
        else 0.0,
        "recall_at_5": round(sum(1 for rank in ranks if rank <= 5) / total, 4)
        if total
        else 0.0,
        "mrr": round(sum(reciprocal) / total, 4) if total else 0.0,
        "extracted": extracted,
        "extraction_recall": round(extracted / total, 4) if total else 0.0,
        "supported": supported,
        "support_rate_among_extracted": round(supported / extracted, 4)
        if extracted
        else 0.0,
        "answered": answered,
        "answer_rate": round(answered / total, 4) if total else 0.0,
        "end_to_end": funnel.get("success", 0),
        "end_to_end_rate": round(funnel.get("success", 0) / total, 4)
        if total
        else 0.0,
        "funnel": dict(sorted(funnel.items())),
        "withheld_exact_evidence": funnel.get("withheld_exact_evidence", 0),
        "withheld_other": funnel.get("withheld_other", 0),
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
    results = []
    all_rows = []
    with_graph = None
    import tempfile

    with tempfile.TemporaryDirectory(prefix="q1-funnel-") as tmp:
        with_graph = EvidenceGraphStore(Path(tmp) / "graph.sqlite")
        for case in cases:
            task_claims = grouped.get((case["region"], case["mode"]), [])
            if not task_claims:
                continue
            run = diagnose_run(case, task_claims, with_graph)
            results.append(run)
            all_rows.extend(run["rows"])

    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in results:
        by_mode[run["mode"]].extend(run["rows"])
        by_region[run["region"]].extend(run["rows"])

    run_table = [
        {
            "run_id": run["run_id"],
            "region": run["region"],
            "mode": run["mode"],
            "documents": run["documents"],
            "extracted_claims": run["extracted_claims"],
            **summarize(run["rows"]),
        }
        for run in results
    ]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "OFFLINE_STAGE_DIAGNOSIS",
        "provider_calls": 0,
        "ground_truth_sha256": hashlib.sha256(
            GROUND_TRUTH.read_bytes()
        ).hexdigest(),
        "runs_root": str(args.runs_root),
        "runs": run_table,
        "overall": summarize(all_rows),
        "by_mode": {mode: summarize(rows) for mode, rows in sorted(by_mode.items())},
        "by_region": {
            region: summarize(rows) for region, rows in sorted(by_region.items())
        },
        "caveats": [
            "Retrieval uses archived raw documents only; it is a retrieval-set coverage proxy, not a live search benchmark.",
            "Extraction matching is deterministic and GT-anchored; unmatched claims are not automatically wrong.",
            "A withheld claim is labelled a candidate false rejection only when the exact GT excerpt is in its own span; all others need review.",
            "No semantic judge or human labels were used.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "run_diagnostics.jsonl").write_text(
        "\n".join(json.dumps(run, ensure_ascii=False) for run in results) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Q1 Quality Funnel — Strategy C",
        "",
        f"Generated: {report['generated_at']}",
        "Evidence: offline archived docs/reports; provider calls 0.",
        "",
        "| Run | Docs | Claims | Retrieval | Extraction | Supported | Answered | E2E |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in run_table:
        lines.append(
            f"| {row['region']} {row['mode']} | {row['documents']} | "
            f"{row['extracted_claims']} | {row['retrieval_rate']:.3f} | "
            f"{row['extraction_recall']:.3f} | {row['support_rate_among_extracted']:.3f} | "
            f"{row['answer_rate']:.3f} | {row['end_to_end_rate']:.3f} |"
        )
    overall = report["overall"]
    lines += [
        "",
        "## Overall",
        "",
        f"- Claims: {overall['claims']}",
        f"- Retrieved: {overall['retrieved']} ({overall['retrieval_rate']:.1%})",
        f"- Recall@1/3/5: {overall['recall_at_1']:.3f} / {overall['recall_at_3']:.3f} / {overall['recall_at_5']:.3f}; MRR {overall['mrr']:.3f}",
        f"- Extracted: {overall['extracted']} ({overall['extraction_recall']:.1%})",
        f"- Supported among extracted: {overall['supported']} ({overall['support_rate_among_extracted']:.1%})",
        f"- Answered: {overall['answered']} ({overall['answer_rate']:.1%})",
        f"- End-to-end: {overall['end_to_end']} ({overall['end_to_end_rate']:.1%})",
        f"- Funnel: `{overall['funnel']}`",
        "",
        "## Caveats",
        "",
    ]
    lines += [f"- {caveat}" for caveat in report["caveats"]]
    lines.append("")
    (args.output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(overall, ensure_ascii=False, indent=2))
    print(f"wrote {args.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
