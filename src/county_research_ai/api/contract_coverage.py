"""Measure each required question against the run's verified evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from ..domain.question_targets import QuestionTarget, question_target
from ..domain.research_contracts import QuestionSlot, ResearchContract
from ..evidence.graph import (
    ClaimChain,
    EvidenceGraphStore,
    EvidenceLink,
    VerificationStatus,
    VerifiedFinding,
)
from ..evidence.source_identity import source_groups
from ..search.request_history import SearchExecution
from .enterprise_leads import EnterpriseLead, collect_enterprise_leads

_QuestionStatus = Literal["SUPPORTED", "INSUFFICIENT", "NEEDS_REVIEW", "CONFLICT_UNRESOLVED"]
_SCOPE_REJECTIONS = {"provisional_or_nonfactual", "partial_statistics_scope", "source_region_mismatch"}


class QuestionEvidence(BaseModel):
    claim_id: str
    statement: str
    period: str
    status: Literal["SUPPORTED", "DISPUTED", "REJECTED"]
    reason: str
    snapshot_id: str = ""
    span_id: str = ""
    title: str = ""
    url: str = ""


class ContractQuestionResult(BaseModel):
    question_id: str
    question: str
    status: _QuestionStatus
    claim_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    missing_metrics: list[str] = Field(default_factory=list)
    candidates: list[QuestionEvidence] = Field(default_factory=list)
    # Named-company display aid for enterprise questions. Never a qualification verdict.
    enterprise_leads: list[EnterpriseLead] = Field(default_factory=list)
    query_executions: list[SearchExecution] | None = None


@dataclass
class ContractCoverage:
    questions: list[ContractQuestionResult] = field(default_factory=list)
    relevant_claim_ids: set[str] = field(default_factory=set)
    answer_links: dict[str, list[EvidenceLink]] = field(default_factory=dict)
    conflicts: dict[str, set[str]] = field(default_factory=dict)
    withheld: dict[str, str] = field(default_factory=dict)

    def apply_verdicts(self, findings: list[VerifiedFinding]) -> list[VerifiedFinding]:
        adjusted = []
        for original in findings:
            item = original
            claim_id = item.finding.claim_id
            verification = item.chain.verification
            peers = self.conflicts.get(claim_id)
            if peers and verification is not None:
                checks = dict(verification.deterministic_checks)
                checks["contradicting_supported_claims"] = sorted(
                    set(checks.get("contradicting_supported_claims") or ()) | peers
                )
                item = item.with_verification_status(
                    VerificationStatus.NEEDS_REVIEW, "conflicting_contract_evidence", checks=checks,
                )
            elif claim_id in self.withheld and claim_id not in self.answer_links:
                item = item.with_verification_status(VerificationStatus.INSUFFICIENT, self.withheld[claim_id])
            adjusted.append(item)
        return adjusted

    @property
    def citation_links(self) -> dict[str, EvidenceLink]:
        return {claim_id: links[0] for claim_id, links in self.answer_links.items()}

    def evidence_summary(self) -> dict[str, int | float]:
        supported_ids = {
            claim_id for question in self.questions if question.status == "SUPPORTED"
            for claim_id in question.claim_ids
        }
        groups = source_groups(
            link.snapshot for claim_id in sorted(supported_ids) for link in self.answer_links[claim_id]
        )
        total = len(self.relevant_claim_ids)
        return {
            "supported_claims": len(supported_ids),
            "independent_sources": len(groups),
            "supported_ratio": round(len(supported_ids) / total, 4) if total else 0.0,
        }


def _candidate(
    chain: ClaimChain, reason: str, *, link: EvidenceLink | None = None,
    status: Literal["SUPPORTED", "DISPUTED", "REJECTED"] = "REJECTED",
) -> QuestionEvidence:
    return QuestionEvidence(
        claim_id=chain.claim.claim_id, statement=chain.claim.statement, period=chain.claim.period,
        status=status, reason=reason,
        snapshot_id=link.snapshot.snapshot_id if link else "", span_id=link.span.span_id if link else "",
        title=link.snapshot.title if link else "", url=link.snapshot.canonical_url if link else "",
    )


def _related_to_target(chain: ClaimChain, target: QuestionTarget) -> bool:
    return target.label in "".join(chain.claim.statement.split())


def _answer_links(
    item: VerifiedFinding, target: QuestionTarget, graph: EvidenceGraphStore,
) -> tuple[list[EvidenceLink], EvidenceLink | None, str]:
    chain = item.chain
    context = next(graph.intact_links(chain), None)
    verification = chain.verification
    if verification is None or verification.status is not item.finding.status:
        return [], context, chain.claim.verification_reason or "verification_missing"
    if verification.status not in (VerificationStatus.NEEDS_REVIEW, VerificationStatus.SUPPORTED):
        if verification.reason == "insufficient_source_credibility":
            context = next(graph.supporting_links(chain, require_credible_source=False), context)
        return [], context, verification.reason or verification.status.value
    links: list[EvidenceLink] = []
    rejection = "no_verified_supporting_span"
    rejected_link = None
    for link in graph.supporting_links(chain):
        issue = target.quote_issue(
            chain.claim, link.span.quote, title=link.snapshot.title, content=link.snapshot.content,
        )
        if not issue:
            links.append(link)
        elif rejected_link is None or issue in _SCOPE_REJECTIONS:
            rejection, rejected_link = issue, link
    return links, rejected_link or context, rejection


def _assess_question(
    slot: QuestionSlot, target: QuestionTarget, coverage: ContractCoverage,
    graph: EvidenceGraphStore, findings: list[VerifiedFinding], unselected: list[ClaimChain],
    result: ContractQuestionResult, *, run_id: str = "",
) -> None:
    supported: list[str] = []
    disputed: list[str] = []
    comparable_amounts: dict[tuple[str, str, str, str], dict[Decimal, set[str]]] = {}
    for item in findings:
        chain = item.chain
        claim = chain.claim
        # A Claim is stored once; every slot that selected it evaluates it on its own terms.
        if not _related_to_target(chain, target) and slot.slot_id not in item.finding.linked_slot_ids():
            continue
        issue = target.claim_issue(slot, claim)
        if issue:
            result.candidates.append(_candidate(chain, issue, link=next(graph.intact_links(chain), None)))
            continue
        coverage.relevant_claim_ids.add(claim.claim_id)
        links, context, reason = _answer_links(item, target, graph)
        if not links:
            if reason in _SCOPE_REJECTIONS:
                coverage.withheld[claim.claim_id] = reason
            result.candidates.append(_candidate(chain, reason, link=context))
            continue
        coverage.answer_links[claim.claim_id] = links
        is_disputed = item.finding.status is VerificationStatus.NEEDS_REVIEW
        (disputed if is_disputed else supported).append(claim.claim_id)
        result.candidates.append(_candidate(
            chain, chain.claim.verification_reason if is_disputed else "direct_verified_evidence",
            link=links[0], status="DISPUTED" if is_disputed else "SUPPORTED",
        ))
        if target.kind == "annual_total":
            amount = Decimal(claim.value) / Decimal(10000) if claim.unit == "元" else claim.normalized_numeric_value()
            if amount is not None:
                identity = (claim.period, claim.administrative_scope, claim.statistical_caliber, claim.series_version)
                comparable_amounts.setdefault(identity, {}).setdefault(amount, set()).add(claim.claim_id)
    conflicting_ids = _record_amount_conflicts(comparable_amounts, coverage)
    for candidate in result.candidates:
        if candidate.claim_id in conflicting_ids:
            candidate.status = "DISPUTED"
            candidate.reason = "conflicting_contract_evidence"
    for chain in unselected:
        if _related_to_target(chain, target):
            issue = target.claim_issue(slot, chain.claim) or "outside_selected_evidence"
            result.candidates.append(_candidate(chain, issue, link=next(graph.intact_links(chain), None)))
    result.claim_ids = sorted(set(disputed + supported))
    if disputed or conflicting_ids:
        result.status, result.reason = "CONFLICT_UNRESOLVED", "conflicting_supported_evidence"
    elif supported:
        result.status, result.reason = "SUPPORTED", "direct_verified_evidence"
    else:
        result.status, result.reason = "INSUFFICIENT", "no_direct_verified_answer"
    if result.status != "SUPPORTED":
        result.missing_metrics = [target.label]
    if target.kind == "enterprise":
        pool = graph.list_run_claims(run_id) if run_id else [item.chain.claim for item in findings]
        result.enterprise_leads = collect_enterprise_leads(
            target, graph, pool, run_id=run_id, supported_claim_ids=set(supported),
        )


def _record_amount_conflicts(
    amounts_by_scope: dict[tuple[str, str, str, str], dict[Decimal, set[str]]],
    coverage: ContractCoverage,
) -> set[str]:
    conflicting_ids: set[str] = set()
    for amounts in amounts_by_scope.values():
        if len(amounts) < 2:
            continue
        all_ids = set().union(*amounts.values())
        conflicting_ids.update(all_ids)
        for ids in amounts.values():
            for claim_id in ids:
                coverage.conflicts.setdefault(claim_id, set()).update(all_ids - ids)
    return conflicting_ids


def assess_contract_coverage(
    contract: ResearchContract, graph: EvidenceGraphStore, findings: list[VerifiedFinding], *,
    run_id: str = "", executions: list[SearchExecution] | None = None,
) -> ContractCoverage:
    coverage = ContractCoverage()
    if not contract.required_questions:
        return coverage
    if len(contract.regions) != 1:
        coverage.questions = [ContractQuestionResult(
            question_id=f"contract:{index}", question=question, status="NEEDS_REVIEW",
            reason="unsupported_multi_region", missing_metrics=[question],
        ) for index, question in enumerate(contract.required_questions)]
        return coverage
    slots = contract.to_research_spec().question_slots
    targets = [question_target(slot) for slot in slots]
    labels = {target.label for target in targets if target is not None}
    selected = {item.finding.claim_id for item in findings}
    unselected = []
    if run_id and labels:
        for claim in graph.list_run_claims(run_id):
            text = "".join(claim.statement.split())
            if claim.claim_id not in selected and any(label in text for label in labels):
                try:
                    unselected.append(graph.get_chain(claim.claim_id, run_id=run_id))
                except KeyError:
                    # A concurrent retry can clear the run's evidence.
                    continue
    for slot, target in zip(slots, targets, strict=True):
        result = ContractQuestionResult(
            question_id=slot.slot_id, question=slot.research_question, status="NEEDS_REVIEW",
            query_executions=None if executions is None else [item for item in executions if item.slot_id == slot.slot_id],
        )
        if target is None or slot.evidence_requirement:
            result.reason = "custom_evidence_requirement" if slot.evidence_requirement else "unsupported_question_form"
            result.missing_metrics = [target.label if target else slot.research_question]
        else:
            _assess_question(slot, target, coverage, graph, findings, unselected, result, run_id=run_id)
        coverage.questions.append(result)
    return coverage
