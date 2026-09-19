"""Agent 工具注册表。"""
from __future__ import annotations

from collections.abc import Iterable

from .base import AgentTool, ToolSpec


class AgentToolError(ValueError):
    """工具注册或查找失败。"""


class ToolRegistry:
    """限制 Planner 可调用范围的工具注册表。"""

    def __init__(self, tools: Iterable[AgentTool] | None = None) -> None:
        self._tools: dict[str, AgentTool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: AgentTool) -> None:
        if tool.name in self._tools:
            raise AgentToolError(f"agent tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise AgentToolError(f"unknown agent tool: {name}") from exc

    def describe(self) -> list[ToolSpec]:
        return [self._tools[name].spec() for name in sorted(self._tools)]
