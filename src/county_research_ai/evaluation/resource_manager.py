"""持久化、租约式实验资源管理器。

实验调用先 reserve，再 settle/fail。所有预算判断在 SQLite 写事务中完成，
因此多个研究进程共享同一账本时不会因为并发而超额预留。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ResourceKey = tuple[str, str, str]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResourceError(RuntimeError):
    """资源账本错误基类。"""


class ResourceDeniedError(ResourceError):
    """Provider、计费类别或资源类型不允许调用。"""


class ResourceExhaustedError(ResourceError):
    """预算或并发容量不足。"""


class ResourceOverrunError(ResourceExhaustedError):
    """Provider 实际结算量超过已冻结容量。"""


class ResourceStateError(ResourceError):
    """租约状态不允许当前操作。"""


@dataclass(frozen=True)
class ResourceLimit:
    capacity_units: int
    billing_class: str = "free_confirmed"

    def __post_init__(self) -> None:
        if self.capacity_units <= 0:
            raise ValueError("capacity_units must be positive")
        if self.billing_class not in {
            "free_confirmed",
            "paid_authorized",
            "paid",
            "unknown",
        }:
            raise ValueError(f"unsupported billing_class: {self.billing_class}")


@dataclass(frozen=True)
class ResourceRequest:
    provider: str
    model: str
    kind: str
    units: int
    run_id: str

    def __post_init__(self) -> None:
        if self.units <= 0:
            raise ValueError("units must be positive")
        if not all((self.provider, self.model, self.kind, self.run_id)):
            raise ValueError("provider, model, kind and run_id are required")

    @property
    def key(self) -> ResourceKey:
        return self.provider, self.model, self.kind


@dataclass(frozen=True)
class Lease:
    lease_id: str
    request: ResourceRequest
    reserved_units: int
    created_at: str


@dataclass(frozen=True)
class ResourceSnapshot:
    consumed: dict[ResourceKey, int]
    reserved: dict[ResourceKey, int]
    active: int
    events: list[dict[str, Any]]


class ResourceManager:
    """使用 SQLite 事务实现并发安全的资源预留和结算。"""

    def __init__(self, path: Path, *, limits: dict[ResourceKey, ResourceLimit]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.limits = dict(limits)
        self._initialize()

    def reserve(self, request: ResourceRequest) -> Lease:
        limit = self.limits.get(request.key)
        if limit is None:
            raise ResourceDeniedError(f"resource is not configured: {request.key}")
        if limit.billing_class not in {"free_confirmed", "paid_authorized"}:
            raise ResourceDeniedError(
                f"billing class is not allowed: {request.key} ({limit.billing_class})"
            )

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            consumed, reserved = self._totals(connection, request.key)
            if consumed + reserved + request.units > limit.capacity_units:
                raise ResourceExhaustedError(
                    f"resource capacity exhausted: {request.key}; "
                    f"used={consumed}, reserved={reserved}, requested={request.units}, "
                    f"capacity={limit.capacity_units}"
                )

            lease_id = uuid.uuid4().hex
            created_at = _now()
            connection.execute(
                """
                INSERT INTO leases (
                    lease_id, provider, model, kind, run_id, reserved_units,
                    consumed_units, status, created_at, updated_at, usage_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 'reserved', ?, ?, '{}', NULL)
                """,
                (
                    lease_id,
                    request.provider,
                    request.model,
                    request.kind,
                    request.run_id,
                    request.units,
                    created_at,
                    created_at,
                ),
            )
            connection.commit()
            return Lease(lease_id, request, request.units, created_at)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def settle(
        self,
        lease_id: str,
        settled_units: int,
        *,
        usage: dict[str, Any] | None = None,
    ) -> None:
        if settled_units < 0:
            raise ValueError("settled_units must not be negative")
        self._finish(lease_id, "settled", max(settled_units, 0), usage=usage, error=None)

    def fail(self, lease_id: str, reason: str) -> None:
        if not reason:
            raise ValueError("failure reason is required")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._get_lease(connection, lease_id)
            self._require_reserved(row)
            now = _now()
            connection.execute(
                """
                UPDATE leases
                SET status='failed', consumed_units=reserved_units,
                    updated_at=?, error=?
                WHERE lease_id=?
                """,
                (now, reason, lease_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def snapshot(self) -> ResourceSnapshot:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT provider, model, kind, reserved_units, consumed_units,
                       status, run_id, lease_id, updated_at, error
                FROM leases ORDER BY updated_at, lease_id
                """
            ).fetchall()
        finally:
            connection.close()

        consumed: dict[ResourceKey, int] = {}
        reserved: dict[ResourceKey, int] = {}
        events: list[dict[str, Any]] = []
        active = 0
        for row in rows:
            key = (row[0], row[1], row[2])
            if row[5] == "reserved":
                reserved[key] = reserved.get(key, 0) + row[3]
                active += 1
            else:
                consumed[key] = consumed.get(key, 0) + row[4]
            events.append(
                {
                    "lease_id": row[7],
                    "run_id": row[6],
                    "provider": row[0],
                    "model": row[1],
                    "kind": row[2],
                    "status": row[5],
                    "units": row[4] if row[5] != "reserved" else row[3],
                    "updated_at": row[8],
                    "error": row[9],
                }
            )
        return ResourceSnapshot(consumed=consumed, reserved=reserved, active=active, events=events)

    def _finish(
        self,
        lease_id: str,
        status: str,
        settled_units: int,
        *,
        usage: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._get_lease(connection, lease_id)
            self._require_reserved(row)
            now = _now()
            key = (row["provider"], row["model"], row["kind"])
            limit = self.limits.get(key)
            if limit is None:
                raise ResourceStateError(f"resource limit is missing for lease: {key}")
            consumed, reserved = self._totals_excluding(connection, key, lease_id)
            if consumed + reserved + settled_units > limit.capacity_units:
                overrun_error = (
                    f"actual settlement exceeded resource capacity: {key}; "
                    f"consumed={consumed}, reserved={reserved}, settled={settled_units}, "
                    f"capacity={limit.capacity_units}"
                )
                connection.execute(
                    """
                    UPDATE leases
                    SET status='overrun', consumed_units=?, updated_at=?, usage_json=?, error=?
                    WHERE lease_id=?
                    """,
                    (
                        settled_units,
                        now,
                        json.dumps(usage or {}, ensure_ascii=False, sort_keys=True),
                        overrun_error,
                        lease_id,
                    ),
                )
                connection.commit()
                raise ResourceOverrunError(overrun_error)
            connection.execute(
                """
                UPDATE leases
                SET status=?, consumed_units=?, updated_at=?, usage_json=?, error=?
                WHERE lease_id=?
                """,
                (
                    status,
                    settled_units,
                    now,
                    json.dumps(usage or {}, ensure_ascii=False, sort_keys=True),
                    error,
                    lease_id,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _require_reserved(row: sqlite3.Row) -> None:
        if row is None:
            raise ResourceStateError("lease does not exist")
        if row["status"] != "reserved":
            raise ResourceStateError(f"lease is already finalized: {row['status']}")

    @staticmethod
    def _get_lease(connection: sqlite3.Connection, lease_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
        return row

    @staticmethod
    def _totals(connection: sqlite3.Connection, key: ResourceKey) -> tuple[int, int]:
        provider, model, kind = key
        consumed = connection.execute(
            """
            SELECT COALESCE(SUM(consumed_units), 0) FROM leases
            WHERE provider=? AND model=? AND kind=?
              AND status IN ('settled', 'failed', 'overrun')
            """,
            (provider, model, kind),
        ).fetchone()[0]
        reserved = connection.execute(
            """
            SELECT COALESCE(SUM(reserved_units), 0) FROM leases
            WHERE provider=? AND model=? AND kind=? AND status='reserved'
            """,
            (provider, model, kind),
        ).fetchone()[0]
        return int(consumed), int(reserved)

    @staticmethod
    def _totals_excluding(
        connection: sqlite3.Connection,
        key: ResourceKey,
        lease_id: str,
    ) -> tuple[int, int]:
        provider, model, kind = key
        consumed = connection.execute(
            """
            SELECT COALESCE(SUM(consumed_units), 0) FROM leases
            WHERE provider=? AND model=? AND kind=?
              AND status IN ('settled', 'failed', 'overrun') AND lease_id != ?
            """,
            (provider, model, kind, lease_id),
        ).fetchone()[0]
        reserved = connection.execute(
            """
            SELECT COALESCE(SUM(reserved_units), 0) FROM leases
            WHERE provider=? AND model=? AND kind=?
              AND status='reserved' AND lease_id != ?
            """,
            (provider, model, kind, lease_id),
        ).fetchone()[0]
        return int(consumed), int(reserved)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS leases (
                    lease_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    reserved_units INTEGER NOT NULL,
                    consumed_units INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    usage_json TEXT NOT NULL,
                    error TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS resource_limits (
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    capacity_units INTEGER NOT NULL,
                    billing_class TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (provider, model, kind)
                )
                """
            )
            for (provider, model, kind), limit in self.limits.items():
                existing = connection.execute(
                    """
                    SELECT capacity_units, billing_class FROM resource_limits
                    WHERE provider=? AND model=? AND kind=?
                    """,
                    (provider, model, kind),
                ).fetchone()
                if existing is not None and (
                    int(existing[0]) != limit.capacity_units
                    or str(existing[1]) != limit.billing_class
                ):
                    raise ResourceStateError(
                        "resource limit drift for "
                        f"{(provider, model, kind)}: persisted="
                        f"({existing[0]}, {existing[1]}), configured="
                        f"({limit.capacity_units}, {limit.billing_class})"
                    )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO resource_limits
                    (provider, model, kind, capacity_units, billing_class, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (provider, model, kind, limit.capacity_units, limit.billing_class, _now()),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
