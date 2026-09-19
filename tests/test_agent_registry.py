from __future__ import annotations

import pytest

from county_research_ai.agent.models import AgentState, ToolStatus
from county_research_ai.models import ResearchRequest


class EchoTool:
    name = "echo"
    description = "返回输入摘要"

    def spec(self):
        from county_research_ai.agent.base import ToolSpec

        return ToolSpec(name=self.name, description=self.description, arguments={})

    def execute(self, state, arguments):
        from county_research_ai.agent.base import ToolResult

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            observation=str(arguments),
            state_patch={},
        )


def test_registry_register_get_and_describe():
    from county_research_ai.agent.registry import ToolRegistry

    registry = ToolRegistry([EchoTool()])

    assert registry.get("echo").name == "echo"
    assert registry.describe()[0].name == "echo"


def test_registry_rejects_duplicate_tool():
    from county_research_ai.agent.registry import AgentToolError, ToolRegistry

    registry = ToolRegistry([EchoTool()])

    with pytest.raises(AgentToolError, match="echo"):
        registry.register(EchoTool())


def test_registry_rejects_unknown_tool():
    from county_research_ai.agent.registry import AgentToolError, ToolRegistry

    registry = ToolRegistry([EchoTool()])

    with pytest.raises(AgentToolError, match="missing"):
        registry.get("missing")


def test_echo_tool_contract_returns_tool_result():
    state = AgentState.from_request(ResearchRequest(county="安吉县"))
    result = EchoTool().execute(state, {"value": "ok"})

    assert result.status == ToolStatus.SUCCESS
    assert result.tool_name == "echo"
