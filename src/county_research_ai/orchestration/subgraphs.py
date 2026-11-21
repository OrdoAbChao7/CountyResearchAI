"""专业 Agent 子图。

每个专业 Agent 是一个独立的 LangGraph 子图（单节点），拥有自己的状态契约。
父图通过 ``Send`` 把任务并发分发到这些子图，输出通过 reducer 合并。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..domain.intelligence import AgentKind
from .state import SpecialistState

SpecialistNode = Callable[[SpecialistState, dict[str, Any]], dict[str, Any]]


def build_specialist_subgraph(kind: AgentKind, node: SpecialistNode) -> Any:
    graph: StateGraph = StateGraph(SpecialistState)
    graph.add_node("run", node)
    graph.add_edge(START, "run")
    graph.add_edge("run", END)
    return graph.compile(name=f"agent_{kind.value}")


__all__ = ["build_specialist_subgraph"]
