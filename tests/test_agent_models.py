from __future__ import annotations

import pytest

from county_research_ai.models import ResearchRequest


def test_agent_state_starts_pending_with_request():
    from county_research_ai.agent.models import AgentState, AgentStatus

    state = AgentState.from_request(
        ResearchRequest(county="安吉县", focus="竹产业", mode="snapshot")
    )

    assert state.status == AgentStatus.PENDING
    assert state.request.county == "安吉县"
    assert state.steps_used == 0
    assert state.raw_docs == []


def test_plan_step_requires_tool_and_reason():
    from county_research_ai.agent.models import AgentPlanStep

    step = AgentPlanStep(
        tool="search_materials",
        reason="需要先收集资料",
        arguments={"county": "安吉县"},
    )

    assert step.tool == "search_materials"
    assert step.is_final is False


def test_state_apply_patch_rejects_unknown_fields():
    from county_research_ai.agent.models import AgentState

    state = AgentState.from_request(ResearchRequest(county="安吉县"))

    with pytest.raises(ValueError, match="not_allowed"):
        state.apply_patch({"not_allowed": "value"})
