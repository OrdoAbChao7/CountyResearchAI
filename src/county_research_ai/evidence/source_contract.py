"""Stable source archive contract used by experiment and evidence pipelines."""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from ..models import RawDoc

MIN_VERIFIABLE_CREDIBILITY = 0.65
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 120


def meets_source_credibility_threshold(
    metadata: Mapping[str, Any], *, allow_unscored: bool = False,
) -> bool:
    """Apply the source credibility floor to a stored assessment.

    Legacy graph imports may predate source scoring. Search ingestion always
    records a score, so only older and externally supplied snapshots use the
    compatibility fallback.
    """
    if "credibility_score" not in metadata:
        return allow_unscored
    try:
        score = float(metadata["credibility_score"])
    except (TypeError, ValueError, OverflowError):
        return False
    return MIN_VERIFIABLE_CREDIBILITY <= score <= 1.0


def _text_chunks(content: str, doc_id: str) -> list[dict[str, Any]]:
    if not content:
        return []
    chunks: list[dict[str, Any]] = []
    start = 0
    chunk_number = 1
    while start < len(content):
        end = min(len(content), start + _CHUNK_SIZE)
        text = content[start:end]
        chunks.append(
            {
                "chunk_id": f"{doc_id}:chunk:{chunk_number}",
                "text": text,
                "heading": "",
                "start_offset": start,
                "end_offset": end,
                "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
        if end == len(content):
            break
        start = end - _CHUNK_OVERLAP
        chunk_number += 1
    return chunks


def serialize_source_documents(docs: Iterable[RawDoc]) -> list[dict[str, Any]]:
    """Serialize RawDocs with enough provenance for offline claim scoring.

    Document and chunk identifiers depend on source URL, body, and title. A
    revised title can change the evidence's scope even when the body is the same.
    Timestamps retain observed metadata without changing these identifiers.
    Empty content is represented as ``snippet_only`` when a snippet is available.
    """
    records: list[dict[str, Any]] = []
    for doc in docs:
        content = doc.content or doc.snippet
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        doc_id = hashlib.sha256(
            f"{doc.url}\n{content_hash}\n{doc.title}".encode()
        ).hexdigest()[:24]
        provider = str(doc.source or doc.metadata.get("provider") or "unknown")
        source_type = str(doc.domain_type or doc.metadata.get("source_type") or "unknown")
        fetch_status = "fetched" if doc.content else ("snippet_only" if doc.snippet else "empty")
        document_timestamp = (
            doc.published_at.isoformat()
            if doc.published_at is not None
            else doc.fetched_at.isoformat()
        )
        records.append(
            {
                "doc_id": doc_id,
                "title": doc.title,
                "url": doc.url,
                "canonical_url": doc.url,
                "content": content,
                "content_hash": content_hash,
                "fetch_status": fetch_status,
                "provider": provider,
                "source_type": source_type,
                "document_timestamp": document_timestamp,
                "published_at": doc.published_at.isoformat() if doc.published_at else None,
                "retrieved_at": doc.fetched_at.isoformat(),
                "content_original_length": doc.content_original_length,
                "content_truncated": doc.content_truncated,
                "truncation_reason": doc.truncation_reason,
                "metadata": {
                    **dict(doc.metadata),
                    "credibility_score": doc.credibility_score,
                },
                "chunks": _text_chunks(content, doc_id),
            }
        )
    return records
