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
from .claim_region import classify_claim_region
from .ledger import EvidenceLedger
from .measure import data_years, derive_measure_key, infer_period
from .numeric_support import numeric_context_matches
from .source_contract import meets_source_credibility_threshold
from .source_identity import source_groups

SCHEMA_VERSION = 3
_UNBOUND_EVIDENCE = "run_evidence_unavailable"
DETERMINISTIC_VERIFIER_VERSION = "deterministic_v3_source_credibility"

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
    # A later import can be less credible than the immutable source snapshot.
    source_credibility_eligible: bool = True


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
    run_id: str = ""
    reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceLink(BaseModel):
    edge: ClaimEvidenceEdgeRecord
    span: EvidenceSpanRecord
    snapshot: SourceSnapshotRecord


def _eligible_source(link: EvidenceLink) -> bool:
    return link.edge.source_credibility_eligible and meets_source_credibility_threshold(
        link.snapshot.metadata, allow_unscored=True,
    )


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
    # Every question slot whose evidence pack selected this Claim. The Claim and its
    # verification stay global; a slot link only says "considered for this question".
    slot_ids: list[str] = Field(default_factory=list)
    text: str = ""
    status: VerificationStatus = VerificationStatus.INSUFFICIENT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def linked_slot_ids(self) -> list[str]:
        """Slot links, falling back to the single legacy section for older rows."""
        return list(self.slot_ids) or ([self.section] if self.section else [])


class VerifiedFinding(BaseModel):
    finding: FindingRecord
    chain: ClaimChain

    def with_verification_status(
        self, status: VerificationStatus, reason: str, *, checks: dict[str, Any] | None = None,
    ) -> VerifiedFinding:
        record = self.chain.verification
        if record is not None:
            record = record.model_copy(update={
                "status": status, "reason": reason,
                "deterministic_checks": record.deterministic_checks if checks is None else checks,
            })
        return self.model_copy(update={
            "finding": self.finding.model_copy(update={"status": status}),
            "chain": self.chain.model_copy(update={
                "claim": self.chain.claim.model_copy(update={
                    "verification_status": status.value.lower(), "verification_reason": reason,
                }),
                "verification": record,
            }),
        })


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
    """Check a numeric value without requiring identical formatting.

    Substring matching is boundary-aware: a claim value of ``20`` must not match
    ``200``. Numeric tokens are then compared with unit conversion support.
    """
    normalized_quote = _normalize_ws(quote)
    forms = _value_forms(value, unit)
    if unit:
        forms = {form for form in forms if unit in form}
    for form in forms:
        start = normalized_quote.find(form)
        while start != -1:
            end = start + len(form)
            before = normalized_quote[start - 1] if start > 0 else ""
            after = normalized_quote[end] if end < len(normalized_quote) else ""
            if (
                not before.isdigit()
                and before != "."
                and not after.isdigit()
                and after != "."
            ):
                return True
            start = normalized_quote.find(form, start + 1)
    target = _decimal(value)
    if target is None:
        return False
    target = abs(target)  # Direction/sign is checked by numeric_context_matches.
    target_unit_multiplier = _unit_multiplier(unit)
    for match in _NUMERIC_RE.finditer(quote):
        found = _decimal(match.group(1))
        if found is None:
            continue
        found_unit = match.group(2) or ""
        if not unit:
            if found == target:
                return True
            continue
        if found_unit == unit and found == target:
            return True
        if found_unit and target_unit_multiplier is not None:
            found_multiplier = _unit_multiplier(found_unit)
            if (
                found_multiplier is not None
                and found * found_multiplier
                == target * target_unit_multiplier
            ):
                return True
    return False


def _claim_supported_by_quote(
    claim: AtomicClaim,
    quote: str,
    *,
    title: str = "",
    url: str = "",
) -> bool:
    """Whether one exact quote (plus source metadata) supports the claim.

    A single span must carry the region, period, value/unit, and statement or
    metric. Values and metrics found in different spans do not compose into
    support.
    """
    evidence_text = f"{quote}\n{title}\n{url}"
    if claim.region_id:
        if claim.region_id not in evidence_text:
            return False
        attribution = classify_claim_region(claim.region_id, statement=claim.statement)
        if attribution.source == "claim" and attribution.excluded_from_target and attribution.region_id != claim.region_id:
            return False
    claim_years = set(_years(claim.period))
    if not claim_years:
        return False
    quote_years = set(data_years(quote))
    report_year = infer_period('', title=title)
    if report_year:
        quote_years.add(report_year)
    if not (claim_years & quote_years):
        return False
    if claim.value:
        if not _quote_contains_value(quote, claim.value, claim.unit):
            return False
        if not numeric_context_matches(claim, quote, title=title, url=url):
            return False
        if not claim.statement and not claim.metric_id:
            return True
        statement_ok = (
            _normalize_ws(claim.statement) in _normalize_ws(quote)
            if claim.statement
            else False
        )
        metric_ok = bool(claim.metric_id) and claim.metric_id in quote
        return statement_ok or metric_ok
    if not claim.statement:
        return False
    return _normalize_ws(claim.statement) in _normalize_ws(quote)


def _integrity_check(
    *,
    quote: str,
    start_offset: int | None,
    end_offset: int | None,
    span_hash: str,
    content: str,
    content_hash: str,
) -> tuple[bool, str]:
    actual_hash = _sha256(content)
    if content_hash and content_hash != actual_hash:
        return False, "snapshot_hash_mismatch"
    if span_hash and span_hash != _sha256(quote):
        return False, "span_hash_mismatch"
    if start_offset is not None and end_offset is not None:
        if not (0 <= start_offset <= end_offset <= len(content)):
            return False, "offset_out_of_range"
        if content[start_offset:end_offset] == quote:
            return True, "exact_offset"
        return False, "offset_quote_mismatch"
    if quote and quote in content:
        return True, "quote_substring_unknown_offset"
    return False, "quote_not_in_snapshot"


def claim_identity(claim: AtomicClaim) -> tuple[str, ...]:
    return (
        claim.region_id,
        claim.metric_id,
        claim.period,
        claim.administrative_scope,
        claim.statistical_caliber,
        claim.series_version,
    )


def claim_measure_key(claim: AtomicClaim) -> str:
    if claim.measure_id:
        return claim.measure_id
    return derive_measure_key(claim.statement, value=claim.value)


def classify_claim_relation(
    left: AtomicClaim,
    right: AtomicClaim,
    *,
    left_observed: datetime | None = None,
    right_observed: datetime | None = None,
    use_measure_identity: bool = True,
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
    left_measure = claim_measure_key(left)
    right_measure = claim_measure_key(right)
    if (
        use_measure_identity
        and left_measure
        and right_measure
        and left_measure != right_measure
    ):
        return ClaimRelationRecord(
            from_claim_id=left.claim_id,
            to_claim_id=right.claim_id,
            relation=ClaimRelationKind.RELATED,
            rationale=f"different_measure:{left_measure}|{right_measure}",
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
                    measure_id TEXT NOT NULL DEFAULT '',
                    value TEXT NOT NULL DEFAULT '',
                    unit TEXT NOT NULL DEFAULT '',
                    normalized_unit TEXT NOT NULL DEFAULT '',
                    region_id TEXT NOT NULL DEFAULT '',
                    region_source TEXT NOT NULL DEFAULT '',
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
                    run_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (from_claim_id, to_claim_id, relation, run_id)
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
                    run_id TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
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
                CREATE TABLE IF NOT EXISTS finding_slots (
                    finding_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (finding_id, slot_id)
                );
                CREATE INDEX IF NOT EXISTS idx_finding_slots_run ON finding_slots(run_id);
                CREATE TABLE IF NOT EXISTS run_snapshots (
                    run_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
                    PRIMARY KEY (run_id, snapshot_id)
                );
                CREATE TABLE IF NOT EXISTS run_claims (
                    run_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                    claim_json TEXT,
                    edges_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, claim_id)
                );
                CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
                CREATE INDEX IF NOT EXISTS idx_spans_snapshot ON evidence_spans(snapshot_id);
                CREATE INDEX IF NOT EXISTS idx_run_snapshots_run ON run_snapshots(run_id);
                """
            )
            relation_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(claim_relations)")
            }
            if "run_id" not in relation_columns:
                connection.execute("PRAGMA foreign_keys = OFF")
                connection.executescript(
                    """
                    ALTER TABLE claim_relations RENAME TO claim_relations_old;
                    CREATE TABLE claim_relations (
                        from_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                        to_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                        relation TEXT NOT NULL,
                        rationale TEXT NOT NULL DEFAULT '',
                        run_id TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (from_claim_id, to_claim_id, relation, run_id)
                    );
                    INSERT INTO claim_relations
                        (from_claim_id, to_claim_id, relation, rationale, run_id, created_at)
                    SELECT from_claim_id, to_claim_id, relation, rationale, '', created_at
                    FROM claim_relations_old;
                    DROP TABLE claim_relations_old;
                    """
                )
                connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            for table, column, ddl in (
                ("claims", "measure_id", "TEXT NOT NULL DEFAULT ''"),
                ("claims", "region_source", "TEXT NOT NULL DEFAULT ''"),
                ("verification_records", "run_id", "TEXT NOT NULL DEFAULT ''"),
                ("verification_records", "reason", "TEXT NOT NULL DEFAULT ''"),
            ):
                columns = {
                    row[1]
                    for row in connection.execute(f"PRAGMA table_info({table})")
                }
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"
                    )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_verification_claim_run"
                " ON verification_records(claim_id, run_id, created_at DESC)"
            )
            if connection.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
                self._migrate_run_claims(connection)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _migrate_run_claims(self, connection: sqlite3.Connection) -> None:
        memberships = connection.execute(
            "SELECT run_id, claim_id, MIN(created_at) AS bound_at FROM ("
            " SELECT run_id, claim_id, created_at FROM findings"
            " UNION ALL SELECT run_id, claim_id, created_at FROM verification_records"
            ") WHERE run_id <> '' GROUP BY run_id, claim_id"
        ).fetchall()
        for row in memberships:
            self._bind_legacy_claim(connection, row["run_id"], row["claim_id"], row["bound_at"])

    @staticmethod
    def _write_claim_version(
        connection: sqlite3.Connection, run_id: str, claim_id: str,
        claim: AtomicClaim | None, edges: list[ClaimEvidenceEdgeRecord],
    ) -> None:
        connection.execute(
            "INSERT INTO run_claims (run_id, claim_id, claim_json, edges_json) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(run_id, claim_id) DO UPDATE SET"
            " claim_json=excluded.claim_json, edges_json=excluded.edges_json",
            (
                run_id, claim_id, claim.model_dump_json() if claim is not None else None,
                json.dumps([edge.model_dump(mode="json") for edge in edges]),
            ),
        )

    def _bind_legacy_claim(
        self, connection: sqlite3.Connection, run_id: str, claim_id: str, bound_at: str,
    ) -> None:
        """Freeze a legacy finding's chain if its original ownership is recoverable."""
        if connection.execute(
            "SELECT 1 FROM run_claims WHERE run_id = ? AND claim_id = ?", (run_id, claim_id),
        ).fetchone():
            return
        snapshots = {row[0] for row in connection.execute(
            "SELECT snapshot_id FROM run_snapshots WHERE run_id = ?", (run_id,),
        )}
        unscoped = connection.execute(
            "SELECT claim_json, edges_json FROM run_claims WHERE run_id = '' AND claim_id = ?",
            (claim_id,),
        ).fetchone()
        legacy_verification = connection.execute(
            "SELECT * FROM verification_records WHERE run_id = '' AND claim_id = ? AND created_at <= ?"
            " ORDER BY created_at DESC, record_id DESC LIMIT 1", (claim_id, bound_at),
        ).fetchone()
        has_other_run = connection.execute(
            "SELECT 1 FROM (SELECT run_id FROM findings WHERE claim_id = ?"
            " UNION SELECT run_id FROM verification_records WHERE claim_id = ?)"
            " WHERE run_id NOT IN ('', ?) LIMIT 1", (claim_id, claim_id, run_id),
        ).fetchone() is not None
        if not snapshots and unscoped is not None and legacy_verification is not None:
            claim = AtomicClaim.model_validate_json(unscoped["claim_json"])
            edges = [ClaimEvidenceEdgeRecord.model_validate(edge) for edge in json.loads(unscoped["edges_json"])]
        else:
            row = connection.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown claim: {claim_id}")
            # An earlier edge may be present in multiple runs. A later write
            # can still replace the global Claim while leaving that edge intact.
            newer_foreign_verification = connection.execute(
                "SELECT 1 FROM verification_records WHERE claim_id = ? AND run_id <> ?"
                " AND created_at >= ? LIMIT 1", (claim_id, run_id, bound_at),
            ).fetchone()
            if newer_foreign_verification is not None:
                self._write_claim_version(connection, run_id, claim_id, None, [])
                return
            claim = self._claim_from_row(row)
            edge_rows = connection.execute(
                "SELECT e.*, s.snapshot_id FROM claim_evidence_edges e"
                " JOIN evidence_spans s ON s.span_id = e.span_id"
                " WHERE e.claim_id = ? AND e.created_at <= ? ORDER BY e.relation, e.span_id",
                (claim_id, bound_at),
            ).fetchall()
            if snapshots:
                edge_rows = [edge for edge in edge_rows if edge["snapshot_id"] in snapshots]
            elif has_other_run or legacy_verification is None or row["created_at"] > bound_at:
                edge_rows = []
            if has_other_run:
                edge_rows = [edge for edge in edge_rows if edge["span_id"] in claim.evidence_chunk_ids]
            authorized_spans = {edge["span_id"] for edge in edge_rows}
            authorized_sources = snapshots or {edge["snapshot_id"] for edge in edge_rows}
            if (not set(claim.evidence_chunk_ids) <= authorized_spans
                    or not set(claim.source_ids) <= authorized_sources
                    or not edge_rows):
                self._write_claim_version(connection, run_id, claim_id, None, [])
                return
            edges = [self._edge_from_row(edge) for edge in edge_rows]
        self._write_claim_version(connection, run_id, claim_id, claim, edges)
        if not snapshots and legacy_verification is not None:
            record = self._verification_from_row(legacy_verification)
            record_id = _sha256(f"legacy:{run_id}:{record.record_id}")[:24]
            record = record.model_copy(update={"run_id": run_id, "record_id": record_id})
            self._insert_verification(connection, record, record.reason, update_global=False)

    # ---------------------------------------------------------------- writes

    def save_ledger(
        self,
        ledger: EvidenceLedger,
        *,
        run_id: str = "",
        window: tuple[date | None, date | None] | None = None,
        use_measure_identity: bool = True,
        target_region: str = "",
    ) -> dict[str, int]:
        """Persist a ledger, classify claim relations, and record verification."""
        now = _utcnow().isoformat()
        observed: dict[str, datetime | None] = {}
        supported_ids: set[str] = set()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            credible_source_ids: set[str] = set()
            for source in ledger.sources.values():
                if self._insert_snapshot(connection, source, now):
                    credible_source_ids.add(source.doc_id)
                if run_id:
                    connection.execute(
                        "INSERT OR IGNORE INTO run_snapshots (run_id, snapshot_id)"
                        " VALUES (?, ?)",
                        (run_id, source.doc_id),
                    )
            for chunk in ledger.chunks.values():
                self._insert_span(connection, chunk)
            for claim in ledger.claims.values():
                edges = [
                    ClaimEvidenceEdgeRecord(
                        claim_id=claim.claim_id, span_id=chunk_id,
                        rationale="ledger_evidence_link", verifier_version="ledger_adapter_v1",
                        source_credibility_eligible=ledger.chunks[chunk_id].document_id in credible_source_ids,
                    )
                    for chunk_id in sorted(set(claim.evidence_chunk_ids))
                    if chunk_id in ledger.chunks
                    and ledger.chunks[chunk_id].document_id in ledger.sources
                ]
                # Use only observations bound to immutable, verifiable quotes.
                links = self._links_for_edges(
                    connection, [edge for edge in edges if edge.source_credibility_eligible],
                )
                supporting_dates = [
                    link.snapshot.observed_at
                    for link in self.supporting_links(ClaimChain(claim=claim, links=links))
                ]
                claim_observed = max((at for at in supporting_dates if at is not None), default=None)
                observed[claim.claim_id] = claim_observed
                if (
                    supporting_dates
                    and not self._region_issue(claim, {}, target_region)
                    and not self._window_issue(claim, window)
                ):
                    supported_ids.add(claim.claim_id)
                self._insert_claim(connection, claim, claim_observed, now)
                connection.executemany(
                    "INSERT OR IGNORE INTO claim_evidence_edges"
                    " (claim_id, span_id, relation, rationale, verifier_version, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    [(e.claim_id, e.span_id, e.relation.value, e.rationale, e.verifier_version, now) for e in edges],
                )
                self._write_claim_version(connection, run_id, claim.claim_id, claim, edges)
            self._record_relations(
                connection,
                ledger,
                observed,
                now,
                run_id=run_id,
                use_measure_identity=use_measure_identity,
            )
            for claim in ledger.claims.values():
                self._verify_claim(
                    connection, claim.claim_id, window=window, supported_ids=supported_ids,
                    run_id=run_id, target_region=target_region,
                )
        return {
            "snapshots": len(ledger.sources),
            "spans": len(ledger.chunks),
            "claims": len(ledger.claims),
        }

    @staticmethod
    def _source_credibility_row(connection: sqlite3.Connection, snapshot_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT content_hash, metadata_json FROM source_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()

    @staticmethod
    def _source_assessments_eligible(source: SourceDocument, archived: sqlite3.Row | None) -> bool:
        return meets_source_credibility_threshold(source.metadata, allow_unscored=True) and (
            archived is None
            or meets_source_credibility_threshold(json.loads(archived["metadata_json"]), allow_unscored=True)
        )

    def source_credibility_eligible(self, source: SourceDocument) -> bool:
        """Check incoming and immutable ratings before persisting a candidate."""
        with self._connect() as connection:
            archived = self._source_credibility_row(connection, source.doc_id)
        return self._source_assessments_eligible(source, archived)

    def _insert_snapshot(
        self, connection: sqlite3.Connection, source: SourceDocument, now: str
    ) -> bool:
        """Save the snapshot if new and require both assessments to qualify."""
        content_hash = source.content_hash or _sha256(source.content)
        row = self._source_credibility_row(connection, source.doc_id)
        eligible = self._source_assessments_eligible(source, row)
        if row is not None:
            if row["content_hash"] != content_hash:
                raise ValueError(
                    f"snapshot id collision with different content: {source.doc_id}"
                )
            return eligible
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
        return eligible

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
            " (claim_id, statement, subject, predicate, measure_id, value, unit,"
            " normalized_unit, region_id, region_source, scope, valid_time, observed_time, methodology,"
            " qualifier, verification_status, verification_reason, source_ids_json,"
            " evidence_chunk_ids_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(claim_id) DO UPDATE SET"
            " statement=excluded.statement, subject=excluded.subject,"
            " predicate=excluded.predicate, measure_id=excluded.measure_id,"
            " value=excluded.value, unit=excluded.unit,"
            " normalized_unit=excluded.normalized_unit,"
            " region_id=excluded.region_id, region_source=excluded.region_source,"
            " scope=excluded.scope,"
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
                claim.measure_id,
                claim.value,
                claim.unit,
                normalized_unit,
                claim.region_id,
                claim.region_source,
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

    def _record_relations(
        self,
        connection: sqlite3.Connection,
        ledger: EvidenceLedger,
        observed: dict[str, datetime | None],
        now: str,
        *,
        run_id: str = "",
        use_measure_identity: bool = True,
    ) -> None:
        claims = sorted(ledger.claims.values(), key=lambda item: item.claim_id)
        for index, left in enumerate(claims):
            for right in claims[index + 1 :]:
                relation = classify_claim_relation(
                    left,
                    right,
                    left_observed=observed.get(left.claim_id),
                    right_observed=observed.get(right.claim_id),
                    use_measure_identity=use_measure_identity,
                )
                if relation is None:
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO claim_relations"
                    " (from_claim_id, to_claim_id, relation, rationale, run_id, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        relation.from_claim_id,
                        relation.to_claim_id,
                        relation.relation.value,
                        relation.rationale,
                        run_id,
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
            region_source=row["region_source"],
            metric_id=row["predicate"],
            measure_id=row["measure_id"],
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
        if run_id:
            return sorted(
                (item.chain.claim for item in self.list_findings(run_id)),
                key=lambda claim: claim.claim_id,
            )
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM claims ORDER BY claim_id").fetchall()
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
                "SELECT n.* FROM source_snapshots n WHERE n.snapshot_id IN ("
                " SELECT snapshot_id FROM run_snapshots WHERE run_id = ?"
                " UNION SELECT s.snapshot_id FROM run_claims c JOIN json_each(c.edges_json) e"
                " JOIN evidence_spans s ON s.span_id = json_extract(e.value, '$.span_id')"
                " WHERE c.run_id = ?"
                ") ORDER BY n.snapshot_id",
                (run_id, run_id),
            ).fetchall()
        return [self._snapshot_from_row(row) for row in rows]

    def list_run_claims(self, run_id: str) -> list[AtomicClaim]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT c.claim_json, v.status, v.reason FROM run_claims c"
                " JOIN verification_records v ON v.record_id = ("
                "   SELECT record_id FROM verification_records"
                "   WHERE run_id = c.run_id AND claim_id = c.claim_id"
                "   ORDER BY created_at DESC, record_id DESC LIMIT 1"
                " ) WHERE c.run_id = ? AND c.claim_json IS NOT NULL ORDER BY c.claim_id",
                (run_id,),
            ).fetchall()
        return [
            AtomicClaim.model_validate_json(row["claim_json"]).model_copy(update={
                "verification_status": row["status"].lower(), "verification_reason": row["reason"],
            })
            for row in rows
        ]

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

    @staticmethod
    def _edge_from_row(row: sqlite3.Row) -> ClaimEvidenceEdgeRecord:
        return ClaimEvidenceEdgeRecord(
            claim_id=row["claim_id"], span_id=row["span_id"],
            relation=EdgeRelation(row["relation"]), rationale=row["rationale"],
            verifier_version=row["verifier_version"],
        )

    def get_chain(self, claim_id: str, *, run_id: str = "") -> ClaimChain:
        with self._connect() as connection:
            connection.execute("BEGIN")
            return self._get_chain(connection, claim_id, run_id)

    def _get_chain(self, connection: sqlite3.Connection, claim_id: str, run_id: str) -> ClaimChain:
        version = connection.execute(
            "SELECT claim_json, edges_json FROM run_claims WHERE run_id = ? AND claim_id = ?",
            (run_id, claim_id),
        ).fetchone()
        if version is None:
            if run_id:
                raise KeyError(f"unknown claim in run {run_id}: {claim_id}")
            row = connection.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown claim: {claim_id}")
            claim = self._claim_from_row(row)
            edges = [self._edge_from_row(row) for row in connection.execute(
                "SELECT * FROM claim_evidence_edges WHERE claim_id = ? ORDER BY relation, span_id",
                (claim_id,),
            )]
        else:
            if version["claim_json"] is None:
                finding = connection.execute(
                    "SELECT text FROM findings WHERE run_id = ? AND claim_id = ? ORDER BY finding_id LIMIT 1",
                    (run_id, claim_id),
                ).fetchone()
                return ClaimChain(claim=AtomicClaim(
                    claim_id=claim_id, statement=finding["text"] if finding else "",
                    verification_status="insufficient", verification_reason=_UNBOUND_EVIDENCE,
                ))
            claim = AtomicClaim.model_validate_json(version["claim_json"])
            edges = [ClaimEvidenceEdgeRecord.model_validate(edge) for edge in json.loads(version["edges_json"])]
        relation_rows = connection.execute(
            "SELECT * FROM claim_relations"
            " WHERE (from_claim_id = ? OR to_claim_id = ?) AND (? OR run_id = ?)"
            " ORDER BY from_claim_id, to_claim_id, relation",
            (claim_id, claim_id, version is None, run_id),
        )
        verification_row = connection.execute(
            "SELECT * FROM verification_records WHERE claim_id = ? AND (? OR run_id = ?)"
            " ORDER BY created_at DESC, record_id DESC LIMIT 1",
            (claim_id, version is None, run_id),
        ).fetchone()
        links = self._links_for_edges(connection, edges)
        relations = [
            ClaimRelationRecord(
                from_claim_id=row["from_claim_id"], to_claim_id=row["to_claim_id"],
                relation=ClaimRelationKind(row["relation"]), rationale=row["rationale"],
            )
            for row in relation_rows
        ]
        verification = self._verification_from_row(verification_row) if verification_row is not None else None
        if verification is not None and version is not None:
            claim = claim.model_copy(update={
                "verification_status": verification.status.value.lower(), "verification_reason": verification.reason,
            })
        return ClaimChain(claim=claim, links=links, relations=relations, verification=verification)

    def _links_for_edges(
        self, connection: sqlite3.Connection, edges: list[ClaimEvidenceEdgeRecord],
    ) -> list[EvidenceLink]:
        links: list[EvidenceLink] = []
        for edge in edges:
            span_row = connection.execute(
                "SELECT * FROM evidence_spans WHERE span_id = ?", (edge.span_id,),
            ).fetchone()
            if span_row is None:
                continue
            snapshot_row = connection.execute(
                "SELECT * FROM source_snapshots WHERE snapshot_id = ?", (span_row["snapshot_id"],),
            ).fetchone()
            if snapshot_row is not None:
                links.append(EvidenceLink(
                    edge=edge, span=self._span_from_row(span_row), snapshot=self._snapshot_from_row(snapshot_row),
                ))
        return links

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
            version = connection.execute(
                "SELECT claim_json, edges_json FROM run_claims WHERE run_id = '' AND claim_id = ?",
                (edge.claim_id,),
            ).fetchone()
            if version is not None:
                edges = [ClaimEvidenceEdgeRecord.model_validate(e) for e in json.loads(version["edges_json"])]
                if not any(e.span_id == edge.span_id and e.relation is edge.relation for e in edges):
                    edges.append(edge)
                    edges.sort(key=lambda item: (item.relation, item.span_id))
                    self._write_claim_version(
                        connection, "", edge.claim_id, AtomicClaim.model_validate_json(version["claim_json"]), edges,
                    )

    def verify_claim(
        self,
        claim_id: str,
        *,
        verifier_version: str = DETERMINISTIC_VERIFIER_VERSION,
        window: tuple[date | None, date | None] | None = None,
        supported_ids: set[str] | None = None,
        run_id: str = "",
        target_region: str = "",
    ) -> VerificationRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._verify_claim(
                connection, claim_id, verifier_version=verifier_version, window=window,
                supported_ids=supported_ids, run_id=run_id, target_region=target_region,
            )

    def _verify_claim(
        self,
        connection: sqlite3.Connection,
        claim_id: str,
        *,
        verifier_version: str = DETERMINISTIC_VERIFIER_VERSION,
        window: tuple[date | None, date | None] | None = None,
        supported_ids: set[str] | None = None,
        run_id: str = "",
        target_region: str = "",
    ) -> VerificationRecord:
        chain = self._get_chain(connection, claim_id, run_id)
        if supported_ids is None:
            supported_ids = self._related_support_ids(
                connection, [chain], run_id=run_id, window=window, target_region=target_region,
            )
        status, reason, checks = self._evaluate_claim(
            chain, window=window, supported_ids=supported_ids, target_region=target_region,
        )
        record = VerificationRecord(
            record_id=hashlib.sha256(
                f"{run_id}|{claim_id}|{verifier_version}|{_utcnow().isoformat()}".encode()
            ).hexdigest()[:24],
            claim_id=claim_id,
            status=status,
            deterministic_checks=checks,
            verifier_version=verifier_version,
            run_id=run_id,
            reason=reason,
        )
        self._insert_verification(connection, record, reason)
        return record

    def _evaluate_claim(
        self, chain: ClaimChain, *, window: tuple[date | None, date | None] | None,
        supported_ids: set[str], target_region: str,
    ) -> tuple[VerificationStatus, str, dict[str, Any]]:
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
            link for link in integrity_ok
            if link.edge.relation is EdgeRelation.CONTRADICTS and _eligible_source(link)
        ]
        valid_support = [
            link for link in supporting
            if _claim_supported_by_quote(claim, link.span.quote,
                                         title=link.snapshot.title, url=link.snapshot.canonical_url)
        ]
        eligible_support = [link for link in valid_support if _eligible_source(link)]
        checks["independent_support"] = self._independent_source_count(eligible_support)
        checks["source_groups"] = source_groups(link.snapshot for link in eligible_support)
        checks["quote_supporting_edges"] = len(valid_support)
        checks["eligible_supporting_edges"] = len(eligible_support)
        checks["supporting_edges"] = len(supporting)
        checks["contradicting_edges"] = len(contradicting)
        checks["claim_region"] = claim.region_id
        checks["claim_region_source"] = claim.region_source
        if target_region:
            checks["target_region"] = target_region

        quote_text = "\n".join(link.span.quote for link in supporting)
        region_text = "\n".join(
            f"{link.span.quote}\n{link.snapshot.title}\n{link.snapshot.canonical_url}"
            for link in supporting
        )
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
                claim.region_id in region_text if claim.region_id else None
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

        status, reason = self._decide_status(
            claim, chain, checks, window=window, supported_ids=supported_ids, target_region=target_region,
        )
        return status, reason, checks

    def _check_span_integrity(
        self, span: EvidenceSpanRecord, snapshot: SourceSnapshotRecord
    ) -> tuple[bool, str]:
        return _integrity_check(
            quote=span.quote,
            start_offset=span.start_offset,
            end_offset=span.end_offset,
            span_hash=span.content_hash,
            content=snapshot.content,
            content_hash=snapshot.content_hash,
        )

    @staticmethod
    def _independent_source_count(links: list[EvidenceLink]) -> int:
        return len(source_groups(link.snapshot for link in links))

    def supporting_sources(self, claim_id: str, *, run_id: str = "") -> list[SourceSnapshotRecord]:
        """Only valid links that actually support this claim may satisfy API gates."""
        chain = self.get_chain(claim_id, run_id=run_id)
        return [link.snapshot for link in self.supporting_links(chain)]

    def intact_links(self, chain: ClaimChain) -> Iterator[EvidenceLink]:
        for link in chain.links:
            if self._check_span_integrity(link.span, link.snapshot)[0]:
                yield link

    def supporting_links(
        self, chain: ClaimChain, *, require_credible_source: bool = True,
    ) -> Iterator[EvidenceLink]:
        """Yield usable support, with an option to inspect matching candidate quotes."""
        for link in self.intact_links(chain):
            if (
                link.edge.relation is not EdgeRelation.CONTRADICTS
                and (not require_credible_source or _eligible_source(link))
                and _claim_supported_by_quote(
                    chain.claim, link.span.quote,
                    title=link.snapshot.title, url=link.snapshot.canonical_url,
                )
            ):
                yield link

    def _decide_status(
        self,
        claim: AtomicClaim,
        chain: ClaimChain,
        checks: dict[str, Any],
        *,
        window: tuple[date | None, date | None] | None,
        supported_ids: set[str],
        target_region: str,
    ) -> tuple[VerificationStatus, str]:
        region_issue = self._region_issue(claim, checks, target_region)
        if region_issue:
            status = (
                VerificationStatus.NOT_COMPARABLE
                if region_issue.startswith("claim_region_not_target")
                else VerificationStatus.INSUFFICIENT
            )
            return status, region_issue
        window_issue = self._window_issue(claim, window)
        if window_issue:
            return VerificationStatus.NOT_COMPARABLE, window_issue
        supports = int(checks.get("supporting_edges") or 0)
        contradicts = int(checks.get("contradicting_edges") or 0)
        if not supports and not contradicts:
            if checks.get("span_integrity_failures"):
                return VerificationStatus.INSUFFICIENT, "false_or_broken_reference"
            return VerificationStatus.INSUFFICIENT, "no_evidence"
        if claim.value and not claim.unit:
            return VerificationStatus.NOT_COMPARABLE, "numeric_value_without_unit"
        if claim.value and not claim.period:
            return VerificationStatus.NOT_COMPARABLE, "numeric_value_without_period"
        own_support = bool(checks["eligible_supporting_edges"])
        supported_conflicts = self._supported_claim_conflicts(chain, supported_ids) if own_support else []
        checks["contradicting_supported_claims"] = supported_conflicts
        if own_support:
            if any(
                relation.relation is ClaimRelationKind.SUPERSEDES
                and relation.to_claim_id == claim.claim_id
                and relation.from_claim_id in supported_ids
                for relation in chain.relations
            ):
                return VerificationStatus.OUTDATED, "superseded_by_newer_claim"
            if supported_conflicts or contradicts:
                return VerificationStatus.NEEDS_REVIEW, "conflicting_supported_evidence"
            if claim.value:
                return VerificationStatus.SUPPORTED, "value_and_span_verified"
            return VerificationStatus.SUPPORTED, "statement_exact_in_span"
        if contradicts:
            return VerificationStatus.CONTRADICTED, "contradicting_evidence"
        if checks["quote_supporting_edges"]:
            reason = "insufficient_source_credibility"
        elif checks.get("value_present") is False:
            reason = "value_not_in_quote"
        else:
            reason = "statement_not_in_span"
        return VerificationStatus.INSUFFICIENT, reason

    @staticmethod
    def _region_issue(
        claim: AtomicClaim,
        checks: dict[str, Any],
        target_region: str,
    ) -> str:
        """Region is an authorization condition, not a display-only check."""
        region = (claim.region_id or "").strip()
        if region.upper() == "UNKNOWN":
            return "claim_region_unknown"
        if not region:
            if claim.region_source == "unknown" or target_region:
                return "claim_region_unknown"
            return ""
        if target_region and region != target_region:
            return f"claim_region_not_target:{region}"
        if checks.get("region_present") is False:
            return "claim_region_not_in_evidence"
        return ""

    @staticmethod
    def _window_issue(
        claim: AtomicClaim, window: tuple[date | None, date | None] | None
    ) -> str:
        if window is None:
            return ""
        start, end = window
        if start is None and end is None:
            return ""
        period = claim.period.strip()
        if not period:
            return "claim_period_missing_for_window"
        full_date = re.search(
            r"(?<!\d)(\d{4})-(\d{1,2})(?:-(\d{1,2}))?(?!\d)", period
        )
        if full_date:
            try:
                value = date(
                    int(full_date.group(1)),
                    int(full_date.group(2)),
                    int(full_date.group(3) or 1),
                )
            except ValueError:
                value = None
            if value is not None:
                if start is not None and value < start:
                    return f"outside_requested_window:{value.isoformat()}"
                if end is not None and value > end:
                    return f"outside_requested_window:{value.isoformat()}"
                return ""
        month_match = re.search(r"(?<!\d)(\d{4})年(\d{1,2})月", period)
        if month_match:
            year_month = (int(month_match.group(1)), int(month_match.group(2)))
            if start is not None and year_month < (start.year, start.month):
                return f"outside_requested_window:{year_month[0]}-{year_month[1]:02d}"
            if end is not None and year_month > (end.year, end.month):
                return f"outside_requested_window:{year_month[0]}-{year_month[1]:02d}"
            return ""
        years = [int(year) for year in _years(period)]
        if not years:
            return "claim_period_missing_for_window"
        low = start.year if start is not None else -9999
        high = end.year if end is not None else 9999
        outside = [year for year in years if not (low <= year <= high)]
        if outside:
            return f"outside_requested_window:{min(outside)}"
        return ""

    def _related_support_ids(
        self, connection: sqlite3.Connection, chains: list[ClaimChain], *, run_id: str,
        window: tuple[date | None, date | None] | None, target_region: str,
    ) -> set[str]:
        """Check peers in the same transaction and run as the selected claims."""
        known = {chain.claim.claim_id: chain for chain in chains}
        related_ids = {
            claim_id for chain in chains for relation in chain.relations
            if relation.relation in (ClaimRelationKind.CONTRADICTS, ClaimRelationKind.SUPERSEDES)
            for claim_id in (relation.from_claim_id, relation.to_claim_id)
        }
        supported = set()
        for claim_id in related_ids:
            try:
                chain = known.get(claim_id) or self._get_chain(connection, claim_id, run_id)
            except KeyError:
                continue  # A legacy relation can point to a claim outside this run.
            if (
                not self._region_issue(chain.claim, {}, target_region)
                and not self._window_issue(chain.claim, window)
                and next(self.supporting_links(chain), None) is not None
            ):
                supported.add(claim_id)
        return supported

    @staticmethod
    def _supported_claim_conflicts(chain: ClaimChain, supported_ids: set[str]) -> list[str]:
        peer_ids = {
            claim_id for relation in chain.relations if relation.relation is ClaimRelationKind.CONTRADICTS
            for claim_id in (relation.from_claim_id, relation.to_claim_id)
        }
        return sorted((peer_ids & supported_ids) - {chain.claim.claim_id})

    def save_verification(
        self, record: VerificationRecord, *, reason: str = ""
    ) -> None:
        with self._connect() as connection:
            self._insert_verification(connection, record, reason or record.reason)

    @staticmethod
    def _insert_verification(
        connection: sqlite3.Connection, record: VerificationRecord, reason: str, *, update_global: bool = True,
    ) -> None:
        connection.execute(
            "INSERT OR REPLACE INTO verification_records"
            " (record_id, claim_id, status, deterministic_checks_json,"
            " judge_assessment_json, uncertainty, human_review_json,"
            " verifier_version, run_id, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                record.run_id,
                reason,
                record.created_at.isoformat(),
            ),
        )
        if update_global:
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
            run_id=row["run_id"],
            reason=row["reason"],
            created_at=_parse_datetime(row["created_at"]) or _utcnow(),
        )

    # ---------------------------------------------------------------- findings

    def save_findings(
        self, run_id: str, findings: list[FindingRecord], *,
        verifications: list[VerificationRecord] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for finding in findings:
                if finding.run_id != run_id:
                    raise ValueError("finding belongs to another run")
                if run_id:
                    self._bind_legacy_claim(connection, run_id, finding.claim_id, finding.created_at.isoformat())
            for record in verifications or ():
                if record.run_id != run_id:
                    raise ValueError("finding verification belongs to another run")
                self._insert_verification(connection, record, record.reason, update_global=False)
            connection.execute("DELETE FROM findings WHERE run_id = ?", (run_id,))
            connection.execute("DELETE FROM finding_slots WHERE run_id = ?", (run_id,))
            for finding in findings:
                connection.execute(
                    "INSERT INTO findings"
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
                for position, slot_id in enumerate(dict.fromkeys(finding.slot_ids)):
                    connection.execute(
                        "INSERT INTO finding_slots (finding_id, run_id, slot_id, position)"
                        " VALUES (?, ?, ?, ?)",
                        (finding.finding_id, run_id, slot_id, position),
                    )

    def list_findings(
        self, run_id: str, *, recheck_legacy: bool = False,
        window: tuple[date | None, date | None] | None = None, target_region: str = "",
    ) -> list[VerifiedFinding]:
        with self._connect() as connection:
            connection.execute("BEGIN")
            rows = connection.execute(
                "SELECT * FROM findings WHERE run_id = ? ORDER BY finding_id", (run_id,),
            ).fetchall()
            slots_by_finding: dict[str, list[str]] = {}
            for link in connection.execute(
                "SELECT finding_id, slot_id FROM finding_slots WHERE run_id = ? ORDER BY finding_id, position",
                (run_id,),
            ):
                slots_by_finding.setdefault(link["finding_id"], []).append(link["slot_id"])
            findings: list[VerifiedFinding] = []
            for row in rows:
                chain = self._get_chain(connection, row["claim_id"], run_id)
                status = VerificationStatus(
                    "INSUFFICIENT" if chain.claim.verification_reason == _UNBOUND_EVIDENCE else row["status"]
                )
                legacy_slots = [row["section"]] if row["section"] else []
                finding = FindingRecord(
                    finding_id=row["finding_id"], run_id=row["run_id"], claim_id=row["claim_id"],
                    section=row["section"], text=row["text"], status=status,
                    slot_ids=slots_by_finding.get(row["finding_id"], legacy_slots),
                    created_at=_parse_datetime(row["created_at"]) or _utcnow(),
                )
                findings.append(VerifiedFinding(finding=finding, chain=chain))
            if recheck_legacy:
                self._recheck_legacy_findings(connection, findings, run_id, window=window, target_region=target_region)
        return findings

    def _recheck_legacy_findings(
        self, connection: sqlite3.Connection, findings: list[VerifiedFinding], run_id: str, *,
        window: tuple[date | None, date | None] | None, target_region: str,
    ) -> None:
        """Refresh prior positive and adverse deterministic decisions in memory."""
        indexes = []
        for index, item in enumerate(findings):
            record = item.chain.verification
            if (
                record is not None and record.verifier_version != DETERMINISTIC_VERIFIER_VERSION
                and record.judge_assessment is None and record.human_review is None
                and record.status is item.finding.status
                and record.status in {
                    VerificationStatus.SUPPORTED, VerificationStatus.NEEDS_REVIEW,
                    VerificationStatus.OUTDATED, VerificationStatus.CONTRADICTED,
                }
            ):
                indexes.append(index)
        if not indexes:
            return
        supported_ids = self._related_support_ids(
            connection, [findings[index].chain for index in indexes],
            run_id=run_id, window=window, target_region=target_region,
        )
        for index in indexes:
            item = findings[index]
            status, reason, checks = self._evaluate_claim(
                item.chain, window=window, supported_ids=supported_ids, target_region=target_region,
            )
            findings[index] = item.with_verification_status(status, reason, checks=checks)

    def clear_run(self, run_id: str) -> None:
        """Remove findings, run-source links, relations and verification for a run.

        Used when a durable job is resumed so a later attempt cannot serve
        results produced by an earlier attempt.
        """
        with self._connect() as connection:
            for table in (
                "finding_slots",
                "findings",
                "run_claims",
                "run_snapshots",
                "claim_relations",
                "verification_records",
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE run_id = ?", (run_id,)
                )

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
