"""Regression coverage for relocatable experiment-manifest resource paths.

Committed continuation manifests record absolute paths from the machine and
directory where the run happened. Renaming or moving the checkout must not turn
a present resource ledger into a false ``MISSING`` audit result, and a genuinely
missing ledger must still fail closed.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.audit_continuation_experiment import (
    _audit_resource_db,
    _resolve_recorded_path,
)


def _make_resource_db(path: Path, *, reserved: int = 0) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE leases (status TEXT, consumed_units INTEGER)"
        )
        connection.execute(
            "CREATE TABLE resource_limits ("
            "provider TEXT, model TEXT, kind TEXT, "
            "capacity_units INTEGER, billing_class TEXT)"
        )
        for _ in range(reserved):
            connection.execute("INSERT INTO leases VALUES ('reserved', 0)")
        connection.execute("INSERT INTO leases VALUES ('closed', 10)")
        connection.execute(
            "INSERT INTO resource_limits VALUES ('deepseek', 'flash', 'token', 1000, 'paid')"
        )
        connection.commit()
    finally:
        connection.close()


def _repo_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo_root = tmp_path / "AxiomScope"
    runs_dir = repo_root / "experiments" / "independent_comparison" / "runs"
    batch_root = runs_dir / "batch_20261019"
    batch_root.mkdir(parents=True)
    return repo_root, runs_dir, batch_root


def _foreign_recorded(tmp_path: Path, db_name: str) -> Path:
    """An absolute path outside the repository that is guaranteed not to exist."""
    return (
        tmp_path
        / "foreign-checkout"
        / "experiments"
        / "independent_comparison"
        / "runs"
        / db_name
    )


def test_foreign_absolute_path_resolves_via_experiments_suffix(tmp_path: Path) -> None:
    repo_root, runs_dir, batch_root = _repo_layout(tmp_path)
    db_name = "continuation_resource_manager_20261019.sqlite"
    _make_resource_db(runs_dir / db_name)
    recorded = _foreign_recorded(tmp_path, db_name)

    resolved, source = _resolve_recorded_path(
        recorded, search_dir=batch_root.parent, repo_root=repo_root
    )

    assert resolved == (runs_dir / db_name).resolve()
    assert source == "relocated_repo_relative"


def test_foreign_absolute_path_resolves_by_basename(tmp_path: Path) -> None:
    repo_root, runs_dir, batch_root = _repo_layout(tmp_path)
    db_name = "ledger.sqlite"
    _make_resource_db(runs_dir / db_name)
    recorded = Path(r"D:\Elsewhere\ledger.sqlite")

    resolved, source = _resolve_recorded_path(
        recorded, search_dir=batch_root.parent, repo_root=repo_root
    )

    assert resolved == (runs_dir / db_name).resolve()
    assert source == "relocated_by_name"


def test_missing_ledger_still_fails_closed(tmp_path: Path) -> None:
    repo_root, _, batch_root = _repo_layout(tmp_path)
    recorded = Path(r"E:\Projects\CountyResearchAI\nowhere.sqlite")

    resolved, source = _resolve_recorded_path(
        recorded, search_dir=batch_root.parent, repo_root=repo_root
    )
    result = _audit_resource_db(resolved, recorded_path=recorded, path_source=source)

    assert source == "missing"
    assert result["status"] == "MISSING"
    assert result["path_source"] == "missing"
    assert result["recorded_path"] == str(recorded)


def test_audit_reports_relocated_path_and_closed_ledger(tmp_path: Path) -> None:
    repo_root, runs_dir, batch_root = _repo_layout(tmp_path)
    db_name = "continuation_resource_manager_20261019.sqlite"
    _make_resource_db(runs_dir / db_name)
    recorded = _foreign_recorded(tmp_path, db_name)

    resolved, source = _resolve_recorded_path(
        recorded, search_dir=batch_root.parent, repo_root=repo_root
    )
    result = _audit_resource_db(resolved, recorded_path=recorded, path_source=source)

    assert result["status"] == "CLOSED"
    assert result["active_leases"] == 0
    assert result["path_source"] == "relocated_repo_relative"
    assert result["recorded_path"] == str(recorded)
