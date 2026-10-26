"""Typed request/response schemas for the AxiomScope API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ..domain.outcomes import ResearchOutcome
from ..domain.research_contracts import ResearchContract
from ..evidence.graph import ClaimChain, SourceSnapshotRecord, VerifiedFinding
from .jobs import EventRecord, JobRecord, JobStatus


class CreateTaskRequest(BaseModel):
    contract: ResearchContract


class TaskSummary(BaseModel):
    job_id: str
    status: JobStatus
    outcome: ResearchOutcome | None = None
    outcome_reason: str = ""
    objective: str
    regions: list[str]
    mode: str
    mode_label: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_requested: bool = False
    error_code: str = ""
    report_path: str = ""

    @classmethod
    def from_job(cls, job: JobRecord) -> TaskSummary:
        return cls(
            job_id=job.job_id,
            status=job.status,
            outcome=job.outcome,
            outcome_reason=job.outcome_reason,
            objective=job.contract.objective,
            regions=job.contract.regions,
            mode=job.mode,
            mode_label=job.mode_label,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            cancel_requested=job.cancel_requested,
            error_code=job.error_code,
            report_path=job.report_path,
        )


class TaskDetail(TaskSummary):
    contract: ResearchContract
    result: dict[str, Any] = Field(default_factory=dict)
    budget_enforcement: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_job(cls, job: JobRecord) -> TaskDetail:
        summary = TaskSummary.from_job(job)
        return cls(
            **summary.model_dump(),
            contract=job.contract,
            result=job.result,
            budget_enforcement=job.budget_enforcement,
        )


class EventOut(BaseModel):
    seq: int
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @classmethod
    def from_event(cls, event: EventRecord) -> EventOut:
        return cls(
            seq=event.seq,
            event_type=event.event_type,
            payload=event.payload,
            created_at=event.created_at,
        )


class ClaimOut(BaseModel):
    claim_id: str
    statement: str
    region: str
    metric: str
    value: str
    unit: str
    period: str
    scope: str
    caliber: str
    version: str
    verification_status: str
    verification_reason: str = ""


class EvidenceLinkOut(BaseModel):
    relation: str
    span_id: str
    quote: str
    start_offset: int | None = None
    end_offset: int | None = None
    offset_status: str
    snapshot_id: str
    url: str
    title: str
    observed_at: datetime | None = None
    published_at: datetime | None = None


class FindingOut(BaseModel):
    finding_id: str
    section: str
    text: str
    status: str
    claim: ClaimOut
    links: list[EvidenceLinkOut] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_verified(cls, verified: VerifiedFinding) -> FindingOut:
        chain = verified.chain
        claim = chain.claim
        return cls(
            finding_id=verified.finding.finding_id,
            section=verified.finding.section,
            text=verified.finding.text,
            status=verified.finding.status.value,
            claim=ClaimOut(
                claim_id=claim.claim_id,
                statement=claim.statement,
                region=claim.region_id,
                metric=claim.metric_id,
                value=claim.value,
                unit=claim.unit,
                period=claim.period,
                scope=claim.administrative_scope,
                caliber=claim.statistical_caliber,
                version=claim.series_version,
                verification_status=claim.verification_status,
                verification_reason=claim.verification_reason,
            ),
            links=[
                EvidenceLinkOut(
                    relation=link.edge.relation.value,
                    span_id=link.span.span_id,
                    quote=link.span.quote,
                    start_offset=link.span.start_offset,
                    end_offset=link.span.end_offset,
                    offset_status=link.span.offset_status,
                    snapshot_id=link.snapshot.snapshot_id,
                    url=link.snapshot.canonical_url,
                    title=link.snapshot.title,
                    observed_at=link.snapshot.observed_at,
                    published_at=link.snapshot.published_at,
                )
                for link in chain.links
            ],
            checks=(
                chain.verification.deterministic_checks
                if chain.verification is not None
                else {}
            ),
        )


class ClaimChainOut(BaseModel):
    finding: FindingOut
    relations: list[dict[str, str]] = Field(default_factory=list)

    @classmethod
    def from_chain(cls, chain: ClaimChain) -> ClaimChainOut:
        verified = VerifiedFinding(
            finding=_finding_from_chain(chain), chain=chain
        )
        return cls(
            finding=FindingOut.from_verified(verified),
            relations=[
                {
                    "from_claim_id": relation.from_claim_id,
                    "to_claim_id": relation.to_claim_id,
                    "relation": relation.relation.value,
                    "rationale": relation.rationale,
                }
                for relation in chain.relations
            ],
        )


def _finding_from_chain(chain: ClaimChain):
    from ..evidence.graph import FindingRecord, VerificationStatus

    status = (
        chain.verification.status
        if chain.verification is not None
        else VerificationStatus.INSUFFICIENT
    )
    return FindingRecord(
        finding_id=chain.claim.claim_id,
        run_id="",
        claim_id=chain.claim.claim_id,
        text=chain.claim.statement,
        status=status,
    )


class SourceOut(BaseModel):
    snapshot_id: str
    title: str
    url: str
    source_type: str
    fetch_status: str
    observed_at: datetime | None = None
    published_at: datetime | None = None
    content_length: int = 0

    @classmethod
    def from_snapshot(cls, snapshot: SourceSnapshotRecord) -> SourceOut:
        return cls(
            snapshot_id=snapshot.snapshot_id,
            title=snapshot.title,
            url=snapshot.canonical_url,
            source_type=snapshot.source_type,
            fetch_status=snapshot.fetch_status,
            observed_at=snapshot.observed_at,
            published_at=snapshot.published_at,
            content_length=len(snapshot.content),
        )


class SourceDetailOut(SourceOut):
    content: str

    @classmethod
    def from_snapshot(cls, snapshot: SourceSnapshotRecord) -> SourceDetailOut:
        summary = SourceOut.from_snapshot(snapshot)
        return cls(**summary.model_dump(), content=snapshot.content)


class CapabilitiesOut(BaseModel):
    api_version: str
    job_schema_version: int
    evidence_schema_version: int
    mode_label: str
    live_enabled: bool
    enforced_caps: list[str]
    unenforced_caps: list[str]
    docs_url: str
