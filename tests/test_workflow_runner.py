from __future__ import annotations

from pathlib import Path

import pytest

from county_research_ai.application.context import ResearchContext
from county_research_ai.application.results import ResearchRunResult
from county_research_ai.application.workflow import WorkflowRunner
from county_research_ai.config import PipelineStages
from county_research_ai.exceptions import ResearchStageError
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
