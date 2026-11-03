from __future__ import annotations

from pathlib import Path

from county_research_ai.agent.base import ToolResult, ToolSpec
from county_research_ai.agent.models import AgentPlanStep, AgentState, AgentStatus, ToolStatus
from county_research_ai.agent.planner import FallbackPlanner
from county_research_ai.agent.registry import ToolRegistry
from county_research_ai.models import (
    AnalysisResult,
    CountyInfo,
    ProcessedData,
    RawDoc,
    ReportSection,
    ResearchReport,
    ResearchRequest,
)


class RuntimeTool:
    def __init__(self, name, action):
        self.name = name
        self.description = name
        self._action = action

    def spec(self):
        return ToolSpec(name=self.name, description=self.description)

    def execute(self, state: AgentState, arguments: dict):
        return self._action(state, arguments)


def _tools(tmp_path: Path, *, with_discovery: bool = False):
    def search(state, arguments):
        return ToolResult(
            tool_name="search_materials",
            status=ToolStatus.SUCCESS,
            observation="collected 1 raw documents",
            state_patch={
                "raw_docs": [
                    RawDoc(title="统计公报", url="https://example.gov.cn/a", content="竹产业产值"),
                ]
            },
        )

    def discover(state, arguments):
        return ToolResult(
            tool_name="discover_focus",
            status=ToolStatus.SUCCESS,
            observation="selected focus: 竹产业",
            state_patch={"request": state.request.model_copy(update={"focus": "竹产业"})},
        )

    def evidence(state, arguments):
        county = CountyInfo.from_name(state.request.county)
        processed = ProcessedData(county=county, focus=state.request.focus or "竹产业", docs=state.raw_docs)
        return ToolResult(
            tool_name="build_evidence_pack",
            status=ToolStatus.SUCCESS,
            observation="built evidence pack",
            state_patch={"processed": processed},
        )

    def analyze(state, arguments):
        return ToolResult(
            tool_name="analyze_research",
            status=ToolStatus.SUCCESS,
            observation="analysis completed",
            state_patch={
                "snapshot_analyses": [
                    AnalysisResult(task="industry_status", content="产业现状"),
                ]
            },
        )

    def render(state, arguments):
        report_path = tmp_path / "report.md"
        report_path.write_text(
            f"# {state.request.county}\n\n## {state.request.focus or '竹产业'}\n\n来源: https://example.gov.cn/a\n",
            encoding="utf-8",
        )
        report = ResearchReport(
            county=CountyInfo.from_name(state.request.county),
            focus=state.request.focus or "竹产业",
            sections=[ReportSection(title="执行摘要", content="产业现状", order=1)],
        )
        return ToolResult(
            tool_name="render_report",
            status=ToolStatus.SUCCESS,
            observation="report written",
            state_patch={"report": report, "report_path": str(report_path)},
        )

    tools = [
        RuntimeTool("search_materials", search),
        RuntimeTool("build_evidence_pack", evidence),
        RuntimeTool("analyze_research", analyze),
        RuntimeTool("render_report", render),
    ]
    if with_discovery:
        tools.insert(1, RuntimeTool("discover_focus", discover))
    return tools


def test_runtime_executes_snapshot_and_persists_trace(tmp_path):
    from county_research_ai.agent.runtime import AgentRuntime
    from county_research_ai.agent.trace import JsonTraceStore
    from county_research_ai.agent.verifier import AgentVerifier

    runtime = AgentRuntime(
        planner=FallbackPlanner(),
        registry=ToolRegistry(_tools(tmp_path)),
        verifier=AgentVerifier(),
        trace_store=JsonTraceStore(tmp_path / "traces"),
    )

    result = runtime.run(ResearchRequest(county="安吉县", focus="竹产业"))

    assert result.state.status == AgentStatus.COMPLETED
    assert result.trace.status == AgentStatus.COMPLETED
    assert [item.tool_name for item in result.trace.observations] == [
        "search_materials", "build_evidence_pack", "analyze_research", "render_report", "finish",
    ]
    assert result.report_path and result.report_path.exists()
    assert result.trace_path and result.trace_path.exists()


def test_runtime_discovers_focus_before_building_evidence(tmp_path):
    from county_research_ai.agent.runtime import AgentRuntime
    from county_research_ai.agent.verifier import AgentVerifier

    result = AgentRuntime(
        planner=FallbackPlanner(),
        registry=ToolRegistry(_tools(tmp_path, with_discovery=True)),
        verifier=AgentVerifier(),
        max_steps=8,
    ).run(ResearchRequest(county="安吉县"))

    assert result.state.status == AgentStatus.COMPLETED
    assert result.state.request.focus == "竹产业"
    assert [item.tool_name for item in result.trace.observations][1] == "discover_focus"


def test_runtime_fails_when_max_steps_is_exceeded(tmp_path):
    from county_research_ai.agent.runtime import AgentRuntime
    from county_research_ai.agent.verifier import AgentVerifier

    result = AgentRuntime(
        planner=FallbackPlanner(),
        registry=ToolRegistry(_tools(tmp_path)),
        verifier=AgentVerifier(),
        max_steps=1,
    ).run(ResearchRequest(county="安吉县", focus="竹产业"))

    assert result.state.status == AgentStatus.FAILED
    assert result.trace.failure_code == "max_steps_exceeded"


def test_runtime_records_unknown_tool_and_terminates():
    from county_research_ai.agent.runtime import AgentRuntime
    from county_research_ai.agent.verifier import AgentVerifier

    class UnknownPlanner:
        def next_step(self, state, tool_specs):
            return AgentPlanStep(tool="not_registered", reason="bad action")

    result = AgentRuntime(
        planner=UnknownPlanner(),
        registry=ToolRegistry(),
        verifier=AgentVerifier(),
        max_steps=2,
    ).run(ResearchRequest(county="安吉县"))

    assert result.state.status == AgentStatus.FAILED
    assert any(error.code == "invalid_tool" for error in result.trace.errors)


def test_runtime_captures_tool_exception(tmp_path):
    from county_research_ai.agent.runtime import AgentRuntime
    from county_research_ai.agent.verifier import AgentVerifier

    def explode(state, arguments):
        raise RuntimeError("network unavailable")

    result = AgentRuntime(
        planner=FallbackPlanner(),
        registry=ToolRegistry([RuntimeTool("search_materials", explode)]),
        verifier=AgentVerifier(),
        max_steps=2,
    ).run(ResearchRequest(county="安吉县"))

    assert result.state.status == AgentStatus.FAILED
    assert any(error.code == "tool_exception" for error in result.trace.errors)
    assert result.trace.observations[0].status == ToolStatus.ERROR
