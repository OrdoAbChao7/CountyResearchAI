"""Bridge legacy application evidence into the persistent graph and findings."""
from __future__ import annotations

from collections import Counter
from typing import Any

from ..domain.research_contracts import EvidencePack, ResearchContract
from ..evidence.graph import (
    EvidenceGraphStore,
    FindingRecord,
    VerificationStatus,
    VerifiedFinding,
)
from ..evidence.ledger import EvidenceLedger
from ..evidence.source_identity import source_groups
from ..search.disambiguation import disambiguate_region


def persist_run_evidence(
    graph: EvidenceGraphStore,
    ledger: EvidenceLedger,
    packs: list[EvidencePack],
    *,
    run_id: str,
    contract: ResearchContract | None = None,
) -> dict[str, Any]:
    """Persist the run graph and structured findings, then summarize support."""
    window = None
    target_region = ""
    if contract is not None and contract.date_window.is_set:
        window = (contract.date_window.start, contract.date_window.end)
    if contract is not None and contract.regions:
        target_region = disambiguate_region(contract.regions[0]).clean_name
    graph.save_ledger(
        ledger,
        run_id=run_id,
        window=window,
        target_region=target_region,
    )
    findings: list[FindingRecord] = []
    seen: set[str] = set()
    for pack in packs:
        for claim in pack.selected_claims:
            if claim.claim_id in seen:
                continue
            seen.add(claim.claim_id)
            chain = graph.get_chain(claim.claim_id, run_id=run_id)
            status = (
                chain.verification.status
                if chain.verification is not None
                else VerificationStatus.INSUFFICIENT
            )
            findings.append(
                FindingRecord(
                    finding_id=f"{run_id}:{claim.claim_id}",
                    run_id=run_id,
                    claim_id=claim.claim_id,
                    section=pack.slot_id,
                    text=claim.statement,
                    status=status,
                )
            )
    graph.save_findings(run_id, findings)

    status_counts = Counter(finding.status.value for finding in findings)
    supported = status_counts.get(VerificationStatus.SUPPORTED.value, 0)
    sources = [source for finding in findings
               if finding.status is VerificationStatus.SUPPORTED
               for source in graph.supporting_sources(finding.claim_id, run_id=run_id)]
    groups = source_groups(sources)
    total = len(findings)
    return {
        "claims": total,
        "supported_claims": supported,
        "independent_sources": len(groups),
        "source_groups": groups,
        "supported_ratio": round(supported / total, 4) if total else 0.0,
        "status_counts": dict(sorted(status_counts.items())),
        "snapshots": len(ledger.sources),
        "spans": len(ledger.chunks),
    }


def thresholds_met(contract: ResearchContract, summary: dict[str, Any]) -> tuple[bool, list[str]]:
    thresholds = contract.evidence_thresholds
    failures: list[str] = []
    if summary.get("independent_sources", 0) < thresholds.min_independent_sources:
        failures.append(
            "min_independent_sources:"
            f"{summary.get('independent_sources', 0)}<{thresholds.min_independent_sources}"
        )
    if summary.get("supported_claims", 0) < thresholds.min_supported_claims:
        failures.append(
            "min_supported_claims:"
            f"{summary.get('supported_claims', 0)}<{thresholds.min_supported_claims}"
        )
    ratio = float(summary.get("supported_ratio", 0.0))
    if ratio < thresholds.min_supported_ratio:
        failures.append(
            f"min_supported_ratio:{ratio}<{thresholds.min_supported_ratio}"
        )
    return (not failures, failures)


def load_findings(
    graph: EvidenceGraphStore, run_id: str
) -> list[VerifiedFinding]:
    return graph.list_findings(run_id)
