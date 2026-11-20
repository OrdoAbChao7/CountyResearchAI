from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts import run_independent_report_qa, score_independent_claims

from county_research_ai.evaluation.gate import FormalGateError


def _write_valid_report_manifest(root: Path) -> None:
    run_dir = root / "formal-valid"
    run_dir.mkdir(parents=True)
    report = run_dir / "report.md"
    report.write_text("研究报告：地区生产总值为352.6094亿元。", encoding="utf-8")
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "formal-valid",
                "experiment_id": "E1",
                "group": "A",
                "county": "德清县",
                "task_id": "snapshot",
                "mode": "snapshot",
                "status": "VALID",
                "formal_target": True,
                "artifacts": {"report": f"report.md:{digest}"},
            }
        ),
        encoding="utf-8",
    )


def _closed_gate(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "NOT_RUN",
                "resource_precheck": "precheck.json",
            }
        ),
        encoding="utf-8",
    )
    path.with_name("precheck.json").write_text(
        json.dumps({"gemini": {"billing_boundary": "UNKNOWN"}}),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("module", "runner"),
    [
        (run_independent_report_qa, "run_qa_batch"),
        (score_independent_claims, "run_claim_batch"),
    ],
)
def test_post_run_scoring_gate_blocks_before_output_or_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module, runner: str
):
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _write_valid_report_manifest(runs_root)
    gate = tmp_path / "gate.json"
    _closed_gate(gate)
    monkeypatch.setattr(module, "FORMAL_GATE_PATH", gate)
    output_dir = tmp_path / "output"

    with pytest.raises(FormalGateError, match="gate is not open"):
        getattr(module, runner)(
            runs_root=runs_root,
            output_dir=output_dir,
            batch_id="closed-gate-probe",
        )

    assert not output_dir.exists()
