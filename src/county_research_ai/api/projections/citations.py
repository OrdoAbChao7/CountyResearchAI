"""Numbered citations shared by the report and evidence projections."""
from __future__ import annotations

from ...evidence.graph import EvidenceLink, VerifiedFinding
from .common import source_credibility
from .models import CitationView

_STATUS_ORDER = {
    "SUPPORTED": 0,
    "NEEDS_REVIEW": 1,
    "CONTRADICTED": 2,
    "OUTDATED": 3,
    "NOT_COMPARABLE": 4,
    "INSUFFICIENT": 5,
}


def build_citations(
    findings: list[VerifiedFinding], *, preferred_links: dict[str, EvidenceLink],
) -> list[CitationView]:
    ordered = sorted(
        [finding for finding in findings if finding.chain.links],
        key=lambda finding: (
            _STATUS_ORDER.get(finding.finding.status.value, 9),
            finding.chain.claim.metric_id,
            finding.chain.claim.period,
            finding.chain.claim.claim_id,
        ),
    )
    citations: list[CitationView] = []
    for finding in ordered:
        claim = finding.chain.claim
        link = preferred_links.get(claim.claim_id)
        if link is None:
            if finding.finding.status.value == "SUPPORTED":
                continue
            link = next(
                (item for item in finding.chain.links if item.edge.relation.value != "contradicts"),
                finding.chain.links[0],
            )
        snapshot = link.snapshot
        citations.append(
            CitationView(
                n=len(citations) + 1,
                evidence_id=claim.claim_id,
                claim_id=claim.claim_id,
                snapshot_id=snapshot.snapshot_id,
                span_id=link.span.span_id,
                statement=claim.statement,
                value=claim.value,
                unit=claim.unit,
                period=claim.period,
                title=snapshot.title,
                url=snapshot.canonical_url,
                credibility=source_credibility(snapshot),
                domain_type=snapshot.source_type,
                year=claim.period or None,
                status=finding.finding.status.value,
                quote=link.span.quote,
            )
        )
    return citations


def citation_numbers(citations: list[CitationView]) -> dict[str, int]:
    return {citation.claim_id: citation.n for citation in citations}


__all__ = ["build_citations", "citation_numbers"]
