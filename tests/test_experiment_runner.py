from __future__ import annotations

import time
from pathlib import Path

from county_research_ai.evaluation.experiment_models import RunStatus
from county_research_ai.evaluation.experiment_runner import (
    ExecutionOutcome,
    ExperimentRunner,
    ExperimentRunSpec,
)
from county_research_ai.evaluation.resource_manager import (
    ResourceExhaustedError,
    ResourceLimit,
    ResourceManager,
    ResourceOverrunError,
    ResourceRequest,
)


def _spec(run_id: str = "run-1") -> ExperimentRunSpec:
    return ExperimentRunSpec(
        run_id=run_id,
        experiment_id="E1",
        group="A",
        county="新地区县",
        task_id="snapshot",
        mode="snapshot",
        model="gemini-3.1-flash-lite",
        search_provider="tavily",
        config={"model": "gemini-3.1-flash-lite", "task": "snapshot"},
    )


def test_runner_persists_valid_artifact_and_separates_run_directory(tmp_path):
    runner = ExperimentRunner(tmp_path / "runs", ResourceManager(tmp_path / "resources.sqlite", limits={}))

    def execute(artifact):
        path, digest = artifact.write_text("report.md", "valid report")
        return ExecutionOutcome(artifacts={"report": (path, digest)}, usage_known=True)

    manifest = runner.run(_spec(), execute)

    assert manifest.status == RunStatus.VALID
    assert (tmp_path / "runs" / "run-1" / "report.md").is_file()
    assert manifest.artifacts["report"]
    assert manifest.duration_seconds is not None
    assert manifest.resource_usage == {}


def test_runner_records_resource_usage_for_this_run(tmp_path):
    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={("gemini", "model", "llm"): ResourceLimit(10)},
    )
    runner = ExperimentRunner(tmp_path / "runs", manager)

    def execute(artifact):
        lease = manager.reserve(
            ResourceRequest("gemini", "model", "llm", 2, "run-usage")
        )
        manager.settle(lease.lease_id, 2)
        return ExecutionOutcome(artifacts={}, usage_known=True)

    manifest = runner.run(_spec("run-usage"), execute)

    assert manifest.status == RunStatus.VALID
    assert manifest.resource_usage == {"gemini:model:llm": 2}


def test_runner_marks_mock_outcome_invalid_but_keeps_artifacts(tmp_path):
    runner = ExperimentRunner(tmp_path / "runs", ResourceManager(tmp_path / "resources.sqlite", limits={}))

    def execute(artifact):
        path, digest = artifact.write_text("report.md", "mock report")
        return ExecutionOutcome(
            artifacts={"report": (path, digest)}, usage_known=True, mock_detected=True
        )

    manifest = runner.run(_spec(), execute)

    assert manifest.status == RunStatus.INVALID_MOCK
    assert (tmp_path / "runs" / "run-1" / "report.md").read_text(encoding="utf-8") == "mock report"


def test_runner_marks_missing_usage_invalid_without_dropping_failure_evidence(tmp_path):
    runner = ExperimentRunner(tmp_path / "runs", ResourceManager(tmp_path / "resources.sqlite", limits={}))

    def execute(artifact):
        return ExecutionOutcome(artifacts={}, usage_known=False)

    manifest = runner.run(_spec(), execute)

    assert manifest.status == RunStatus.INVALID_USAGE_UNKNOWN
    assert (tmp_path / "runs" / "run-1" / "manifest.json").is_file()


def test_runner_marks_wall_clock_budget_exhaustion(tmp_path):
    runner = ExperimentRunner(
        tmp_path / "runs",
        ResourceManager(tmp_path / "resources.sqlite", limits={}),
        max_duration_seconds=0.001,
    )

    def execute(artifact):
        time.sleep(0.01)
        return ExecutionOutcome(artifacts={}, usage_known=True)

    manifest = runner.run(_spec("wall-clock-run"), execute)

    assert manifest.status == RunStatus.BUDGET_EXHAUSTED
    assert "wall-clock budget exceeded" in (manifest.error or "")


def test_runner_marks_resource_exhaustion_blocked(tmp_path):
    runner = ExperimentRunner(tmp_path / "runs", ResourceManager(tmp_path / "resources.sqlite", limits={}))

    def execute(artifact):
        raise ResourceExhaustedError("budget")

    manifest = runner.run(_spec(), execute)

    assert manifest.status == RunStatus.BLOCKED


def test_runner_marks_settlement_overrun_invalid_accounting(tmp_path):
    runner = ExperimentRunner(tmp_path / "runs", ResourceManager(tmp_path / "resources.sqlite", limits={}))

    def execute(artifact):
        raise ResourceOverrunError("actual usage exceeded budget")

    manifest = runner.run(_spec("overrun-run"), execute)

    assert manifest.status == RunStatus.INVALID_RESOURCE_ACCOUNTING


def test_runner_marks_unsettled_lease_invalid_accounting_after_execution_error(tmp_path):
    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={("gemini", "model", "llm"): ResourceLimit(10)},
    )
    runner = ExperimentRunner(tmp_path / "runs", manager)

    def execute(artifact):
        manager.reserve(ResourceRequest("gemini", "model", "llm", 2, "unsettled-run"))
        raise RuntimeError("research stage failed")

    manifest = runner.run(_spec("unsettled-run"), execute)

    assert manifest.status == RunStatus.INVALID_RESOURCE_ACCOUNTING
    assert "unsettled resource lease" in (manifest.error or "")


def test_runner_normalizes_relative_root_before_recording_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = ExperimentRunner(Path("runs"), ResourceManager(Path("resources.sqlite"), limits={}))

    def execute(artifact):
        path, digest = artifact.write_text("report.md", "valid report")
        return ExecutionOutcome(artifacts={"report": (path, digest)}, usage_known=True)

    manifest = runner.run(_spec("relative-run"), execute)

    assert manifest.status == RunStatus.VALID
