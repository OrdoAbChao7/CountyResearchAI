"""Durable, restart-safe job records for the local AxiomScope API."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..domain.outcomes import ResearchOutcome
from ..domain.research_contracts import ResearchContract

JOB_SCHEMA_VERSION = 1


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    INTERRUPTED = "INTERRUPTED"

    @property
    def terminal(self) -> bool:
        return self not in {JobStatus.QUEUED, JobStatus.RUNNING}


_TERMINAL_STATUSES = tuple(status.value for status in JobStatus if status.terminal)


class JobRecord(BaseModel):
    job_id: str
    status: JobStatus
    outcome: ResearchOutcome | None = None
    outcome_reason: str = ""
    contract: ResearchContract
    county: str = ""
    focus: str = ""
    mode: str = "snapshot"
    mode_label: str = "MOCK"
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_requested: bool = False
    error_code: str = ""
    error_message: str = ""
    report_path: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    budget_enforcement: dict[str, Any] = Field(default_factory=dict)
    lease_owner: str = ""
    lease_expires_at: datetime | None = None
    fencing_token: int = 0


class EventRecord(BaseModel):
    job_id: str
    seq: int
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class JobStore:
    """SQLite store for job history and append-only event streams."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    outcome TEXT,
                    outcome_reason TEXT NOT NULL DEFAULT '',
                    contract_json TEXT NOT NULL,
                    county TEXT NOT NULL DEFAULT '',
                    focus TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT 'snapshot',
                    mode_label TEXT NOT NULL DEFAULT 'MOCK',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    report_path TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    budget_enforcement_json TEXT NOT NULL DEFAULT '{}',
                    lease_owner TEXT NOT NULL DEFAULT '',
                    lease_expires_at TEXT NOT NULL DEFAULT '',
                    fencing_token INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    job_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, seq)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
                """
            )
            job_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(jobs)")
            }
            for column, ddl in (
                ("lease_owner", "TEXT NOT NULL DEFAULT ''"),
                ("lease_expires_at", "TEXT NOT NULL DEFAULT ''"),
                ("fencing_token", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if column not in job_columns:
                    connection.execute(
                        f"ALTER TABLE jobs ADD COLUMN {column} {ddl}"
                    )
            connection.execute(f"PRAGMA user_version = {JOB_SCHEMA_VERSION}")

    # ------------------------------------------------------------------ jobs

    def create_job(
        self,
        contract: ResearchContract,
        *,
        mode_label: str,
        job_id: str | None = None,
    ) -> JobRecord:
        now = _utcnow()
        record = JobRecord(
            job_id=job_id or uuid.uuid4().hex,
            status=JobStatus.QUEUED,
            contract=contract,
            county=contract.regions[0],
            focus=contract.research_focus,
            mode=contract.mode,
            mode_label=mode_label,
            created_at=now,
            updated_at=now,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs"
                " (job_id, status, contract_json, county, focus, mode, mode_label,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.job_id,
                    record.status.value,
                    record.contract.model_dump_json(),
                    record.county,
                    record.focus,
                    record.mode,
                    record.mode_label,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        self.append_event(record.job_id, "job.queued", {"mode_label": mode_label})
        return record

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job(row) if row is not None else None

    def list_jobs(self, *, limit: int = 50, offset: int = 0) -> list[JobRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            status=JobStatus(row["status"]),
            outcome=ResearchOutcome(row["outcome"]) if row["outcome"] else None,
            outcome_reason=row["outcome_reason"],
            contract=ResearchContract.model_validate_json(row["contract_json"]),
            county=row["county"],
            focus=row["focus"],
            mode=row["mode"],
            mode_label=row["mode_label"],
            created_at=_parse(row["created_at"]) or _utcnow(),
            updated_at=_parse(row["updated_at"]) or _utcnow(),
            started_at=_parse(row["started_at"]),
            finished_at=_parse(row["finished_at"]),
            cancel_requested=bool(row["cancel_requested"]),
            error_code=row["error_code"],
            error_message=row["error_message"],
            report_path=row["report_path"],
            result=json.loads(row["result_json"]),
            budget_enforcement=json.loads(row["budget_enforcement_json"]),
            lease_owner=row["lease_owner"],
            lease_expires_at=_parse(row["lease_expires_at"]),
            fencing_token=int(row["fencing_token"]),
        )

    def claim_for_execution(
        self,
        job_id: str,
        *,
        owner: str = "",
        lease_seconds: float = 60.0,
    ) -> int | None:
        """Atomically acquire an execution lease and return a fencing token.

        A job can be claimed when it is queued/interrupted, or when it is
        RUNNING but its lease has expired. Only one caller can win; the returned
        token must accompany later renewal and terminal writes so a stale worker
        cannot overwrite a newer attempt.
        """
        owner = owner or f"worker:{uuid.uuid4().hex}"
        now_dt = _utcnow()
        now = now_dt.isoformat()
        expires = (now_dt + timedelta(seconds=max(0.1, lease_seconds))).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status = ?, started_at = COALESCE(started_at, ?),"
                " finished_at = NULL, updated_at = ?, error_code = '',"
                " error_message = '', lease_owner = ?, lease_expires_at = ?,"
                " fencing_token = fencing_token + 1"
                " WHERE job_id = ? AND ("
                "   status IN (?, ?)"
                "   OR (status = ? AND (lease_expires_at = '' OR lease_expires_at < ?))"
                " )",
                (
                    JobStatus.RUNNING.value,
                    now,
                    now,
                    owner,
                    expires,
                    job_id,
                    JobStatus.QUEUED.value,
                    JobStatus.INTERRUPTED.value,
                    JobStatus.RUNNING.value,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT fencing_token FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return int(row["fencing_token"]) if row is not None else None

    def renew_lease(
        self,
        job_id: str,
        *,
        owner: str,
        fencing_token: int,
        lease_seconds: float = 60.0,
    ) -> bool:
        now_dt = _utcnow()
        expires = (now_dt + timedelta(seconds=max(0.1, lease_seconds))).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET lease_expires_at = ?, updated_at = ?"
                " WHERE job_id = ? AND status = ? AND lease_owner = ?"
                " AND fencing_token = ?",
                (
                    expires,
                    now_dt.isoformat(),
                    job_id,
                    JobStatus.RUNNING.value,
                    owner,
                    fencing_token,
                ),
            )
            return cursor.rowcount == 1

    def mark_running(self, job_id: str) -> None:
        now = _utcnow().isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, started_at = ?, finished_at = NULL,"
                " updated_at = ?, error_code = '', error_message = ''"
                " WHERE job_id = ?",
                (JobStatus.RUNNING.value, now, now, job_id),
            )

    def mark_terminal(
        self,
        job_id: str,
        status: JobStatus,
        *,
        outcome: ResearchOutcome,
        outcome_reason: str = "",
        report_path: str = "",
        result: dict[str, Any] | None = None,
        budget_enforcement: dict[str, Any] | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> None:
        if not status.terminal:
            raise ValueError(f"not a terminal status: {status}")
        now = _utcnow().isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, outcome = ?, outcome_reason = ?,"
                " finished_at = ?, updated_at = ?, report_path = ?, result_json = ?,"
                " budget_enforcement_json = ?, error_code = ?, error_message = ?,"
                " lease_owner = '', lease_expires_at = ''"
                " WHERE job_id = ?",
                (
                    status.value,
                    outcome.value,
                    outcome_reason,
                    now,
                    now,
                    report_path,
                    json.dumps(result or {}, ensure_ascii=False, default=str),
                    json.dumps(budget_enforcement or {}, ensure_ascii=False),
                    error_code,
                    error_message,
                    job_id,
                ),
            )

    def finish_job(
        self,
        job_id: str,
        status: JobStatus,
        *,
        outcome: ResearchOutcome,
        event_type: str,
        event_payload: dict[str, Any] | None = None,
        outcome_reason: str = "",
        owner: str = "",
        fencing_token: int | None = None,
        report_path: str = "",
        result: dict[str, Any] | None = None,
        budget_enforcement: dict[str, Any] | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> bool:
        """Atomically write the terminal state and its event.

        With owner + fencing token, a stale worker that lost its lease cannot
        overwrite a newer attempt. Returns False in that case.
        """
        if not status.terminal:
            raise ValueError(f"not a terminal status: {status}")
        now_dt = _utcnow()
        now = now_dt.isoformat()
        terminal_placeholders = ", ".join("?" for _ in _TERMINAL_STATUSES)
        where = f"job_id = ? AND status NOT IN ({terminal_placeholders})"
        where_params: list[Any] = [job_id, *_TERMINAL_STATUSES]
        if owner and fencing_token is not None:
            where += (
                " AND status = ? AND lease_owner = ? AND fencing_token = ?"
                " AND lease_expires_at >= ?"
            )
            where_params.extend(
                [JobStatus.RUNNING.value, owner, int(fencing_token), now]
            )
        values: list[Any] = [
            status.value,
            outcome.value,
            outcome_reason,
            now,
            now,
            report_path,
            json.dumps(result or {}, ensure_ascii=False, default=str),
            json.dumps(budget_enforcement or {}, ensure_ascii=False),
            error_code,
            error_message,
        ]
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status = ?, outcome = ?, outcome_reason = ?,"
                " finished_at = ?, updated_at = ?, report_path = ?, result_json = ?,"
                " budget_enforcement_json = ?, error_code = ?, error_message = ?,"
                " lease_owner = '', lease_expires_at = ''"
                f" WHERE {where}",
                (*values, *where_params),
            )
            if cursor.rowcount != 1:
                return False
            row = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq FROM job_events WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            seq = int(row["seq"]) + 1
            connection.execute(
                "INSERT INTO job_events"
                " (job_id, seq, event_type, payload_json, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    job_id,
                    seq,
                    event_type,
                    json.dumps(event_payload or {}, ensure_ascii=False, default=str),
                    now,
                ),
            )
        return True

    def request_cancel(self, job_id: str) -> bool:
        """Request cancellation; returns True when the job is still active."""
        now = _utcnow().isoformat()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if JobStatus(row["status"]).terminal:
                return False
            connection.execute(
                "UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE job_id = ?",
                (now, job_id),
            )
        self.append_event(job_id, "job.cancel_requested", {})
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return bool(row["cancel_requested"]) if row is not None else False

    def requeue(self, job_id: str) -> None:
        """Reset a finished or interrupted job so it can be executed again."""
        now = _utcnow().isoformat()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] == JobStatus.RUNNING.value:
                raise ValueError("cannot requeue a running job")
            connection.execute(
                "UPDATE jobs SET status = ?, outcome = NULL, outcome_reason = '',"
                " cancel_requested = 0, error_code = '', error_message = '',"
                " report_path = '', result_json = '{}',"
                " budget_enforcement_json = '{}', started_at = NULL,"
                " finished_at = NULL, lease_owner = '', lease_expires_at = '',"
                " updated_at = ?"
                " WHERE job_id = ?",
                (JobStatus.QUEUED.value, now, job_id),
            )
        self.append_event(job_id, "job.requeued", {})

    def recover_interrupted(self) -> int:
        """Mark RUNNING jobs with no live lease as INTERRUPTED.

        A live lease belongs to another worker/process and must not be stolen on
        startup. Only empty or expired leases are recovered.
        """
        now = _utcnow().isoformat()
        condition = (
            "status = ? AND (lease_expires_at = '' OR lease_expires_at < ?)"
        )
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT job_id FROM jobs WHERE {condition}",
                (JobStatus.RUNNING.value, now),
            ).fetchall()
            if not rows:
                return 0
            connection.execute(
                "UPDATE jobs SET status = ?, outcome = ?, outcome_reason = ?,"
                " finished_at = ?, updated_at = ?, error_code = ?,"
                " lease_owner = '', lease_expires_at = ''"
                f" WHERE {condition}",
                (
                    JobStatus.INTERRUPTED.value,
                    ResearchOutcome.FAILED.value,
                    "process_restarted_before_completion",
                    now,
                    now,
                    "process_restarted",
                    JobStatus.RUNNING.value,
                    now,
                ),
            )
        for row in rows:
            self.append_event(
                row["job_id"],
                "job.interrupted",
                {"reason": "process_restarted_before_completion"},
            )
        return len(rows)

    # ---------------------------------------------------------------- events

    def append_event(
        self, job_id: str, event_type: str, payload: dict[str, Any] | None = None
    ) -> EventRecord:
        now = _utcnow()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq FROM job_events WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            seq = int(row["seq"]) + 1
            connection.execute(
                "INSERT INTO job_events"
                " (job_id, seq, event_type, payload_json, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    job_id,
                    seq,
                    event_type,
                    json.dumps(payload or {}, ensure_ascii=False, default=str),
                    now.isoformat(),
                ),
            )
        return EventRecord(
            job_id=job_id,
            seq=seq,
            event_type=event_type,
            payload=payload or {},
            created_at=now,
        )

    def list_events(self, job_id: str, *, after_seq: int = 0) -> list[EventRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_events WHERE job_id = ? AND seq > ? ORDER BY seq",
                (job_id, after_seq),
            ).fetchall()
        return [
            EventRecord(
                job_id=row["job_id"],
                seq=row["seq"],
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                created_at=_parse(row["created_at"]) or _utcnow(),
            )
            for row in rows
        ]
