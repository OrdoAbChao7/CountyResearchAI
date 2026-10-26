"""Review withheld and supported claims from the frozen C corpus.

No provider or judge calls. This does not assert that a withheld claim is a
false rejection; it classifies the *relationship* between the claim and its
conflicting counterparts so the coarse-identity hypothesis can be tested.

Outputs:
  summary.json          counts by mode/region and conflict relationship
  samples.jsonl         up to 40 withheld + 30 supported samples for review
  summary.md            human-readable summary
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.evaluate_adaptive_retrieval_offline import load_docs
from scripts.evaluate_evidence_verifier_offline import discover_cases

from county_research_ai.evidence.graph import EvidenceGraphStore, VerificationStatus
from county_research_ai.evidence.ledger import build_evidence_ledger
from county_research_ai.models import CountyInfo
from county_research_ai.processor import DocumentProcessor

RUNS_ROOT = Path(
    "experiments/independent_comparison/runs/"
    "continuation_matched_budget_deepseek_flash_20261019"
)
OUTPUT = Path("experiments/quality/20261026_q1_withheld_review")
_WS = re.compile(r"\s+")
_NON_MEASURE = re.compile(r"[\d.,%‰（）()亿元万元万亿亩人年增减为是的了]")


def norm(text: str) -> str:
    return _WS.sub("", text or "").lower()


def measure_key(statement: str) -> str:
    """Strip numbers/units/particles to compare the stated measure."""
    return _NON_MEASURE.sub("", norm(statement))


def classify_claim(
    claim,
    conflicts: list,
) -> dict[str, Any]:
    claim_key = measure_key(claim.statement)
    relationships = Counter()
    for other in conflicts:
        other_key = measure_key(other.statement)
        if other_key == claim_key:
            relationships["same_measure_statement"] += 1
        elif norm(other.statement) == norm(claim.statement):
            relationships["identical_statement"] += 1
        else:
            relationships["different_measure_statement"] += 1
    if not conflicts:
        category = "no_supported_conflict"
    elif relationships.get("same_measure_statement") or relationships.get(
        "identical_statement"
    ):
        category = "same_measure_value_conflict"
    else:
        category = "different_measure_grouped_conflict"
    return {
        "category": category,
        "relationships": dict(relationships),
        "conflict_count": len(conflicts),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    cases = discover_cases(args.runs_root)
    withheld: list[dict[str, Any]] = []
    supported: list[dict[str, Any]] = []
    by_mode: dict[str, Counter] = defaultdict(Counter)
    by_region: dict[str, Counter] = defaultdict(Counter)
    with tempfile.TemporaryDirectory(prefix="q1-withheld-") as tmp:
        graph = EvidenceGraphStore(Path(tmp) / "graph.sqlite")
        for case in cases:
            docs = load_docs(case["raw_docs"])
            processed = DocumentProcessor().process(
                docs,
                county=CountyInfo.from_name(case["region"]),
                focus=case["focus"],
            )
            ledger = build_evidence_ledger(processed)
            graph.save_ledger(ledger, run_id=case["run_id"])
            supported_ids = {
                claim_id
                for claim_id, claim in ledger.claims.items()
                if EvidenceGraphStore._ledger_objective_support(claim, ledger)
            }
            for claim in ledger.claims.values():
                chain = graph.get_chain(claim.claim_id, run_id=case["run_id"])
                status = (
                    chain.verification.status
                    if chain.verification is not None
                    else VerificationStatus.INSUFFICIENT
                )
                reason = chain.verification.reason if chain.verification else ""
                if status is VerificationStatus.SUPPORTED:
                    if claim.statement and not any(
                        norm(claim.statement) in norm(link.span.quote)
                        for link in chain.links
                    ):
                        supported.append(
                            {
                                "run_id": case["run_id"],
                                "region": case["region"],
                                "mode": case["mode"],
                                "claim_id": claim.claim_id,
                                "statement": claim.statement,
                                "metric": claim.metric_id,
                                "value_unit": f"{claim.value}{claim.unit}",
                                "period": claim.period,
                                "quote": chain.links[0].span.quote[:500]
                                if chain.links
                                else "",
                                "reason": "supported_by_metric_only",
                            }
                        )
                    continue
                if status is not VerificationStatus.NEEDS_REVIEW:
                    continue
                conflicts = []
                for relation in chain.relations:
                    if relation.relation.value != "contradicts":
                        continue
                    other_id = (
                        relation.to_claim_id
                        if relation.from_claim_id == claim.claim_id
                        else relation.from_claim_id
                    )
                    other = ledger.claims.get(other_id)
                    if other is None or other_id not in supported_ids:
                        continue
                    conflicts.append(other)
                classification = classify_claim(claim, conflicts)
                row = {
                    "run_id": case["run_id"],
                    "region": case["region"],
                    "mode": case["mode"],
                    "claim_id": claim.claim_id,
                    "statement": claim.statement,
                    "metric": claim.metric_id,
                    "value_unit": f"{claim.value}{claim.unit}",
                    "period": claim.period,
                    "scope": claim.administrative_scope,
                    "caliber": claim.statistical_caliber,
                    "status": status.value,
                    "reason": reason,
                    "quote": chain.links[0].span.quote[:500]
                    if chain.links
                    else "",
                    **classification,
                    "conflicts": [
                        {
                            "statement": other.statement,
                            "metric": other.metric_id,
                            "value_unit": f"{other.value}{other.unit}",
                            "period": other.period,
                        }
                        for other in conflicts[:4]
                    ],
                }
                withheld.append(row)
                by_mode[case["mode"]][classification["category"]] += 1
                by_region[case["region"]][classification["category"]] += 1
    categories = Counter(row["category"] for row in withheld)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "OFFLINE_WITHHELD_REVIEW",
        "provider_calls": 0,
        "runs": len(cases),
        "withheld_needs_review": len(withheld),
        "categories": dict(sorted(categories.items())),
        "conflict_count_distribution": dict(
            sorted(Counter(row["conflict_count"] for row in withheld).items())
        ),
        "by_mode": {mode: dict(counter) for mode, counter in sorted(by_mode.items())},
        "by_region": {
            region: dict(counter) for region, counter in sorted(by_region.items())
        },
        "supported_by_metric_only": len(supported),
        "supported_sample_size": min(len(supported), 30),
        "notes": [
            "different_measure_grouped_conflict means the conflicting claims share "
            "region/metric/period/scope/caliber identity but state different "
            "measures; this is a coarse-identity grouping problem, not proof of a "
            "false rejection in every case.",
            "supported_by_metric_only lists SUPPORTED claims whose exact statement "
            "was not found in the quote (metric-only support); these are candidates "
            "for false support, not confirmed errors.",
            "No human labels or semantic judge were used.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in withheld[:40]:
            handle.write(json.dumps({"kind": "withheld", **row}, ensure_ascii=False) + "\n")
        for row in supported[:30]:
            handle.write(json.dumps({"kind": "supported", **row}, ensure_ascii=False) + "\n")
    lines = [
        "# Q1 withheld-claim review",
        "",
        f"Generated: {report['generated_at']} · provider calls 0",
        "",
        f"- Withheld `NEEDS_REVIEW`: {len(withheld)}",
        f"- Categories: `{report['categories']}`",
        f"- Conflict-count distribution: `{report['conflict_count_distribution']}`",
        f"- Supported but statement not in quote: {len(supported)}",
        "",
        "## By mode",
        "",
    ]
    for mode, counts in report["by_mode"].items():
        lines.append(f"- {mode}: `{counts}`")
    lines += ["", "## Notes", ""]
    lines += [f"- {note}" for note in report["notes"]]
    lines.append("")
    (args.output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report["categories"], ensure_ascii=False, indent=2))
    print(json.dumps(report["conflict_count_distribution"], ensure_ascii=False))
    print(
        json.dumps(
            {"withheld": len(withheld), "supported_metric_only": len(supported)},
            ensure_ascii=False,
        )
    )
    print(f"wrote {args.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
