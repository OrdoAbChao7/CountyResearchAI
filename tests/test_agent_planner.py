from __future__ import annotations

from county_research_ai.agent.models import AgentState
from county_research_ai.models import CountyInfo, ProcessedData, RawDoc, ResearchRequest


def test_parse_plan_step_accepts_plain_json_and_code_fence():
    from county_research_ai.agent.planner import parse_plan_step

    plain = '{"tool":"search_materials","reason":"先搜索","arguments":{}}'
    fenced = '```json\n{"tool":"finish","reason":"完成","arguments":{}}\n```'

    assert parse_plan_step(plain).tool == "search_materials"
    assert parse_plan_step(fenced).tool == "finish"


def test_fallback_planner_selects_search_first():
    from county_research_ai.agent.planner import FallbackPlanner

    state = AgentState.from_request(
        ResearchRequest(county="安吉县", focus="竹产业", mode="snapshot")
    )

    assert FallbackPlanner().next_step(state, []).tool == "search_materials"


def test_fallback_planner_inserts_discovery_without_focus():
    from county_research_ai.agent.planner import FallbackPlanner

    state = AgentState.from_request(ResearchRequest(county="安吉县"))
    state.raw_docs = [RawDoc(title="产业资料", url="https://example.com/a")]

    assert FallbackPlanner().next_step(state, []).tool == "discover_focus"


def test_fallback_planner_does_not_repeat_an_empty_search():
    from county_research_ai.agent.models import AgentObservation, ToolStatus
    from county_research_ai.agent.planner import FallbackPlanner

    state = AgentState.from_request(ResearchRequest(county="安吉县"))
    state.observations.append(
        AgentObservation(
            step_index=1,
            tool_name="search_materials",
            status=ToolStatus.SUCCESS,
            output_summary="collected 0 raw documents",
        )
    )

    assert FallbackPlanner().next_step(state, []).tool == "discover_focus"


def test_fallback_planner_moves_from_processing_to_analysis():
    from county_research_ai.agent.planner import FallbackPlanner

    state = AgentState.from_request(
        ResearchRequest(county="安吉县", focus="竹产业")
    )
    state.raw_docs = [RawDoc(title="产业资料", url="https://example.com/a")]
    state.processed = ProcessedData(
        county=CountyInfo(name="安吉县"),
        focus="竹产业",
    )

    assert FallbackPlanner().next_step(state, []).tool == "analyze_research"


def test_llm_planner_uses_fallback_for_malformed_response():
    from county_research_ai.agent.planner import LLMPlanner
    from county_research_ai.llm.base import LLMClient, LLMResponse

    class BrokenLLM(LLMClient):
        @property
        def name(self) -> str:
            return "broken"

        def chat(self, messages, **kwargs):
            return LLMResponse(content="not json", model="broken")

    state = AgentState.from_request(
        ResearchRequest(county="安吉县", focus="竹产业")
    )
    step = LLMPlanner(llm=BrokenLLM()).next_step(state, [])

    assert step.tool == "search_materials"
    assert step.planner_source == "fallback"


def test_llm_planner_falls_back_when_analysis_is_already_complete():
    from county_research_ai.agent.planner import LLMPlanner
    from county_research_ai.llm.base import LLMClient, LLMResponse
    from county_research_ai.models import AnalysisResult, ProcessedData

    class RepeatingLLM(LLMClient):
        @property
        def name(self) -> str:
            return "repeating"

        def chat(self, messages, **kwargs):
            return LLMResponse(
                content='{"tool":"analyze_research","reason":"再分析","arguments":{}}',
                model="repeating",
            )

    state = AgentState.from_request(
        ResearchRequest(county="安吉县", focus="竹产业", mode="snapshot")
    )
    state.raw_docs = [RawDoc(title="产业资料", url="https://example.com/a")]
    state.processed = ProcessedData(county=CountyInfo(name="安吉县"), focus="竹产业")
    state.snapshot_analyses = [AnalysisResult(task="industry_status", content="已完成")]

    step = LLMPlanner(llm=RepeatingLLM()).next_step(state, [])

    assert step.tool == "render_report"
    assert step.planner_source == "fallback"
