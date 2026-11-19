from __future__ import annotations

from pathlib import Path

import pytest

from county_research_ai.application.results import ResearchRunResult
from county_research_ai.application.workflow import WorkflowRunner
from county_research_ai.config import PipelineStages
from county_research_ai.exceptions import ResearchCancelledError, ResearchStageError
from county_research_ai.models import ResearchReport, ResearchRequest


class RecordingApplication:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def collect_materials(self, context):
        self.calls.append("collect")
        return context

    def discover_focus(self, context):
        self.calls.append("discover")
        return context.model_copy(update={"focus": "竹产业"})

    def build_evidence(self, context):
        self.calls.append("evidence")
        return context

    def analyze(self, context):
        self.calls.append("analyze")
        return context

    def render_report(self, context):
        self.calls.append("report")
        return ResearchRunResult(
            report=ResearchReport(county=context.county, focus=context.focus),
            report_path=Path("report.md"),
        )


def test_workflow_runner_executes_shared_stages_in_order() -> None:
    application = RecordingApplication()
    runner = WorkflowRunner(application=application, stages=PipelineStages())

    result = runner.run(ResearchRequest(county="巴中"))

    assert application.calls == ["collect", "discover", "evidence", "analyze", "report"]
    assert result.report.focus == "竹产业"


def test_workflow_runner_skips_discovery_when_focus_is_provided() -> None:
    application = RecordingApplication()
    runner = WorkflowRunner(application=application, stages=PipelineStages())

    runner.run(ResearchRequest(county="巴中", focus="茶产业"))

    assert application.calls == ["collect", "evidence", "analyze", "report"]


def test_workflow_runner_stops_after_stage_error() -> None:
    class FailingApplication(RecordingApplication):
        def build_evidence(self, context):
            self.calls.append("evidence")
            raise ResearchStageError(
                "failed", code="process_failed", stage="process"
            )

    application = FailingApplication()
    runner = WorkflowRunner(application=application, stages=PipelineStages())

    with pytest.raises(ResearchStageError):
        runner.run(ResearchRequest(county="巴中", focus="茶产业"))

    assert application.calls == ["collect", "evidence"]


def test_workflow_runner_respects_stage_switches() -> None:
    application = RecordingApplication()
    runner = WorkflowRunner(
        application=application,
        stages=PipelineStages(search=False, process=False, analyze=False, report=True),
    )

    runner.run(ResearchRequest(county="巴中", focus="茶产业"))

    assert application.calls == ["report"]


def test_workflow_runner_returns_context_with_report() -> None:
    application = RecordingApplication()
    runner = WorkflowRunner(application=application, stages=PipelineStages())

    result = runner.run(ResearchRequest(county="巴中", focus="茶产业"))

    assert result.context is not None
    assert result.context.report is result.report
    assert result.context.report_path == Path("report.md")


def test_workflow_runner_cancels_at_stage_boundary() -> None:
    application = RecordingApplication()
    runner = WorkflowRunner(application=application, stages=PipelineStages())
    cancel = {"value": False}

    def should_cancel() -> bool:
        return cancel["value"]

    def collect_materials(context):
        application.calls.append("collect")
        cancel["value"] = True
        return context

    application.collect_materials = collect_materials  # type: ignore[method-assign]

    with pytest.raises(ResearchCancelledError) as caught:
        runner.run(
            ResearchRequest(county="巴中", focus="茶产业"),
            should_cancel=should_cancel,
        )

    assert caught.value.stage == "evidence"
    assert application.calls == ["collect"]
