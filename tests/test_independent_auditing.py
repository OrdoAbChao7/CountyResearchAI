from __future__ import annotations

import json
from pathlib import Path

from county_research_ai.evaluation.auditing import audit_runs
from county_research_ai.evaluation.experiment_models import RunArtifact


def test_audit_accepts_valid_artifacts_and_reports_legacy_archive_warning(tmp_path: Path) -> None:
    run_dir = tmp_path / "batch" / "run-1"
    run_dir.mkdir(parents=True)
    artifact = RunArtifact(run_dir)
    path, digest = artifact.write_text("report.md", "report")
    connection = __import__("sqlite3").connect(run_dir.parent / "resources.sqlite")
    connection.execute("CREATE TABLE leases (status TEXT)")
    connection.commit()
    connection.close()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "group": "A",
                "county": "测试县",
                "status": "VALID",
                "artifacts": {"report": f"{path.name}:{digest}"},
            }
        ),
        encoding="utf-8",
    )

    report = audit_runs(tmp_path / "batch")

    assert report.passed
    assert report.warnings[0].code == "RAW_LLM_ARCHIVE_MISSING"


def test_audit_rejects_unsettled_resource_lease(tmp_path: Path) -> None:
    run_dir = tmp_path / "batch" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "group": "A",
                "county": "测试县",
                "status": "FAILED",
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )
    connection = __import__("sqlite3").connect(run_dir.parent / "resources.sqlite")
    connection.execute("CREATE TABLE leases (status TEXT)")
    connection.execute("INSERT INTO leases(status) VALUES ('reserved')")
    connection.commit()
    connection.close()

    report = audit_runs(tmp_path / "batch")

    assert not report.passed
    assert report.errors[0].code == "ACTIVE_LEASE"


def test_audit_rejects_legacy_ledger_over_capacity(tmp_path: Path) -> None:
    run_dir = tmp_path / "batch" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "group": "A",
                "county": "测试县",
                "status": "VALID",
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )
    connection = __import__("sqlite3").connect(run_dir.parent / "resources.sqlite")
    connection.execute("CREATE TABLE leases (provider TEXT, model TEXT, kind TEXT, status TEXT, consumed_units INTEGER, reserved_units INTEGER)")
    connection.execute("CREATE TABLE resource_limits (provider TEXT, model TEXT, kind TEXT, capacity_units INTEGER, billing_class TEXT, updated_at TEXT)")
    connection.execute("INSERT INTO leases VALUES ('gemini', 'model', 'llm', 'settled', 3, 1)")
    connection.execute("INSERT INTO resource_limits VALUES ('gemini', 'model', 'llm', 2, 'free_confirmed', 'now')")
    connection.commit()
    connection.close()

    report = audit_runs(tmp_path / "batch")

    assert not report.passed
    assert any(issue.code == "RESOURCE_CAPACITY_EXCEEDED" for issue in report.errors)
