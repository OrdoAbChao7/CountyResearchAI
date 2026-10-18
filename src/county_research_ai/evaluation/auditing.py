"""独立实验产物的只读审计。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .experiment_models import RunStatus
from .reporting import ReportInputError, load_manifests, validate_manifest_artifacts


@dataclass(frozen=True)
class AuditIssue:
    run_id: str
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class AuditReport:
    runs_checked: int
    issues: tuple[AuditIssue, ...]

    @property
    def errors(self) -> tuple[AuditIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "ERROR")

    @property
    def warnings(self) -> tuple[AuditIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "WARNING")

    @property
    def passed(self) -> bool:
        return not self.errors


def audit_runs(runs_root: Path) -> AuditReport:
    manifests = load_manifests(runs_root)
    issues: list[AuditIssue] = []
    for manifest in manifests:
        run_id = str(manifest["run_id"])
        manifest_path = Path(str(manifest["_manifest_path"]))
        run_dir = manifest_path.parent
        try:
            validate_manifest_artifacts(manifest, run_dir)
        except ReportInputError as exc:
            issues.append(AuditIssue(run_id, "ERROR", "ARTIFACT_INVALID", str(exc)))

        resources_path = run_dir.parent / "resources.sqlite"
        if resources_path.is_file():
            active = _active_lease_count(resources_path)
            if active:
                issues.append(
                    AuditIssue(
                        run_id,
                        "ERROR",
                        "ACTIVE_LEASE",
                        f"resource ledger has {active} unsettled lease(s)",
                    )
                )
            overrun = _overrun_lease_count(resources_path)
            if overrun:
                issues.append(
                    AuditIssue(
                        run_id,
                        "ERROR",
                        "RESOURCE_OVERRUN",
                        f"resource ledger has {overrun} over-capacity settlement(s)",
                    )
                )
            overages = _capacity_overages(resources_path)
            for key, consumed, reserved, capacity in overages:
                issues.append(
                    AuditIssue(
                        run_id,
                        "ERROR",
                        "RESOURCE_CAPACITY_EXCEEDED",
                        f"{key} total={consumed + reserved} exceeds capacity={capacity}",
                    )
                )
        elif manifest["status"] == RunStatus.VALID.value:
            issues.append(
                AuditIssue(run_id, "ERROR", "RESOURCE_LEDGER_MISSING", "VALID run has no resource ledger")
            )

        if manifest["status"] == RunStatus.VALID.value and not (run_dir / "llm_responses").is_dir():
            issues.append(
                AuditIssue(
                    run_id,
                    "WARNING",
                    "RAW_LLM_ARCHIVE_MISSING",
                    "VALID artifact predates raw LLM response archiving or did not record it",
                )
            )
    return AuditReport(runs_checked=len(manifests), issues=tuple(issues))


def _active_lease_count(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT COUNT(*) FROM leases WHERE status='reserved'").fetchone()
        return int(row[0])
    except sqlite3.Error:
        return 1
    finally:
        connection.close()


def _overrun_lease_count(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT COUNT(*) FROM leases WHERE status='overrun'").fetchone()
        return int(row[0])
    except sqlite3.Error:
        return 0
    finally:
        connection.close()


def _capacity_overages(path: Path) -> list[tuple[str, int, int, int]]:
    connection = sqlite3.connect(path)
    try:
        limits = connection.execute(
            "SELECT provider, model, kind, capacity_units FROM resource_limits"
        ).fetchall()
        overages: list[tuple[str, int, int, int]] = []
        for provider, model, kind, capacity in limits:
            consumed, reserved = connection.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN status IN ('settled', 'failed', 'overrun') THEN consumed_units ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status='reserved' THEN reserved_units ELSE 0 END), 0)
                FROM leases
                WHERE provider=? AND model=? AND kind=?
                """,
                (provider, model, kind),
            ).fetchone()
            if int(consumed) + int(reserved) > int(capacity):
                overages.append(
                    (
                        f"({provider}, {model}, {kind})",
                        int(consumed),
                        int(reserved),
                        int(capacity),
                    )
                )
        return overages
    except sqlite3.Error:
        return []
    finally:
        connection.close()
