from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import run_independent_judges
from scripts.run_independent_judges import collect_judge_candidates, load_frozen_rubric

from county_research_ai.evaluation.gate import FormalGateError


def _write_manifest(
    root: Path, *, run_id: str, group: str, status: str, formal_target: bool = True
) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    report = run_dir / "report.md"
    report.write_text(f"实验组 {group} 的 {run_id} 报告", encoding="utf-8")
    digest = __import__("hashlib").sha256(report.read_bytes()).hexdigest()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "experiment_id": "E1",
                "group": group,
                "county": "德清县",
                "task_id": "snapshot",
                "mode": "snapshot",
                "status": status,
                "formal_target": formal_target,
                "artifacts": {"report": f"report.md:{digest}"},
            }
        ),
        encoding="utf-8",
    )


def test_load_frozen_rubric_requires_explicit_freeze():
    rubric = load_frozen_rubric()

    assert rubric["status"] == "FROZEN"
    assert rubric["judge_policy"]["minimum_independent_judges"] >= 2


def test_collect_judge_candidates_filters_invalid_and_anonymizes(tmp_path):
    _write_manifest(tmp_path, run_id="valid-run", group="C", status="VALID")
    _write_manifest(tmp_path, run_id="failed-run", group="A", status="FAILED")

    candidates = collect_judge_candidates(tmp_path)

    assert [candidate.run_id for candidate in candidates] == ["valid-run"]
    assert "实验组 C" not in candidates[0].anonymous_report.text
    assert "valid-run" not in candidates[0].anonymous_report.text
    assert len(candidates[0].anonymous_report.report_hash) == 64


def test_collect_judge_candidates_rejects_missing_report_artifact(tmp_path):
    run_dir = tmp_path / "broken"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "broken",
                "group": "A",
                "county": "德清县",
                "status": "VALID",
                "formal_target": True,
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="report artifact"):
        collect_judge_candidates(tmp_path)


def test_collect_judge_candidates_excludes_nonformal_valid_runs(tmp_path):
    _write_manifest(tmp_path, run_id="formal-run", group="A", status="VALID")
    _write_manifest(
        tmp_path,
        run_id="development-run",
        group="B",
        status="VALID",
        formal_target=False,
    )

    candidates = collect_judge_candidates(tmp_path)

    assert [candidate.run_id for candidate in candidates] == ["formal-run"]


def test_collect_judge_candidates_excludes_bounded_preflight_runs(tmp_path):
    _write_manifest(tmp_path, run_id="formal_preflight_run", group="A", status="VALID")
    _write_manifest(tmp_path, run_id="formal-target-run", group="B", status="VALID")

    candidates = collect_judge_candidates(tmp_path)

    assert [candidate.run_id for candidate in candidates] == ["formal-target-run"]


def test_collect_judge_candidates_can_include_only_selected_batch_prefixes(tmp_path):
    _write_manifest(tmp_path, run_id="corrected-e1-run", group="A", status="VALID")
    _write_manifest(tmp_path, run_id="old-invalid-run", group="B", status="VALID")

    candidates = collect_judge_candidates(
        tmp_path,
        run_id_prefixes=("corrected-e1-",),
    )

    assert [candidate.run_id for candidate in candidates] == ["corrected-e1-run"]


def test_judge_batch_gate_blocks_before_creating_output_or_calling_api(tmp_path, monkeypatch):
    runs_root = tmp_path / "runs"
    _write_manifest(runs_root, run_id="valid-run", group="A", status="VALID")
    gate = tmp_path / "gate.json"
    precheck = tmp_path / "precheck.json"
    gate.write_text(
        json.dumps({"status": "NOT_RUN", "resource_precheck": "precheck.json"}),
        encoding="utf-8",
    )
    precheck.write_text(
        json.dumps({"gemini": {"billing_boundary": "UNKNOWN"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_independent_judges, "FORMAL_GATE_PATH", gate)
    output_dir = tmp_path / "judgements"

    with pytest.raises(FormalGateError, match="gate is not open"):
        run_independent_judges.run_judge_batch(
            runs_root=runs_root,
            output_dir=output_dir,
            batch_id="judge-probe",
        )

    assert not output_dir.exists()
