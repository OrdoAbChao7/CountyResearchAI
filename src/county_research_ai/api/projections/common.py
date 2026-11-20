"""Shared, deterministic helpers for graph/report/evidence projections."""
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ...evidence.graph import VerificationStatus
from ..jobs import JobRecord


class ProjectionUnavailable(Exception):
    """The run cannot provide a projection; the API maps this to 409."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def deep_projection(job: JobRecord) -> dict[str, Any]:
    deep = (job.result or {}).get("deep_research") or {}
    if not deep.get("enabled"):
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


def item_index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map a normalized claim text + optional URL to an EvidenceStore item."""

    index: dict[str, dict[str, Any]] = {}
    for item in items:
        claim = normalize_text(str(item.get("claim", "")))
        if not claim:
            continue
        url = normalize_url(str(item.get("url", "")))
        index[f"{claim}\n{url}"] = item
        index.setdefault(claim, item)
    return index


def find_item(
    index: dict[str, dict[str, Any]],
    statement: str,
    urls: list[str],
) -> dict[str, Any] | None:
    claim = normalize_text(statement)
    if not claim:
        return None
    for url in urls:
        match = index.get(f"{claim}\n{normalize_url(url)}")
        if match is not None:
            return match
    return index.get(claim)


def question_ids_by_item(question_tree: dict[str, Any]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for question in question_tree.get("questions", []) or []:
        question_id = str(question.get("id", ""))
        for item_id in question.get("evidence_ids", []) or []:
            mapping.setdefault(str(item_id), []).append(question_id)
    return mapping
