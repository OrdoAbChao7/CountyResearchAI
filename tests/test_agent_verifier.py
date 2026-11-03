from __future__ import annotations

from county_research_ai.agent.models import AgentState
from county_research_ai.models import ResearchRequest


def test_verifier_rejects_finish_without_report():
    from county_research_ai.agent.verifier import AgentVerifier

    state = AgentState.from_request(
        ResearchRequest(county="安吉县", focus="竹产业")
    )

    result = AgentVerifier().verify_final(state)

    assert result.ok is False
    assert result.code == "missing_report"


def test_verifier_accepts_report_with_source(tmp_path):
    from county_research_ai.agent.verifier import AgentVerifier

    report_path = tmp_path / "report.md"
    report_path.write_text(
        "# 安吉县\n\n## 竹产业\n\n来源: https://example.gov.cn/report\n",
        encoding="utf-8",
    )
    state = AgentState.from_request(
        ResearchRequest(county="安吉县", focus="竹产业")
    )
    state.report_path = str(report_path)

    result = AgentVerifier().verify_final(state)

    assert result.ok is True


def test_verifier_allows_empty_search_result_to_continue():
    from county_research_ai.agent.base import ToolResult
    from county_research_ai.agent.models import AgentPlanStep, ToolStatus
    from county_research_ai.agent.verifier import AgentVerifier

    state = AgentState.from_request(ResearchRequest(county="安吉县"))
    result = AgentVerifier().verify_step(
        state,
        AgentPlanStep(tool="search_materials", reason="collect evidence"),
        ToolResult(
            tool_name="search_materials",
            status=ToolStatus.SUCCESS,
            observation="collected 0 raw documents",
        ),
    )

    assert result.ok is True
