"""Fixtures shared by projection tests (not collected as tests)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from county_research_ai.api.jobs import JobRecord, JobStatus
from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    ResearchContract,
    SourceDocument,
)
from county_research_ai.evidence.graph import (
    EvidenceGraphStore,
    FindingRecord,
    VerificationStatus,
)
from county_research_ai.evidence.ledger import EvidenceLedger

RUN_ID = "run-projection-1"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_source(
    doc_id: str,
    *,
    url: str,
    content: str,
    title: str = "",
    extra_chunks: tuple[str, ...] = (),
) -> SourceDocument:
    full = content
    chunks = [
        EvidenceChunk(
            chunk_id=f"{doc_id}:chunk:1",
            document_id=doc_id,
            text=content,
            start_offset=0,
            end_offset=len(content),
            offset_status="exact",
            content_hash=text_hash(content),
        )
    ]
    cursor = len(content)
    for index, extra in enumerate(extra_chunks, start=2):
        full += "\n" + extra
        cursor += 1
        chunks.append(
            EvidenceChunk(
                chunk_id=f"{doc_id}:chunk:{index}",
                document_id=doc_id,
                text=extra,
                start_offset=cursor,
                end_offset=cursor + len(extra),
                offset_status="exact",
                content_hash=text_hash(extra),
            )
        )
        cursor += len(extra)
    return SourceDocument(
        doc_id=doc_id,
        canonical_url=url,
        source_title=title or f"安吉县竹产业资料 {doc_id}",
        content=full,
        content_hash=text_hash(full),
        retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        publish_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        source_type="government",
        fetch_status="fetched",
        provider="fixture",
        chunks=chunks,
    )


def make_claim(
    claim_id: str,
    *,
    source_id: str,
    chunk_ids: list[str] | None = None,
    value: str = "120",
    unit: str = "亿元",
    period: str = "2024",
    metric: str = "竹产业产值",
    statement: str = "",
    region: str = "安吉县",
    scope: str = "县域本级",
) -> AtomicClaim:
    return AtomicClaim(
        claim_id=claim_id,
        statement=statement or f"{region}{period}年{metric}为{value}{unit}",
        region_id=region,
        metric_id=metric,
        value=value,
        unit=unit,
        period=period,
        administrative_scope=scope,
        source_ids=[source_id],
        evidence_chunk_ids=chunk_ids or [f"{source_id}:chunk:1"],
    )


def seed_graph(
    path,
    run_id: str,
    *,
    sources: list[SourceDocument],
    claims: list[AtomicClaim],
    statuses: dict[str, VerificationStatus] | None = None,
) -> EvidenceGraphStore:
    graph = EvidenceGraphStore(path)
    ledger = EvidenceLedger()
    for source in sources:
        ledger.add_source(source)
    for claim in claims:
        ledger.add_claim(claim)
    graph.save_ledger(ledger, run_id=run_id)
    findings: list[FindingRecord] = []
    for claim in claims:
        chain = graph.get_chain(claim.claim_id, run_id=run_id)
        status = (statuses or {}).get(claim.claim_id)
        if status is None:
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
                section="s1",
                text=claim.statement,
                status=status,
            )
        )
    graph.save_findings(run_id, findings)
    return graph


def deep_result(
    *,
    questions: list[dict[str, Any]] | None = None,
    items: list[dict[str, Any]] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
    gaps: list[dict[str, Any]] | None = None,
    coverage_rate: float = 0.5,
) -> dict[str, Any]:
    return {
        "deep_research": {
            "enabled": True,
            "coverage_rate": coverage_rate,
            "total_turns": 1,
            "reflection_turns": 1,
            "retrieval_stop_reason": "sufficient",
            "retrieval_usage": {},
            "question_tree": {
                "county": "安吉县",
                "focus": "竹产业",
                "mode": "snapshot",
                "questions": questions or [],
            },
            "items": items or [],
            "conflicts": conflicts or [],
            "gaps": gaps or [],
        }
    }


def make_job(
    *,
    run_id: str = RUN_ID,
    result: dict[str, Any] | None = None,
    mode: str = "snapshot",
    county: str = "安吉县",
    focus: str = "竹产业",
    report_path: str = "",
) -> JobRecord:
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    contract = ResearchContract(
        objective="分析安吉县竹产业",
        regions=[county],
        research_focus=focus,
        mode=mode,
    )
    return JobRecord(
        job_id=run_id,
        status=JobStatus.SUCCEEDED,
        contract=contract,
        county=county,
        focus=focus,
        mode=mode,
        mode_label="MOCK",
        created_at=now,
        updated_at=now,
        report_path=report_path,
        result=result or {},
    )


def make_item(
    item_id: str,
    claim: AtomicClaim,
    source: SourceDocument,
    *,
    topic: str = "竹产业",
    credibility: float = 0.9,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "claim": claim.statement,
        "url": source.canonical_url,
        "topic": topic,
        "credibility_score": credibility,
        "title": source.title,
        "snippet": source.content[:120],
        "year": claim.period,
        "domain_type": "government",
    }
