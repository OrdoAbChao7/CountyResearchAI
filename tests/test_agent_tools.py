from __future__ import annotations

from pathlib import Path

import pytest

from county_research_ai.config import Settings
from county_research_ai.llm.analyzer import LLMAnalyzer
from county_research_ai.llm.long_history_analyzer import LongHistoryAnalyzer
from county_research_ai.llm.rise_fall_analyzer import RiseFallAnalyzer
from county_research_ai.models import (
    ResearchRequest,
)
from county_research_ai.processor import DocumentProcessor
from county_research_ai.reporting import ReportRenderer
from county_research_ai.reporting.long_history_renderer import LongHistoryReportRenderer
from county_research_ai.reporting.rise_fall_renderer import RiseFallReportRenderer
from county_research_ai.search.base import SearchProvider
from county_research_ai.storage.local_fs import LocalFSStorage


@pytest.fixture
def tool_context(tmp_settings: Settings, mock_llm, sample_docs):
    from county_research_ai.agent.tools import ResearchToolContext

    class StaticSearch(SearchProvider):
        name = "static"

        def search(self, query: str, max_results: int = 10):
            return sample_docs[:max_results]

    return ResearchToolContext(
        search=StaticSearch(),
        storage=LocalFSStorage(settings=tmp_settings),
        processor=DocumentProcessor(quality_config=tmp_settings.quality),
        analyzer=LLMAnalyzer(llm=mock_llm, settings=tmp_settings),
        rise_fall_analyzer=RiseFallAnalyzer(llm=mock_llm, settings=tmp_settings),
        long_history_analyzer=LongHistoryAnalyzer(llm=mock_llm, settings=tmp_settings),
        renderer=ReportRenderer(),
        rise_fall_renderer=RiseFallReportRenderer(),
        long_history_renderer=LongHistoryReportRenderer(),
        settings=tmp_settings,
    )


def test_search_tool_writes_raw_docs_to_state(tool_context, sample_county):
    from county_research_ai.agent.models import AgentState, ToolStatus
    from county_research_ai.agent.tools import SearchMaterialsTool

    state = AgentState.from_request(
        ResearchRequest(county=sample_county.name, focus="竹产业", mode="snapshot")
    )
    result = SearchMaterialsTool(tool_context).execute(
        state, {"county": "安吉县", "focus": "竹产业", "mode": "snapshot"}
    )

    assert result.status == ToolStatus.SUCCESS
    assert result.state_patch["raw_docs"]


def test_discovery_tool_writes_selected_focus(tool_context, sample_docs):
    from county_research_ai.agent.models import AgentState, ToolStatus
    from county_research_ai.agent.tools import FocusDiscoveryTool

    state = AgentState.from_request(ResearchRequest(county="安吉县"))
    state.raw_docs = sample_docs
    result = FocusDiscoveryTool(tool_context).execute(state, {})

    assert result.status == ToolStatus.SUCCESS
    assert result.state_patch["discovery"].selected_focus == "特色农业"
    assert result.state_patch["request"].focus == "特色农业"


def test_evidence_tool_builds_processed_data(tool_context, sample_county, sample_docs):
    from county_research_ai.agent.models import AgentState, ToolStatus
    from county_research_ai.agent.tools import EvidencePackTool

    state = AgentState.from_request(
        ResearchRequest(county=sample_county.name, focus="竹产业")
    )
    state.raw_docs = sample_docs
    result = EvidencePackTool(tool_context).execute(state, {"focus": "竹产业"})

    assert result.status == ToolStatus.SUCCESS
    assert result.state_patch["processed"].focus == "竹产业"
    assert result.state_patch["processed"].docs


def test_analysis_tool_dispatches_all_modes(tool_context, sample_county, sample_processed_data):
    from county_research_ai.agent.models import AgentState, ToolStatus
    from county_research_ai.agent.tools import ResearchAnalysisTool

    tool = ResearchAnalysisTool(tool_context)
    for mode, field in (
        ("snapshot", "snapshot_analyses"),
        ("rise-fall", "rise_fall_analysis"),
        ("long-history", "long_history_analysis"),
    ):
        state = AgentState.from_request(
            ResearchRequest(county=sample_county.name, focus="竹产业", mode=mode)
        )
        state.processed = sample_processed_data
        result = tool.execute(state, {})

        assert result.status == ToolStatus.SUCCESS
        assert result.state_patch[field] is not None


def test_analysis_tool_keeps_requested_mode_when_llm_supplies_alias(
    tool_context, sample_county, sample_processed_data,
):
    from county_research_ai.agent.models import AgentState, ToolStatus
    from county_research_ai.agent.tools import ResearchAnalysisTool

    state = AgentState.from_request(
        ResearchRequest(county=sample_county.name, focus="竹产业", mode="snapshot")
    )
    state.processed = sample_processed_data

    result = ResearchAnalysisTool(tool_context).execute(
        state, {"mode": "rise_fall_analysis"},
    )

    assert result.status == ToolStatus.SUCCESS
    assert result.state_patch["snapshot_analyses"]
    assert "rise_fall_analysis" not in result.state_patch


def test_report_tool_persists_snapshot_report(tool_context, sample_county, sample_processed_data):
    from county_research_ai.agent.models import AgentState, ToolStatus
    from county_research_ai.agent.tools import ReportTool

    state = AgentState.from_request(
        ResearchRequest(county=sample_county.name, focus="竹产业", mode="snapshot")
    )
    state.processed = sample_processed_data
    state.snapshot_analyses = tool_context.analyzer.analyze(
        sample_county, "竹产业", sample_processed_data,
    )
    result = ReportTool(tool_context).execute(state, {})
    report_path = Path(result.state_patch["report_path"])

    assert result.status == ToolStatus.SUCCESS
    assert report_path.exists()
    assert "安吉县" in report_path.read_text(encoding="utf-8")
