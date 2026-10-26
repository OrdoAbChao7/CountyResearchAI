"""Persistent, append-only temporal evidence graph backed by SQLite.

The in-memory :class:`EvidenceLedger` established the contracts for sources,
chunks, and claims. This module persists that graph so a finding can be walked
back to an exact quote inside an immutable source snapshot, and so claim
relations and deterministic verification survive a process restart.

Design constraints:

* Source snapshots and evidence spans are append-only. Re-inserting the same id
  with different content raises instead of silently overwriting history.
* Verification is deterministic. A claim is never marked ``SUPPORTED`` merely
  because a source is credible; the quote must resolve inside the snapshot and
  the claimed value, unit, region, and period must be checkable in that quote.
* ``NOT_COMPARABLE`` (different year, scope, caliber, or incompatible unit) is
  kept distinct from ``CONTRADICTED``.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    SourceDocument,
)
from .ledger import EvidenceLedger

SCHEMA_VERSION = 1
DETERMINISTIC_VERIFIER_VERSION = "deterministic_v1"

_YEAR_RE = re.compile(r"(?<!\d)(?:1[89]\d{2}|20\d{2})(?!\d)")
_NUMERIC_RE = re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*(亿元|万元|亿|万|%|‰|亩|万人|人)?")
_WS_RE = re.compile(r"\s+")


class EdgeRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class ClaimRelationKind(StrEnum):
    SAME_FACT = "same_fact"
    CONTRADICTS = "contradicts"
    NOT_COMPARABLE = "not_comparable"
    SUPERSEDES = "supersedes"
    RELATED = "related"


class VerificationStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT = "INSUFFICIENT"
    NOT_COMPARABLE = "NOT_COMPARABLE"
    OUTDATED = "OUTDATED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class SourceSnapshotRecord(BaseModel):
    snapshot_id: str
    canonical_url: str = ""
    title: str = ""
    content: str = ""
    content_hash: str = ""
    provider: str = "unknown"
    source_type: str = "unknown"
    fetch_status: str = "unknown"
    observed_at: datetime | None = None
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceSpanRecord(BaseModel):
    span_id: str
    snapshot_id: str
    quote: str = ""
    start_offset: int | None = None
    end_offset: int | None = None
    offset_status: Literal["exact", "limited", "unknown"] = "unknown"
    heading: str = ""
    parent_span_id: str = ""
    extractor_version: str = "source_contract_v1"
    content_hash: str = ""


class ClaimEvidenceEdgeRecord(BaseModel):
    claim_id: str
    span_id: str
    relation: EdgeRelation = EdgeRelation.CONTEXT
    rationale: str = ""
    verifier_version: str = DETERMINISTIC_VERIFIER_VERSION


class ClaimRelationRecord(BaseModel):
    from_claim_id: str
    to_claim_id: str
    relation: ClaimRelationKind
    rationale: str = ""


class VerificationRecord(BaseModel):
    record_id: str
    claim_id: str
    status: VerificationStatus
    deterministic_checks: dict[str, Any] = Field(default_factory=dict)
    judge_assessment: dict[str, Any] | None = None
    uncertainty: float | None = None
    human_review: dict[str, Any] | None = None
    verifier_version: str = DETERMINISTIC_VERIFIER_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceLink(BaseModel):
    edge: ClaimEvidenceEdgeRecord
    span: EvidenceSpanRecord
    snapshot: SourceSnapshotRecord


class ClaimChain(BaseModel):
    claim: AtomicClaim
    links: list[EvidenceLink] = Field(default_factory=list)
    relations: list[ClaimRelationRecord] = Field(default_factory=list)
    verification: VerificationRecord | None = None


class FindingRecord(BaseModel):
    finding_id: str
    run_id: str
    claim_id: str
    section: str = ""
    text: str = ""
    status: VerificationStatus = VerificationStatus.INSUFFICIENT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VerifiedFinding(BaseModel):
    finding: FindingRecord
    chain: ClaimChain


class SpanIntegrityIssue(BaseModel):
    span_id: str
    snapshot_id: str
    issue: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub("", text)


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _unit_multiplier(unit: str) -> Decimal | None:
    return {
        "万元": Decimal("1"),
        "万": Decimal("1"),
        "亿元": Decimal("10000"),
        "亿": Decimal("10000"),
    }.get(unit)


def _years(text: str) -> list[str]:
    return _YEAR_RE.findall(text)


def _value_forms(value: str, unit: str) -> set[str]:
    if not value:
        return set()
    forms = {value, f"{value}{unit}" if unit else value}
    stripped = value.replace(",", "")
    forms.add(stripped)
    if unit:
        forms.add(f"{stripped}{unit}")
    return {form for form in forms if form}


def _quote_contains_value(quote: str, value: str, unit: str) -> bool:
    """Check a numeric value without requiring identical formatting."""
    normalized_quote = _normalize_ws(quote)
    if any(form in normalized_quote for form in _value_forms(value, unit)):
        return True
    target = _decimal(value)
    if target is None:
        return False
    target_unit_multiplier = _unit_multiplier(unit)
    for match in _NUMERIC_RE.finditer(quote):
        found = _decimal(match.group(1))
        if found is None:
            continue
        found_unit = match.group(2) or ""
        if found == target and (not unit or found_unit == unit or not found_unit):
            return True
        if target_unit_multiplier is not None:
            found_multiplier = _unit_multiplier(found_unit)
            if found_multiplier is not None and found * found_multiplier == target * target_unit_multiplier:
                return True
    return False


def claim_identity(claim: AtomicClaim) -> tuple[str, ...]:
    return (
        claim.region_id,
        claim.metric_id,
        claim.period,
        claim.administrative_scope,
        claim.statistical_caliber,
        claim.series_version,
    )


def classify_claim_relation(
    left: AtomicClaim,
    right: AtomicClaim,
    *,
    left_observed: datetime | None = None,
    right_observed: datetime | None = None,
) -> ClaimRelationRecord | None:
    """Classify ``left`` relative to ``right`` using deterministic identity rules."""
    if left.claim_id == right.claim_id:
        return None
    if left.metric_id != right.metric_id:
        return None
    if left.region_id != right.region_id:
        return ClaimRelationRecord(
            from_claim_id=left.claim_id,
            to_claim_id=right.claim_id,
            relation=ClaimRelationKind.RELATED,
            rationale="shared_metric_different_region",
        )
    if left.period != right.period:
        return ClaimRelationRecord(
            from_claim_id=left.claim_id,
            to_claim_id=right.claim_id,
            relation=ClaimRelationKind.NOT_COMPARABLE,
            rationale=f"different_period:{left.period}|{right.period}",
        )
    if left.administrative_scope != right.administrative_scope:
        return ClaimRelationRecord(
            from_claim_id=left.claim_id,
            to_claim_id=right.claim_id,
            relation=ClaimRelationKind.NOT_COMPARABLE,
            rationale=(
                "different_scope:"
                f"{left.administrative_scope}|{right.administrative_scope}"
            ),
        )
    if left.statistical_caliber != right.statistical_caliber:
        return ClaimRelationRecord(
            from_claim_id=left.claim_id,
            to_claim_id=right.claim_id,
            relation=ClaimRelationKind.NOT_COMPARABLE,
            rationale=(
                "different_caliber:"
                f"{left.statistical_caliber}|{right.statistical_caliber}"
            ),
        )
    if left.series_version != right.series_version:
        left_at = left_observed or datetime.min.replace(tzinfo=timezone.utc)
        right_at = right_observed or datetime.min.replace(tzinfo=timezone.utc)
        if left_at == right_at:
            return ClaimRelationRecord(
                from_claim_id=left.claim_id,
                to_claim_id=right.claim_id,
                relation=ClaimRelationKind.NOT_COMPARABLE,
                rationale=f"different_version:{left.series_version}|{right.series_version}",
            )
        newer, older = (
            (left, right) if left_at > right_at else (right, left)
        )
        return ClaimRelationRecord(
            from_claim_id=newer.claim_id,
            to_claim_id=older.claim_id,
            relation=ClaimRelationKind.SUPERSEDES,
            rationale=(
                "newer_series_version:"
                f"{newer.series_version}|{older.series_version}"
            ),
        )

    left_value = left.normalized_numeric_value()
    right_value = right.normalized_numeric_value()
    if left_value is not None and right_value is not None:
        if left_value == right_value:
            return ClaimRelationRecord(
                from_claim_id=left.claim_id,
                to_claim_id=right.claim_id,
                relation=ClaimRelationKind.SAME_FACT,
                rationale="equal_normalized_value",
            )
        return ClaimRelationRecord(
            from_claim_id=left.claim_id,
            to_claim_id=right.claim_id,
            relation=ClaimRelationKind.CONTRADICTS,
            rationale=f"different_normalized_value:{left.value}|{right.value}",
        )
    if left.unit != right.unit:
        return ClaimRelationRecord(
            from_claim_id=left.claim_id,
            to_claim_id=right.claim_id,
            relation=ClaimRelationKind.NOT_COMPARABLE,
            rationale=f"incompatible_units:{left.unit}|{right.unit}",
        )
    if left.value and right.value:
        relation = (
            ClaimRelationKind.SAME_FACT
            if left.value == right.value
            else ClaimRelationKind.CONTRADICTS
        )
        return ClaimRelationRecord(
            from_claim_id=left.claim_id,
            to_claim_id=right.claim_id,
            relation=relation,
            rationale=f"raw_value:{left.value}|{right.value}",
        )
    if _normalize_ws(left.statement) == _normalize_ws(right.statement):
        return ClaimRelationRecord(
            from_claim_id=left.claim_id,
            to_claim_id=right.claim_id,
            relation=ClaimRelationKind.SAME_FACT,
            rationale="identical_statement",
        )
    return ClaimRelationRecord(
        from_claim_id=left.claim_id,
        to_claim_id=right.claim_id,
        relation=ClaimRelationKind.RELATED,
        rationale="same_identity_unstructured",
    )


class EvidenceGraphStore:
    """SQLite-backed append-only evidence graph."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    canonical_url TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'unknown',
                    source_type TEXT NOT NULL DEFAULT 'unknown',
                    fetch_status TEXT NOT NULL DEFAULT 'unknown',
                    observed_at TEXT NOT NULL DEFAULT '',
                    published_at TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_spans (
                    span_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
                    parent_span_id TEXT NOT NULL DEFAULT '',
                    heading TEXT NOT NULL DEFAULT '',
                    quote TEXT NOT NULL,
                    start_offset INTEGER,
                    end_offset INTEGER,
                    offset_status TEXT NOT NULL DEFAULT 'unknown',
                    content_hash TEXT NOT NULL DEFAULT '',
                    extractor_version TEXT NOT NULL DEFAULT 'source_contract_v1',
                    year_hints_json TEXT NOT NULL DEFAULT '[]',
                    metric_hints_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    statement TEXT NOT NULL DEFAULT '',
                    subject TEXT NOT NULL DEFAULT '',
                    predicate TEXT NOT NULL DEFAULT '',
                    value TEXT NOT NULL DEFAULT '',
                    unit TEXT NOT NULL DEFAULT '',
                    normalized_unit TEXT NOT NULL DEFAULT '',
                    region_id TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    valid_time TEXT NOT NULL DEFAULT '',
                    observed_time TEXT NOT NULL DEFAULT '',
                    methodology TEXT NOT NULL DEFAULT '',
                    qualifier TEXT NOT NULL DEFAULT '',
                    verification_status TEXT NOT NULL DEFAULT 'INSUFFICIENT',
                    verification_reason TEXT NOT NULL DEFAULT '',
                    source_ids_json TEXT NOT NULL DEFAULT '[]',
                    evidence_chunk_ids_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS claim_evidence_edges (
                    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                    span_id TEXT NOT NULL REFERENCES evidence_spans(span_id),
                    relation TEXT NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    verifier_version TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (claim_id, span_id, relation)
                );
                CREATE TABLE IF NOT EXISTS claim_relations (
                    from_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                    to_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                    relation TEXT NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (from_claim_id, to_claim_id, relation)
                );
                CREATE TABLE IF NOT EXISTS verification_records (
                    record_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                    status TEXT NOT NULL,
                    deterministic_checks_json TEXT NOT NULL DEFAULT '{}',
                    judge_assessment_json TEXT,
                    uncertainty REAL,
                    human_review_json TEXT,
                    verifier_version TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS findings (
                    finding_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                    section TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'INSUFFICIENT',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_snapshots (
                    run_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
                    PRIMARY KEY (run_id, snapshot_id)
                );
                CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
                CREATE INDEX IF NOT EXISTS idx_spans_snapshot ON evidence_spans(snapshot_id);
                CREATE INDEX IF NOT EXISTS idx_run_snapshots_run ON run_snapshots(run_id);
                """
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # ---------------------------------------------------------------- writes

    def save_ledger(
        self,
        ledger: EvidenceLedger,
        *,
        run_id: str = "",
        window: tuple[date | None, date | None] | None = None,
    ) -> dict[str, int]:
        """Persist a ledger, classify claim relations, and record verification."""
        now = _utcnow().isoformat()
        observed = {
            claim.claim_id: self._claim_observed_at(ledger, claim)
            for claim in ledger.claims.values()
        }
        with self._connect() as connection:
            for source in ledger.sources.values():
                self._insert_snapshot(connection, source, now)
                if run_id:
                    connection.execute(
                        "INSERT OR IGNORE INTO run_snapshots (run_id, snapshot_id)"
                        " VALUES (?, ?)",
                        (run_id, source.doc_id),
                    )
            for chunk in ledger.chunks.values():
                self._insert_span(connection, chunk)
            for claim in ledger.claims.values():
                self._insert_claim(connection, claim, observed[claim.claim_id], now)
                for chunk_id in claim.evidence_chunk_ids:
                    connection.execute(
                        "INSERT OR IGNORE INTO claim_evidence_edges"
                        " (claim_id, span_id, relation, rationale, verifier_version, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            claim.claim_id,
                            chunk_id,
                            EdgeRelation.CONTEXT.value,
                            "ledger_evidence_link",
                            "ledger_adapter_v1",
                            now,
                        ),
                    )
            self._record_relations(connection, ledger, observed, now)

        counts = {
            "snapshots": len(ledger.sources),
            "spans": len(ledger.chunks),
            "claims": len(ledger.claims),
        }
        for claim in ledger.claims.values():
            self.verify_claim(claim.claim_id, window=window)
        return counts

    def _insert_snapshot(
        self, connection: sqlite3.Connection, source: SourceDocument, now: str
    ) -> None:
        content_hash = source.content_hash or _sha256(source.content)
        row = connection.execute(
            "SELECT content_hash FROM source_snapshots WHERE snapshot_id = ?",
            (source.doc_id,),
        ).fetchone()
        if row is not None:
            if row["content_hash"] != content_hash:
                raise ValueError(
                    f"snapshot id collision with different content: {source.doc_id}"
                )
            return
        connection.execute(
            "INSERT INTO source_snapshots"
            " (snapshot_id, canonical_url, title, content, content_hash, provider,"
            " source_type, fetch_status, observed_at, published_at, metadata_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source.doc_id,
                source.canonical_url,
                source.source_title,
                source.content,
                content_hash,
                source.provider,
                source.source_type,
                source.fetch_status,
                _iso(source.retrieved_at),
                _iso(source.publish_date),
                json.dumps(source.metadata, ensure_ascii=False, default=str),
                now,
            ),
        )

    def _insert_span(
        self, connection: sqlite3.Connection, chunk: EvidenceChunk
    ) -> None:
        row = connection.execute(
            "SELECT quote, start_offset, end_offset FROM evidence_spans WHERE span_id = ?",
            (chunk.chunk_id,),
        ).fetchone()
        if row is not None:
            if (
                row["quote"] != chunk.text
                or row["start_offset"] != chunk.start_offset
                or row["end_offset"] != chunk.end_offset
            ):
                raise ValueError(
                    f"span id collision with different content: {chunk.chunk_id}"
                )
            return
        connection.execute(
            "INSERT INTO evidence_spans"
            " (span_id, snapshot_id, parent_span_id, heading, quote, start_offset,"
            " end_offset, offset_status, content_hash, extractor_version,"
            " year_hints_json, metric_hints_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chunk.chunk_id,
                chunk.document_id,
                chunk.parent_chunk_id,
                chunk.heading,
                chunk.text,
                chunk.start_offset,
                chunk.end_offset,
                chunk.offset_status,
                chunk.content_hash or _sha256(chunk.text),
                "source_contract_v1",
                json.dumps(chunk.year_hints, ensure_ascii=False),
                json.dumps(chunk.metric_hints, ensure_ascii=False),
            ),
        )

    def _insert_claim(
        self,
        connection: sqlite3.Connection,
        claim: AtomicClaim,
        observed: datetime | None,
        now: str,
    ) -> None:
        normalized_unit = self._normalized_unit(claim)
        connection.execute(
            "INSERT INTO claims"
            " (claim_id, statement, subject, predicate, value, unit, normalized_unit,"
            " region_id, scope, valid_time, observed_time, methodology, qualifier,"
            " verification_status, verification_reason, source_ids_json,"
            " evidence_chunk_ids_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(claim_id) DO UPDATE SET"
            " statement=excluded.statement, subject=excluded.subject,"
            " predicate=excluded.predicate, value=excluded.value, unit=excluded.unit,"
            " normalized_unit=excluded.normalized_unit,"
            " region_id=excluded.region_id, scope=excluded.scope,"
            " valid_time=excluded.valid_time, observed_time=excluded.observed_time,"
            " methodology=excluded.methodology, qualifier=excluded.qualifier,"
            " verification_status=excluded.verification_status,"
            " verification_reason=excluded.verification_reason,"
            " source_ids_json=excluded.source_ids_json,"
            " evidence_chunk_ids_json=excluded.evidence_chunk_ids_json",
            (
                claim.claim_id,
                claim.statement,
                claim.region_id,
                claim.metric_id,
                claim.value,
                claim.unit,
                normalized_unit,
                claim.region_id,
                claim.administrative_scope,
                claim.period,
                _iso(observed),
                claim.statistical_caliber,
                claim.series_version,
                self._stored_status(claim.verification_status),
                claim.verification_reason,
                json.dumps(claim.source_ids, ensure_ascii=False),
                json.dumps(claim.evidence_chunk_ids, ensure_ascii=False),
                now,
            ),
        )

    @staticmethod
    def _normalized_unit(claim: AtomicClaim) -> str:
        multiplier = _unit_multiplier(claim.unit)
        return f"{claim.unit}->万元" if multiplier is not None else claim.unit

    @staticmethod
    def _stored_status(status: str) -> str:
        try:
            return VerificationStatus(status.upper()).value
        except ValueError:
            return VerificationStatus.INSUFFICIENT.value

    @staticmethod
    def _claim_observed_at(
        ledger: EvidenceLedger, claim: AtomicClaim
    ) -> datetime | None:
        observed: list[datetime] = []
        for source_id in claim.source_ids:
            source = ledger.sources.get(source_id)
            if source is not None and source.retrieved_at is not None:
                observed.append(source.retrieved_at)
        return max(observed) if observed else None

    def _record_relations(
        self,
        connection: sqlite3.Connection,
        ledger: EvidenceLedger,
        observed: dict[str, datetime | None],
        now: str,
    ) -> None:
        claims = sorted(ledger.claims.values(), key=lambda item: item.claim_id)
        for index, left in enumerate(claims):
            for right in claims[index + 1 :]:
                relation = classify_claim_relation(
                    left,
                    right,
                    left_observed=observed.get(left.claim_id),
                    right_observed=observed.get(right.claim_id),
                )
                if relation is None:
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO claim_relations"
                    " (from_claim_id, to_claim_id, relation, rationale, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        relation.from_claim_id,
                        relation.to_claim_id,
                        relation.relation.value,
                        relation.rationale,
                        now,
                    ),
                )

    # ---------------------------------------------------------------- reads

    def load_ledger(self) -> EvidenceLedger:
        ledger = EvidenceLedger()
        with self._connect() as connection:
            snapshots = {
                row["snapshot_id"]: row
                for row in connection.execute("SELECT * FROM source_snapshots")
            }
            spans_by_snapshot: dict[str, list[EvidenceChunk]] = {}
            for row in connection.execute(
                "SELECT * FROM evidence_spans ORDER BY snapshot_id, start_offset, span_id"
            ):
                spans_by_snapshot.setdefault(row["snapshot_id"], []).append(
                    EvidenceChunk(
                        chunk_id=row["span_id"],
                        document_id=row["snapshot_id"],
                        parent_chunk_id=row["parent_span_id"],
                        text=row["quote"],
                        heading=row["heading"],
                        start_offset=row["start_offset"],
                        end_offset=row["end_offset"],
                        offset_status=row["offset_status"],
                        year_hints=json.loads(row["year_hints_json"]),
                        metric_hints=json.loads(row["metric_hints_json"]),
                        content_hash=row["content_hash"],
                    )
                )
            for snapshot_id, row in snapshots.items():
                ledger.add_source(
                    SourceDocument(
                        doc_id=snapshot_id,
                        canonical_url=row["canonical_url"],
                        source_title=row["title"],
                        content=row["content"],
                        content_hash=row["content_hash"],
                        publish_date=_parse_datetime(row["published_at"]),
                        retrieved_at=_parse_datetime(row["observed_at"]),
                        provider=row["provider"],
                        source_type=row["source_type"],
                        fetch_status=row["fetch_status"],
                        metadata=json.loads(row["metadata_json"]),
                        chunks=spans_by_snapshot.get(snapshot_id, []),
                    )
                )
            for row in connection.execute("SELECT * FROM claims ORDER BY claim_id"):
                ledger.add_claim(self._claim_from_row(row))
        return ledger

    @staticmethod
    def _claim_from_row(row: sqlite3.Row) -> AtomicClaim:
        return AtomicClaim(
            claim_id=row["claim_id"],
            statement=row["statement"],
            region_id=row["region_id"],
            metric_id=row["predicate"],
            value=row["value"],
            unit=row["unit"],
            period=row["valid_time"],
            administrative_scope=row["scope"],
            statistical_caliber=row["methodology"],
            series_version=row["qualifier"],
            source_ids=json.loads(row["source_ids_json"]),
            evidence_chunk_ids=json.loads(row["evidence_chunk_ids_json"]),
            verification_status=row["verification_status"].lower(),
            verification_reason=row["verification_reason"],
        )

    def get_claim(self, claim_id: str) -> AtomicClaim | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
            ).fetchone()
        return self._claim_from_row(row) if row is not None else None

    def get_snapshot(self, snapshot_id: str) -> SourceSnapshotRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        return self._snapshot_from_row(row) if row is not None else None

    def get_span(self, span_id: str) -> EvidenceSpanRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM evidence_spans WHERE span_id = ?", (span_id,)
            ).fetchone()
        return self._span_from_row(row) if row is not None else None

    def list_claims(self, *, run_id: str = "") -> list[AtomicClaim]:
        with self._connect() as connection:
            if run_id:
                rows = connection.execute(
                    "SELECT c.* FROM claims c JOIN findings f ON f.claim_id = c.claim_id"
                    " WHERE f.run_id = ? ORDER BY c.claim_id",
                    (run_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM claims ORDER BY claim_id"
                ).fetchall()
        return [self._claim_from_row(row) for row in rows]

    def list_snapshots(self) -> list[SourceSnapshotRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM source_snapshots ORDER BY snapshot_id"
            ).fetchall()
        return [self._snapshot_from_row(row) for row in rows]

    def list_run_snapshots(self, run_id: str) -> list[SourceSnapshotRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT n.* FROM source_snapshots n"
                " JOIN run_snapshots r ON r.snapshot_id = n.snapshot_id"
                " WHERE r.run_id = ? ORDER BY n.snapshot_id",
                (run_id,),
            ).fetchall()
        return [self._snapshot_from_row(row) for row in rows]

    @staticmethod
    def _snapshot_from_row(row: sqlite3.Row) -> SourceSnapshotRecord:
        return SourceSnapshotRecord(
            snapshot_id=row["snapshot_id"],
            canonical_url=row["canonical_url"],
            title=row["title"],
            content=row["content"],
            content_hash=row["content_hash"],
            provider=row["provider"],
            source_type=row["source_type"],
            fetch_status=row["fetch_status"],
            observed_at=_parse_datetime(row["observed_at"]),
            published_at=_parse_datetime(row["published_at"]),
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _span_from_row(row: sqlite3.Row) -> EvidenceSpanRecord:
        return EvidenceSpanRecord(
            span_id=row["span_id"],
            snapshot_id=row["snapshot_id"],
            quote=row["quote"],
            start_offset=row["start_offset"],
            end_offset=row["end_offset"],
            offset_status=row["offset_status"],
            heading=row["heading"],
            parent_span_id=row["parent_span_id"],
            extractor_version=row["extractor_version"],
            content_hash=row["content_hash"],
        )

    def get_chain(self, claim_id: str) -> ClaimChain:
        claim = self.get_claim(claim_id)
        if claim is None:
            raise KeyError(f"unknown claim: {claim_id}")
        with self._connect() as connection:
            edge_rows = connection.execute(
                "SELECT * FROM claim_evidence_edges WHERE claim_id = ?"
                " ORDER BY relation, span_id",
                (claim_id,),
            ).fetchall()
            relation_rows = connection.execute(
                "SELECT * FROM claim_relations"
                " WHERE from_claim_id = ? OR to_claim_id = ?"
                " ORDER BY from_claim_id, to_claim_id, relation",
                (claim_id, claim_id),
            ).fetchall()
            verification_row = connection.execute(
                "SELECT * FROM verification_records WHERE claim_id = ?"
                " ORDER BY created_at DESC LIMIT 1",
                (claim_id,),
            ).fetchone()
            links: list[EvidenceLink] = []
            for edge_row in edge_rows:
                span_row = connection.execute(
                    "SELECT * FROM evidence_spans WHERE span_id = ?",
                    (edge_row["span_id"],),
                ).fetchone()
                if span_row is None:
                    continue
                snapshot_row = connection.execute(
                    "SELECT * FROM source_snapshots WHERE snapshot_id = ?",
                    (span_row["snapshot_id"],),
                ).fetchone()
                if snapshot_row is None:
                    continue
                links.append(
                    EvidenceLink(
                        edge=ClaimEvidenceEdgeRecord(
                            claim_id=edge_row["claim_id"],
                            span_id=edge_row["span_id"],
                            relation=EdgeRelation(edge_row["relation"]),
                            rationale=edge_row["rationale"],
                            verifier_version=edge_row["verifier_version"],
                        ),
                        span=self._span_from_row(span_row),
                        snapshot=self._snapshot_from_row(snapshot_row),
                    )
                )
        relations = [
            ClaimRelationRecord(
                from_claim_id=row["from_claim_id"],
                to_claim_id=row["to_claim_id"],
                relation=ClaimRelationKind(row["relation"]),
                rationale=row["rationale"],
            )
            for row in relation_rows
        ]
        verification = (
            self._verification_from_row(verification_row)
            if verification_row is not None
            else None
        )
        return ClaimChain(
            claim=claim, links=links, relations=relations, verification=verification
        )

    def relations_for(self, claim_id: str) -> list[ClaimRelationRecord]:
        return self.get_chain(claim_id).relations

    # ------------------------------------------------------- verification

    def add_edge(self, edge: ClaimEvidenceEdgeRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO claim_evidence_edges"
                " (claim_id, span_id, relation, rationale, verifier_version, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    edge.claim_id,
                    edge.span_id,
                    edge.relation.value,
                    edge.rationale,
                    edge.verifier_version,
                    _utcnow().isoformat(),
                ),
            )

    def verify_claim(
        self,
        claim_id: str,
        *,
        verifier_version: str = DETERMINISTIC_VERIFIER_VERSION,
        window: tuple[date | None, date | None] | None = None,
    ) -> VerificationRecord:
        chain = self.get_chain(claim_id)
        claim = chain.claim
        checks: dict[str, Any] = {"edges": len(chain.links)}
        if window is not None:
            checks["requested_window"] = [
                window[0].isoformat() if window[0] else None,
                window[1].isoformat() if window[1] else None,
            ]
        integrity_ok: list[EvidenceLink] = []
        integrity_failures: list[str] = []
        for link in chain.links:
            ok, detail = self._check_span_integrity(link.span, link.snapshot)
            if ok:
                integrity_ok.append(link)
            else:
                integrity_failures.append(f"{link.span.span_id}:{detail}")
        checks["span_integrity_failures"] = integrity_failures

        supporting = [
            link
            for link in integrity_ok
            if link.edge.relation is not EdgeRelation.CONTRADICTS
        ]
        contradicting = [
            link
            for link in integrity_ok
            if link.edge.relation is EdgeRelation.CONTRADICTS
        ]
        checks["independent_support"] = self._independent_source_count(supporting)
        checks["supporting_edges"] = len(supporting)
        checks["contradicting_edges"] = len(contradicting)

        quote_text = "\n".join(link.span.quote for link in supporting)
        if quote_text:
            checks["value_present"] = (
                _quote_contains_value(quote_text, claim.value, claim.unit)
                if claim.value
                else None
            )
            checks["period_present"] = (
                claim.period in quote_text if claim.period else None
            )
            checks["region_present"] = (
                claim.region_id in quote_text if claim.region_id else None
            )
            checks["metric_present"] = (
                claim.metric_id in quote_text if claim.metric_id else None
            )
            checks["statement_in_quote"] = (
                _normalize_ws(claim.statement) in _normalize_ws(quote_text)
                if claim.statement
                else None
            )
        else:
            checks.update(
                {
                    "value_present": None,
                    "period_present": None,
                    "region_present": None,
                    "metric_present": None,
                    "statement_in_quote": None,
                }
            )

        status, reason = self._decide_status(claim, chain, checks, window=window)
        record = VerificationRecord(
            record_id=hashlib.sha256(
                f"{claim_id}|{verifier_version}|{_utcnow().isoformat()}".encode()
            ).hexdigest()[:24],
            claim_id=claim_id,
            status=status,
            deterministic_checks=checks,
            verifier_version=verifier_version,
        )
        self.save_verification(record, reason=reason)
        return record

    def _check_span_integrity(
        self, span: EvidenceSpanRecord, snapshot: SourceSnapshotRecord
    ) -> tuple[bool, str]:
        actual_hash = _sha256(snapshot.content)
        if snapshot.content_hash and snapshot.content_hash != actual_hash:
            return False, "snapshot_hash_mismatch"
        if span.content_hash and span.content_hash != _sha256(span.quote):
            return False, "span_hash_mismatch"
        if span.start_offset is not None and span.end_offset is not None:
            if not (0 <= span.start_offset <= span.end_offset <= len(snapshot.content)):
                return False, "offset_out_of_range"
            if snapshot.content[span.start_offset : span.end_offset] == span.quote:
                return True, "exact_offset"
            return False, "offset_quote_mismatch"
        if span.quote and span.quote in snapshot.content:
            return True, "quote_substring_unknown_offset"
        return False, "quote_not_in_snapshot"

    @staticmethod
    def _independent_source_count(links: list[EvidenceLink]) -> int:
        origins = {
            link.snapshot.canonical_url or link.snapshot.snapshot_id for link in links
        }
        return len(origins)

    def _decide_status(
        self,
        claim: AtomicClaim,
        chain: ClaimChain,
        checks: dict[str, Any],
        *,
        window: tuple[date | None, date | None] | None = None,
    ) -> tuple[VerificationStatus, str]:
        superseded = any(
            relation.relation is ClaimRelationKind.SUPERSEDES
            and relation.to_claim_id == claim.claim_id
            for relation in chain.relations
        )
        if superseded:
            return VerificationStatus.OUTDATED, "superseded_by_newer_claim"
        window_issue = self._window_issue(claim, window)
        if window_issue:
            return VerificationStatus.NOT_COMPARABLE, window_issue
        supports = int(checks.get("supporting_edges") or 0)
        contradicts = int(checks.get("contradicting_edges") or 0)
        if not supports:
            if checks.get("span_integrity_failures"):
                return VerificationStatus.INSUFFICIENT, "false_or_broken_reference"
            return VerificationStatus.INSUFFICIENT, "no_evidence"
        if claim.value and not claim.unit:
            return VerificationStatus.NOT_COMPARABLE, "numeric_value_without_unit"
        if claim.value and not claim.period:
            return VerificationStatus.NOT_COMPARABLE, "numeric_value_without_period"
        supported_conflicts = self._supported_claim_conflicts(claim, chain)
        checks["contradicting_supported_claims"] = supported_conflicts
        own_support = self._has_objective_support(chain)
        if own_support and supported_conflicts:
            return VerificationStatus.NEEDS_REVIEW, "conflicting_supported_evidence"
        if contradicts and not own_support:
            return VerificationStatus.CONTRADICTED, "contradicting_evidence"
        if own_support:
            if claim.value:
                return VerificationStatus.SUPPORTED, "value_and_span_verified"
            return VerificationStatus.SUPPORTED, "statement_exact_in_span"
        if checks.get("value_present") is False:
            return VerificationStatus.INSUFFICIENT, "value_not_in_quote"
        return VerificationStatus.INSUFFICIENT, "statement_not_in_span"

    @staticmethod
    def _window_issue(
        claim: AtomicClaim, window: tuple[date | None, date | None] | None
    ) -> str:
        if window is None:
            return ""
        start, end = window
        if start is None and end is None:
            return ""
        years = _years(claim.period)
        if not years:
            return "claim_period_missing_for_window"
        year = int(years[0])
        if start is not None and year < start.year:
            return f"outside_requested_window:{year}"
        if end is not None and year > end.year:
            return f"outside_requested_window:{year}"
        return ""

    def _supported_claim_conflicts(
        self, claim: AtomicClaim, chain: ClaimChain
    ) -> list[str]:
        """Claim ids that contradict this claim *and* have objective support.

        A claim whose value cannot be found in its own quote must not override a
        supported claim. Symmetry is required: both sides are evaluated with the
        same deterministic support test, independent of stored status.
        """
        conflicts: list[str] = []
        for relation in chain.relations:
            if relation.relation is not ClaimRelationKind.CONTRADICTS:
                continue
            other_id = (
                relation.to_claim_id
                if relation.from_claim_id == claim.claim_id
                else relation.from_claim_id
            )
            if other_id == claim.claim_id:
                continue
            other_chain = self.get_chain(other_id)
            if self._has_objective_support(other_chain):
                conflicts.append(other_id)
        return sorted(set(conflicts))

    def _has_objective_support(self, chain: ClaimChain) -> bool:
        claim = chain.claim
        supporting = []
        for link in chain.links:
            if link.edge.relation is EdgeRelation.CONTRADICTS:
                continue
            ok, _ = self._check_span_integrity(link.span, link.snapshot)
            if ok:
                supporting.append(link)
        if not supporting:
            return False
        quote = "\n".join(link.span.quote for link in supporting)
        if claim.value:
            if not _quote_contains_value(quote, claim.value, claim.unit):
                return False
            if not claim.statement and not claim.metric_id:
                return True
            return (
                _normalize_ws(claim.statement) in _normalize_ws(quote)
                if claim.statement
                else False
            ) or (bool(claim.metric_id) and claim.metric_id in quote)
        return _normalize_ws(claim.statement) in _normalize_ws(quote)

    def save_verification(
        self, record: VerificationRecord, *, reason: str = ""
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO verification_records"
                " (record_id, claim_id, status, deterministic_checks_json,"
                " judge_assessment_json, uncertainty, human_review_json,"
                " verifier_version, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.record_id,
                    record.claim_id,
                    record.status.value,
                    json.dumps(record.deterministic_checks, ensure_ascii=False, default=str),
                    json.dumps(record.judge_assessment, ensure_ascii=False)
                    if record.judge_assessment is not None
                    else None,
                    record.uncertainty,
                    json.dumps(record.human_review, ensure_ascii=False)
                    if record.human_review is not None
                    else None,
                    record.verifier_version,
                    record.created_at.isoformat(),
                ),
            )
            connection.execute(
                "UPDATE claims SET verification_status = ?, verification_reason = ?"
                " WHERE claim_id = ?",
                (record.status.value, reason, record.claim_id),
            )

    @staticmethod
    def _verification_from_row(row: sqlite3.Row) -> VerificationRecord:
        return VerificationRecord(
            record_id=row["record_id"],
            claim_id=row["claim_id"],
            status=VerificationStatus(row["status"]),
            deterministic_checks=json.loads(row["deterministic_checks_json"]),
            judge_assessment=json.loads(row["judge_assessment_json"])
            if row["judge_assessment_json"]
            else None,
            uncertainty=row["uncertainty"],
            human_review=json.loads(row["human_review_json"])
            if row["human_review_json"]
            else None,
            verifier_version=row["verifier_version"],
            created_at=_parse_datetime(row["created_at"]) or _utcnow(),
        )

    # ---------------------------------------------------------------- findings

    def save_findings(self, run_id: str, findings: list[FindingRecord]) -> None:
        with self._connect() as connection:
            for finding in findings:
                connection.execute(
                    "INSERT OR REPLACE INTO findings"
                    " (finding_id, run_id, claim_id, section, text, status, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        finding.finding_id,
                        run_id,
                        finding.claim_id,
                        finding.section,
                        finding.text,
                        finding.status.value,
                        finding.created_at.isoformat(),
                    ),
                )

    def list_findings(self, run_id: str) -> list[VerifiedFinding]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM findings WHERE run_id = ? ORDER BY finding_id",
                (run_id,),
            ).fetchall()
        findings: list[VerifiedFinding] = []
        for row in rows:
            finding = FindingRecord(
                finding_id=row["finding_id"],
                run_id=row["run_id"],
                claim_id=row["claim_id"],
                section=row["section"],
                text=row["text"],
                status=VerificationStatus(row["status"]),
                created_at=_parse_datetime(row["created_at"]) or _utcnow(),
            )
            findings.append(
                VerifiedFinding(finding=finding, chain=self.get_chain(row["claim_id"]))
            )
        return findings

    # --------------------------------------------------------------- integrity

    def integrity_report(self) -> list[SpanIntegrityIssue]:
        issues: list[SpanIntegrityIssue] = []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT s.*, n.content_hash AS snapshot_hash, n.content AS snapshot_content,"
                " n.snapshot_id AS snapshot_key"
                " FROM evidence_spans s JOIN source_snapshots n"
                " ON n.snapshot_id = s.snapshot_id"
            ).fetchall()
        snapshots: dict[str, SourceSnapshotRecord] = {}
        for row in rows:
            snapshot_id = row["snapshot_key"]
            snapshot = snapshots.get(snapshot_id)
            if snapshot is None:
                stored = self.get_snapshot(snapshot_id)
                if stored is None:
                    continue
                snapshot = stored
                snapshots[snapshot_id] = snapshot
            ok, detail = self._check_span_integrity(self._span_from_row(row), snapshot)
            if not ok:
                issues.append(
                    SpanIntegrityIssue(
                        span_id=row["span_id"],
                        snapshot_id=snapshot_id,
                        issue=detail,
                    )
                )
        return issues
