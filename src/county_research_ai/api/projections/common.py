"""Shared, deterministic helpers for graph/report/evidence projections."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ...domain.research_contracts import AtomicClaim
from ...evidence.graph import (
    EdgeRelation,
    SourceSnapshotRecord,
    VerificationStatus,
    VerifiedFinding,
)
from ...evidence.measure import canonical_reporting_period
from ...evidence.source_contract import meets_source_credibility_threshold
from ..jobs import JobRecord


class ProjectionUnavailable(Exception):
    """The run cannot provide a projection; the API maps this to 409."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def deep_projection(job: JobRecord, *, required: bool = True) -> dict[str, Any]:
    deep = (job.result or {}).get("deep_research") or {}
    if required and not deep.get("enabled"):
        raise ProjectionUnavailable(
            "deep_research_disabled",
            "this run has no deep research artifacts",
        )
    return deep


def sha(text: str, length: int = 10) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def normalize_url(url: str) -> str:
    """Canonical URL used for node identity and conflict matching.

    The function only normalizes; it does not claim two different URLs are
    independent or duplicate beyond these deterministic transformations.
    """

    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    query.sort()
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def matches_legacy_conflict_member(member: dict[str, Any], claim: AtomicClaim) -> bool:
    value = "".join(str(member.get("value", "")).split()).replace(",", "")
    if member.get("unit") and member["unit"] != claim.unit:
        return False
    try:
        same_amount = Decimal(value.removesuffix(claim.unit)) == Decimal(claim.value.replace(",", ""))
    except InvalidOperation:
        return False
    return same_amount and (
        not member.get("year")
        or canonical_reporting_period(str(member["year"])) == canonical_reporting_period(claim.period)
    ) and all(
        not member.get(key) or member[key] == expected
        for key, expected in (("scope", claim.administrative_scope), ("caliber", claim.statistical_caliber))
    )


def visible_conflicts(
    deep: dict[str, Any], findings: list[VerifiedFinding], snapshots: list[SourceSnapshotRecord],
) -> list[dict[str, Any]]:
    """Omit archived groups containing a known ineligible source, without rewriting them."""
    conflicts = deep.get("conflicts") or []
    if not conflicts:
        return []
    eligibility: dict[str, set[bool]] = defaultdict(set)
    item_scores: dict[str, bool] = {}
    for snapshot in snapshots:
        eligibility[normalize_url(snapshot.canonical_url)].add(
            meets_source_credibility_threshold(snapshot.metadata, allow_unscored=True)
        )
    for item in deep.get("items") or []:
        if "credibility_score" in item:
            score = meets_source_credibility_threshold(item)
            if item.get("id"):
                item_scores[str(item["id"])] = score
            eligibility[normalize_url(str(item.get("url") or ""))].add(score)
    by_url: dict[str, list[tuple[AtomicClaim, bool]]] = defaultdict(list)
    for finding in findings:
        for link in finding.chain.links:
            if link.edge.relation is not EdgeRelation.CONTRADICTS:
                by_url[normalize_url(link.snapshot.canonical_url)].append((
                    finding.chain.claim, link.edge.source_credibility_eligible
                    and meets_source_credibility_threshold(link.snapshot.metadata, allow_unscored=True),
                ))

    def member_is_eligible(member: dict[str, Any]) -> bool:
        item_id = str(member.get("item_id") or "")
        if item_scores.get(item_id) is False:
            return False
        url = normalize_url(str(member.get("url") or ""))
        if not url:
            return True  # The legacy group can still be displayed as unmatched.
        exact = [eligible for claim, eligible in by_url[url] if claim.claim_id == item_id]
        matched = exact or [
            eligible for claim, eligible in by_url[url] if matches_legacy_conflict_member(member, claim)
        ]
        return any(matched) if matched else eligibility.get(url) != {False}

    return [conflict for conflict in conflicts if all(member_is_eligible(m) for m in conflict.get("claims") or [])]


def normalize_text(text: str) -> str:
    return " ".join((text or "").split())


def truncate(text: str, limit: int) -> str:
    collapsed = " ".join((text or "").split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


STATUS_WEIGHT = {
    VerificationStatus.SUPPORTED.value: 1.0,
    VerificationStatus.NEEDS_REVIEW.value: 0.7,
    VerificationStatus.CONTRADICTED.value: 0.5,
    VerificationStatus.OUTDATED.value: 0.4,
    VerificationStatus.NOT_COMPARABLE.value: 0.3,
    VerificationStatus.INSUFFICIENT.value: 0.2,
}


def status_weight(status: str) -> float:
    return STATUS_WEIGHT.get(status, 0.2)


def source_credibility(snapshot: Any) -> float:
    metadata = getattr(snapshot, "metadata", None) or {}
    try:
        return float(metadata.get("credibility_score", 0.5))
    except (TypeError, ValueError):
        return 0.5


def item_index(items: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Index evidence items by ID and by their historical text and URL."""
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        item_id = str(item.get("id", ""))
        if item_id:
            index["", item_id] = item
        claim = normalize_text(str(item.get("claim", "")))
        if claim:
            url = normalize_url(str(item.get("url", "")))
            index[claim, url] = item
            index.setdefault((claim, ""), item)
    return index


def find_item(
    index: dict[tuple[str, str], dict[str, Any]],
    statement: str,
    urls: list[str],
    *,
    claim_id: str,
) -> dict[str, Any] | None:
    if match := index.get(("", claim_id)):
        return match
    claim = normalize_text(statement)
    if not claim:
        return None
    for url in urls:
        if match := index.get((claim, normalize_url(url))):
            return match
    return index.get((claim, ""))


def question_ids_by_item(question_tree: dict[str, Any]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for question in question_tree.get("questions", []) or []:
        question_id = str(question.get("id", ""))
        for item_id in question.get("evidence_ids", []) or []:
            mapping.setdefault(str(item_id), []).append(question_id)
    return mapping
