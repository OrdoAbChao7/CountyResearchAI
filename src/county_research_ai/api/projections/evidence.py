"""Evidence list projection used by the drawer and the accessible graph list."""
from __future__ import annotations

from ...evidence.graph import EvidenceGraphStore
from ..jobs import JobRecord
from .citations import build_citations, citation_numbers
from .common import find_item, item_index, question_ids_by_item
from .models import EvidenceItemView, EvidenceLinkView, EvidenceListResponse


def build_evidence_list(
    *,
    job: JobRecord,
    graph: EvidenceGraphStore,
    query: str = "",
    status: str = "",
    topic: str = "",
    min_credibility: float = 0.0,
    limit: int = 50,
    offset: int = 0,
) -> EvidenceListResponse:
    findings = graph.list_findings(job.job_id)
    deep = (job.result or {}).get("deep_research") or {}
    items = deep.get("items") or []
    item_lookup = item_index(items)
    item_questions = question_ids_by_item(deep.get("question_tree") or {})
    numbers = citation_numbers(build_citations(findings))
    needle = query.strip().lower()

    views: list[EvidenceItemView] = []
    for finding in findings:
        chain = finding.chain
        claim = chain.claim
        urls = [
            link.snapshot.canonical_url
            for link in chain.links
            if link.snapshot.canonical_url
        ]
        item = find_item(item_lookup, claim.statement, urls)
        item_id = str(item.get("id", "")) if item is not None else ""
        credibility = (
            float(item.get("credibility_score", 0.5))
            if item is not None
            else 0.5
        )
        item_topic = str(item.get("topic", "")) if item is not None else ""
        statement = claim.statement
        snippet = str(item.get("snippet", "")) if item is not None else ""
        title = str(item.get("title", "")) if item is not None else ""
        if needle and not any(
            needle in value.lower() for value in (statement, snippet, title)
        ):
            continue
        if status and finding.finding.status.value != status:
            continue
        if topic and item_topic != topic:
            continue
        if credibility < min_credibility:
            continue
        links = [
            EvidenceLinkView(
                relation=link.edge.relation.value,
                span_id=link.span.span_id,
                quote=link.span.quote,
                snapshot_id=link.snapshot.snapshot_id,
                url=link.snapshot.canonical_url,
                title=link.snapshot.title,
                start_offset=link.span.start_offset,
                end_offset=link.span.end_offset,
            )
            for link in chain.links
        ]
        primary = next(
            (link for link in links if link.relation != "contradicts"),
            links[0] if links else None,
        )
        views.append(
            EvidenceItemView(
                id=claim.claim_id,
                claim_id=claim.claim_id,
                statement=statement,
                snippet=snippet,
                metric=claim.metric_id or claim.measure_id,
                value=claim.value,
                unit=claim.unit,
                period=claim.period,
                scope=claim.administrative_scope,
                caliber=claim.statistical_caliber,
                status=finding.finding.status.value,
                reason=chain.verification.reason if chain.verification else "",
                topic=item_topic,
                year=item.get("year") if item is not None else None,
                credibility=credibility,
                url=primary.url if primary is not None else "",
                title=primary.title if primary is not None else "",
                domain_type=(
                    item.get("domain_type", "unknown")
                    if item is not None
                    else "unknown"
                ),
                citation_number=numbers.get(claim.claim_id),
                question_ids=item_questions.get(item_id, []),
                links=links,
            )
        )

    views.sort(
        key=lambda view: (
            _status_rank(view.status),
            -view.credibility,
            view.claim_id,
        )
    )
    total = len(views)
    return EvidenceListResponse(
        run_id=job.job_id,
        items=views[offset : offset + limit],
        total=total,
        limit=limit,
        offset=offset,
    )


def _status_rank(status: str) -> int:
    return {
        "SUPPORTED": 0,
        "NEEDS_REVIEW": 1,
        "CONTRADICTED": 2,
        "OUTDATED": 3,
        "NOT_COMPARABLE": 4,
        "INSUFFICIENT": 5,
    }.get(status, 9)


__all__ = ["build_evidence_list"]
