"""Build a stratified verifier audit sample from the frozen C claims.

The sample is for independent review. Labels are NOT generated here; the file
ships with empty label fields. Use `scripts/summarize_verifier_audit.py` after
labels are filled. A labeler must be recorded explicitly; model/assistant labels
must not be described as human ground truth.
"""
from __future__ import annotations

import argparse
import json
import random
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
OUTPUT = Path("experiments/quality/20261026_q7_verifier_audit")
TARGETS = {
    VerificationStatus.SUPPORTED.value: 10,
    VerificationStatus.NEEDS_REVIEW.value: 10,
    VerificationStatus.NOT_COMPARABLE.value: 5,
    VerificationStatus.INSUFFICIENT.value: 5,
    VerificationStatus.OUTDATED.value: 5,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261026)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    cases = discover_cases(RUNS_ROOT)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with tempfile.TemporaryDirectory(prefix="q7-audit-") as tmp:
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
            for claim in ledger.claims.values():
                chain = graph.get_chain(claim.claim_id, run_id=case["run_id"])
                status = (
                    chain.verification.status.value
                    if chain.verification is not None
                    else VerificationStatus.INSUFFICIENT.value
                )
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
                    if other is not None:
                        conflicts.append(
                            {
                                "statement": other.statement,
                                "measure": other.measure_id or other.metric_id,
                                "value_unit": f"{other.value}{other.unit}",
                            }
                        )
                buckets[status].append(
                    {
                        "run_id": case["run_id"],
                        "region": case["region"],
                        "mode": case["mode"],
                        "claim_id": claim.claim_id,
                        "statement": claim.statement,
                        "metric": claim.metric_id,
                        "measure": claim.measure_id,
                        "value_unit": f"{claim.value}{claim.unit}",
                        "period": claim.period,
                        "scope": claim.administrative_scope,
                        "caliber": claim.statistical_caliber,
                        "status": status,
                        "reason": chain.verification.reason if chain.verification else "",
                        "quote": chain.links[0].span.quote[:800] if chain.links else "",
                        "source_url": chain.links[0].snapshot.canonical_url
                        if chain.links
                        else "",
                        "conflicts": conflicts[:4],
                        "label": "",
                        "label_rationale": "",
                        "labeler": "",
                    }
                )
    rng = random.Random(args.seed)
    sample: list[dict[str, Any]] = []
    for status, target in TARGETS.items():
        items = sorted(buckets.get(status, []), key=lambda item: item["claim_id"])
        rng.shuffle(items)
        sample.extend(items[:target])
    sample.sort(key=lambda item: (item["status"], item["claim_id"]))
    for index, row in enumerate(sample, start=1):
        row["sample_index"] = index
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "audit_sample.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in sample) + "\n",
        encoding="utf-8",
    )
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "frame_counts": dict(sorted(Counter(
            status for status, items in buckets.items() for _ in items
        ).items())),
        "sample_counts": dict(sorted(Counter(row["status"] for row in sample).items())),
        "sample_size": len(sample),
        "runs": len(cases),
        "note": (
            "Labels are empty. Fill label='correct' or 'incorrect', "
            "label_rationale, and labeler (e.g. assistant_manual_review or a "
            "human name). Do not present assistant labels as human ground truth."
        ),
    }
    (args.output / "sample_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
