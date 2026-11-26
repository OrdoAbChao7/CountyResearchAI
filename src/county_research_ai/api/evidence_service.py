"""Bridge legacy application evidence into the persistent graph and findings."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from ..domain.research_contracts import EvidencePack, ResearchContract
from ..evidence.graph import (
    EvidenceGraphStore,
    EvidenceLink,
    FindingRecord,
    VerificationStatus,
    VerifiedFinding,
)
from ..evidence.ledger import EvidenceLedger
from ..evidence.source_identity import source_groups
from ..search.disambiguation import disambiguate_region, matches_explicit_parents
from ..search.request_history import SearchExecution
from .contract_coverage import ContractCoverage, assess_contract_coverage
from .jobs import JobRecord


def persist_run_evidence(
    graph: EvidenceGraphStore,
    ledger: EvidenceLedger,
    packs: list[EvidencePack],
    *,
    run_id: str,
    contract: ResearchContract | None = None,
    executions: list[SearchExecution] | None = None,
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
    findings: list[VerifiedFinding] = []
    # A Claim is stored once per run, yet every question whose pack selected it stays linked.
    slots_by_claim: dict[str, list[str]] = {}
    for pack in packs:
        for claim in pack.selected_claims:
            linked = slots_by_claim.setdefault(claim.claim_id, [])
            if pack.slot_id not in linked:
                linked.append(pack.slot_id)
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
            finding = FindingRecord(
                finding_id=f"{run_id}:{claim.claim_id}",
                run_id=run_id,
                claim_id=claim.claim_id,
                section=pack.slot_id,
                slot_ids=slots_by_claim[claim.claim_id],
                text=claim.statement,
                status=status,
            )
            findings.append(VerifiedFinding(finding=finding, chain=chain))
    coverage = None
    verifications = []
    if contract is not None and contract.required_questions:
        coverage = assess_contract_coverage(contract, graph, findings, run_id=run_id, executions=executions)
        adjusted = coverage.apply_verdicts(findings)
        verifications = [
            item.chain.verification for item, original in zip(adjusted, findings, strict=True)
            if item is not original and item.chain.verification is not None
        ]
        findings = adjusted
    graph.save_findings(run_id, [item.finding for item in findings], verifications=verifications)

    status_counts = Counter(item.finding.status.value for item in findings)
    supported = status_counts.get(VerificationStatus.SUPPORTED.value, 0)
    groups = source_groups(
        link.snapshot for item in findings
        if item.finding.status is VerificationStatus.SUPPORTED
        for link in graph.supporting_links(item.chain)
    )
    total = len(findings)
    summary: dict[str, Any] = {
        "claims": total,
        "supported_claims": supported,
        "independent_sources": len(groups),
        "source_groups": groups,
        "supported_ratio": round(supported / total, 4) if total else 0.0,
        "status_counts": dict(sorted(status_counts.items())),
        "snapshots": len(ledger.sources),
        "spans": len(ledger.chunks),
    }
    if coverage is not None:
        summary["contract_questions"] = [question.model_dump() for question in coverage.questions]
        summary["contract_evidence"] = coverage.evidence_summary()
    return summary


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


@dataclass
class RunEvidence:
    findings: list[VerifiedFinding]
    coverage: ContractCoverage
    citation_links: dict[str, EvidenceLink]


def load_run_evidence(graph: EvidenceGraphStore, job: JobRecord) -> RunEvidence:
    """Recheck supporting links and apply the contract consistently on reads."""
    region = disambiguate_region(job.contract.regions[0])
    findings = []
    citation_links = {}
    date_window = job.contract.date_window
    window = (date_window.start, date_window.end) if date_window.is_set else None
    for original in graph.list_findings(
        job.job_id, recheck_legacy=True, window=window, target_region=region.clean_name,
    ):
        item = original
        chain = item.chain
        intact = list(graph.intact_links(chain))
        if len(intact) != len(chain.links):
            item = item.model_copy(update={"chain": chain.model_copy(update={"links": intact})})
        if item.finding.status is VerificationStatus.SUPPORTED:
            record = chain.verification
            if record is not None and record.status is not VerificationStatus.SUPPORTED:
                item = item.with_verification_status(record.status, record.reason)
            else:
                support = next((link for link in graph.supporting_links(item.chain)
                                if matches_explicit_parents(region, link.snapshot.title)), None) if record else None
                if support is None:
                    reason = "false_or_broken_reference" if not intact else "no_verified_supporting_span"
                    if record and any(
                        matches_explicit_parents(region, link.snapshot.title)
                        for link in graph.supporting_links(item.chain, require_credible_source=False)
                    ):
                        reason = "insufficient_source_credibility"
                    item = item.with_verification_status(VerificationStatus.INSUFFICIENT, reason)
                else:
                    citation_links[chain.claim.claim_id] = support
        if item.chain.claim.verification_reason == "insufficient_source_credibility":
            candidate = next((
                link for link in graph.supporting_links(item.chain, require_credible_source=False)
                if matches_explicit_parents(region, link.snapshot.title)
            ), None)
            if candidate is not None:
                citation_links[chain.claim.claim_id] = candidate
        findings.append(item)
    stored = (job.result.get("evidence") or {}).get("contract_questions") or []
    executions = [
        SearchExecution.model_validate(entry)
        for question in stored for entry in question.get("query_executions") or []
    ] if any(question.get("query_executions") is not None for question in stored) else None
    coverage = assess_contract_coverage(
        job.contract, graph, findings, run_id=job.job_id, executions=executions,
    )
    return RunEvidence(
        findings=coverage.apply_verdicts(findings), coverage=coverage,
        citation_links=citation_links | coverage.citation_links,
    )
