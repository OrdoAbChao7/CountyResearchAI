from __future__ import annotations

import json
from pathlib import Path

import pytest

from county_research_ai.evaluation.experiment_models import RunArtifact
from county_research_ai.evaluation.reporting import (
    ReportInputError,
    build_status_summary,
    load_manifests,
    render_markdown_report,
    validate_manifest_artifacts,
    write_metrics_csv,
)


def _write_manifest(root: Path, *, status: str = "VALID") -> Path:
    run_dir = root / "run-1"
    run_dir.mkdir()
    artifact = RunArtifact(run_dir)
    report, digest = artifact.write_text("report.md", "report")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "experiment_id": "E1",
                "group": "A",
                "county": "测试县",
                "task_id": "snapshot",
                "mode": "snapshot",
                "model": "test-model",
                "search_provider": "test-search",
                "config_hash": "config",
                "status": status,
                "artifacts": {"report": f"{report.name}:{digest}"},
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def test_load_manifests_is_deterministic_and_validates_status(tmp_path: Path) -> None:
    _write_manifest(tmp_path)

    manifests = load_manifests(tmp_path)

    assert [item["run_id"] for item in manifests] == ["run-1"]


def test_validate_manifest_artifacts_detects_hash_drift(tmp_path: Path) -> None:
    run_dir = _write_manifest(tmp_path)
    payload = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    payload["artifacts"]["report"] = "report.md:bad"
    (run_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ReportInputError, match="hash mismatch"):
        validate_manifest_artifacts(payload, run_dir)


def test_render_report_preserves_invalid_runs_and_marks_quality_inconclusive() -> None:
    manifests = [
        {"run_id": "valid", "group": "A", "county": "甲县", "status": "VALID", "error": None},
        {"run_id": "blocked", "group": "B", "county": "甲县", "status": "BLOCKED", "error": "quota"},
    ]

    report = render_markdown_report(
        title="Independent comparison",
        manifests=manifests,
        quality_conclusion="INCONCLUSIVE",
        notes=["Ground Truth has not been frozen."],
    )

    assert "INCONCLUSIVE" in report
    assert "BLOCKED" in report
    assert "quota" in report
    assert build_status_summary(manifests) == {"BLOCKED": 1, "VALID": 1}


def test_write_metrics_csv_is_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "metrics.csv"

    write_metrics_csv(
        output,
        [
            {"run_id": "b", "group": "B", "fact_accuracy": 0.5},
            {"run_id": "a", "group": "A", "fact_accuracy": 1.0},
        ],
    )

    assert output.read_text(encoding="utf-8") == (
        "fact_accuracy,group,run_id\n1.0,A,a\n0.5,B,b\n"
    )
