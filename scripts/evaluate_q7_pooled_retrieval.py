"""Q7 pooled-archive retrieval evaluation for Strategy D.

Builds a per-region corpus from every archived raw_docs.json (deduped by URL +
content hash), then runs the same measure-aware verified answer and GT funnel.
This is OFFLINE CORPUS POOLING, not live search; no provider calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.diagnose_quality_funnel import (
    GROUND_TRUTH,
    answer_present,
    match_extracted_claim,
    retrieval_for_docs,
)
from scripts.evaluate_adaptive_retrieval_offline import load_docs
from scripts.evaluate_strategy_d_offline import task_window

from county_research_ai.application.verified_answer import build_verified_answer
from county_research_ai.evaluation.ground_truth import GroundTruthClaim, GroundTruthStore
from county_research_ai.evidence.graph import EvidenceGraphStore, VerificationStatus
from county_research_ai.evidence.ledger import build_evidence_ledger
from county_research_ai.models import CountyInfo, RawDoc
from county_research_ai.processor import DocumentProcessor

OUTPUT = Path("experiments/quality/20261026_q7_pooled_eval")


def free_web_docs(
    log_path: Path, snapshot_dir: Path
) -> dict[str, list[RawDoc]]:
    by_region: dict[str, list[RawDoc]] = defaultdict(list)
    if not log_path.is_file():
        return {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not row.get("recovered") or not row.get("best"):
            continue
        best = row["best"]
        snapshot_path = snapshot_dir / f"{best.get('content_hash', '')}.json"
        if not snapshot_path.is_file():
            continue
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        by_region[str(row["region"])].append(
            RawDoc(
                title=str(best.get("title", "")),
                url=str(best.get("url", "")),
                content=str(snapshot.get("text", "")),
                snippet="",
                source="q7_public_web",
                metadata={"q7_query": best.get("query", "")},
            )
        )
    return dict(by_region)


def corpus_by_region() -> dict[str, list]:
    by_region: dict[str, list] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    for root in Path("experiments").rglob("raw_docs.json"):
        parts = root.parts
        if "raw" not in parts:
            continue
        index = parts.index("raw")
        if index + 1 >= len(parts):
            continue
        region = parts[index + 1]
        try:
            docs = load_docs(root)
        except Exception:  # noqa: BLE001
            continue
        for doc in docs:
            content = doc.content or doc.snippet
            key = hashlib.sha256(f"{doc.url}\n{content}".encode()).hexdigest()
            if key in seen[region]:
                continue
            seen[region].add(key)
            by_region[region].append(doc)
    return dict(by_region)


def _status(graph: EvidenceGraphStore, claim_id: str, run_id: str) -> str:
    if not claim_id:
        return ""
    chain = graph.get_chain(claim_id, run_id=run_id)
    return (
        chain.verification.status.value
        if chain.verification is not None
        else VerificationStatus.INSUFFICIENT.value
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--include-free-web", action="store_true")
    parser.add_argument(
        "--free-log",
        type=Path,
        default=Path(
            "experiments/quality/20261026_q7_retrieval/retrieval_long-history.jsonl"
        ),
    )
    parser.add_argument(
        "--free-snapshots",
        type=Path,
        default=Path("experiments/quality/20261026_q7_retrieval/snapshots"),
    )
    args = parser.parse_args()
    claims = GroundTruthStore.load(GROUND_TRUTH)
    grouped: dict[tuple[str, str], list[GroundTruthClaim]] = defaultdict(list)
    for claim in claims:
        grouped[(claim.region, claim.research_mode)].append(claim)
    corpus = corpus_by_region()
    free_counts: dict[str, int] = {}
    if args.include_free_web:
        for region, extra_docs in free_web_docs(args.free_log, args.free_snapshots).items():
            existing = {
                hashlib.sha256(
                    f"{doc.url}\n{doc.content or doc.snippet}".encode()
                ).hexdigest()
                for doc in corpus.get(region, [])
            }
            added = 0
            for doc in extra_docs:
                key = hashlib.sha256(
                    f"{doc.url}\n{doc.content or doc.snippet}".encode()
                ).hexdigest()
                if key in existing:
                    continue
                existing.add(key)
                corpus.setdefault(region, []).append(doc)
                added += 1
            if added:
                free_counts[region] = added
    rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="q7-pool-") as tmp:
        graph = EvidenceGraphStore(Path(tmp) / "graph.sqlite")
        for (region, mode), task_claims in sorted(grouped.items()):
            docs = corpus.get(region, [])
            if not docs:
                continue
            processed = DocumentProcessor().process(
                docs,
                county=CountyInfo.from_name(region),
                focus=task_claims[0].metric or "产业",
            )
            ledger = build_evidence_ledger(processed)
            run_id = f"pool:{region}:{mode}"
            graph.save_ledger(ledger, run_id=run_id, window=task_window(task_claims))
            answer = build_verified_answer(graph, run_id)
            funnel = Counter()
            for ground_truth in task_claims:
                retrieval = retrieval_for_docs(ground_truth, docs)
                matched = match_extracted_claim(
                    ground_truth, list(ledger.claims.values()), ledger
                )
                claim_id = matched[0].claim_id if matched else ""
                status = _status(graph, claim_id, run_id)
                supported = status == VerificationStatus.SUPPORTED.value
                answered = answer_present(ground_truth, answer["text"])["present"]
                if not retrieval["retrieved"]:
                    label = "not_retrieved"
                elif not matched:
                    label = "not_extracted"
                elif not supported:
                    label = "not_supported"
                elif not answered:
                    label = "not_in_answer"
                else:
                    label = "success"
                funnel[label] += 1
                rows.append(
                    {
                        "region": region,
                        "mode": mode,
                        "claim_id": ground_truth.claim_id,
                        "retrieved": retrieval["retrieved"],
                        "extracted": bool(matched),
                        "status": status,
                        "answered": answered,
                        "funnel": label,
                    }
                )
            case_rows.append(
                {
                    "region": region,
                    "mode": mode,
                    "documents": len(docs),
                    "extracted_claims": len(ledger.claims),
                    "supported_claims": answer["supported_count"],
                    "funnel": dict(funnel),
                }
            )
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_mode[row["mode"]].append(row)

    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(items)
        return {
            "claims": total,
            "retrieved": sum(1 for row in items if row["retrieved"]),
            "retrieval_rate": round(sum(1 for row in items if row["retrieved"]) / total, 4)
            if total
            else 0.0,
            "extracted": sum(1 for row in items if row["extracted"]),
            "supported": sum(1 for row in items if row["status"] == "SUPPORTED"),
            "answered": sum(1 for row in items if row["answered"]),
            "e2e": sum(1 for row in items if row["funnel"] == "success"),
            "e2e_rate": round(
                sum(1 for row in items if row["funnel"] == "success") / total, 4
            )
            if total
            else 0.0,
            "funnel": dict(sorted(Counter(row["funnel"] for row in items).items())),
        }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "OFFLINE_CORPUS_POOL",
        "provider_calls": 0,
        "corpus_documents": {region: len(docs) for region, docs in sorted(corpus.items())},
        "free_web_added_documents": free_counts,
        "overall": summarize(rows),
        "by_mode": {mode: summarize(items) for mode, items in sorted(by_mode.items())},
        "cases": case_rows,
        "baselines": {
            "q3_d_archived_e2e": 15,
            "q3_c_legacy_e2e": 3,
            "note": "from experiments/quality/20261026_q3_strategy_d/summary.json",
        },
        "caveats": [
            "Offline archived corpus pooling, not live retrieval.",
            "Different runs may contain duplicated or superseded sources; verification window applies.",
            "No provider or judge calls.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "per_case.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Q7 pooled-archive retrieval",
        "",
        f"Generated: {report['generated_at']} · provider calls 0",
        "",
        f"Corpus: `{report['corpus_documents']}`",
        "",
        f"- Retrieved: {report['overall']['retrieved']}/{report['overall']['claims']}",
        f"- Extracted: {report['overall']['extracted']}",
        f"- Supported: {report['overall']['supported']}",
        f"- Answered: {report['overall']['answered']}",
        f"- E2E: {report['overall']['e2e']}/{report['overall']['claims']} "
        f"({report['overall']['e2e_rate']:.1%})",
        f"- Funnel: `{report['overall']['funnel']}`",
        "",
        "| Mode | Retrieved | Extracted | Supported | E2E |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for mode, item in report["by_mode"].items():
        lines.append(
            f"| {mode} | {item['retrieved']}/{item['claims']} | {item['extracted']} | "
            f"{item['supported']} | {item['e2e']}/{item['claims']} |"
        )
    lines += ["", "## Caveats", ""]
    lines += [f"- {caveat}" for caveat in report["caveats"]]
    lines.append("")
    (args.output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report["overall"], ensure_ascii=False, indent=2))
    print(json.dumps(report["by_mode"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
