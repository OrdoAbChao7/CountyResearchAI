"""Agent 抽象接口。"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .models import AgentState, ToolStatus


class ToolSpec(BaseModel):
    """给 Planner 使用的工具描述。"""

    name: str
    description: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """工具执行结果和受控状态更新。"""

    tool_name: str
    status: ToolStatus
    observation: str = ""
    state_patch: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    error_code: str = ""
    retryable: bool = False


@runtime_checkable
class AgentTool(Protocol):
    name: str
    description: str

    def spec(self) -> ToolSpec: ...

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult: ...
