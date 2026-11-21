"""LangGraph 主图装配。

START → intake → supervise → (Send 并行专业 Agent) → aggregate → critic
      → 补充检索 → supervise（反思轮）或 → build_graph → opportunity → report
      → finalize → END
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..agents.registry import specialist_kinds
from .nodes import (
    aggregate_node,
    critic_node,
    finalize_node,
    graph_build_node,
    intake_node,
    make_agent_node,
    opportunity_node,
    report_node,
    supervise_node,
    supplement_node,
)
from .routing import after_critic, dispatch_specialists
from .state import ResearchState
from .subgraphs import build_specialist_subgraph

logger = logging.getLogger(__name__)

SPECIALIST_KINDS = specialist_kinds()


def _after_intake(state: ResearchState) -> str:
    if state.get("status") == "failed" or not state.get("county"):
        return "finalize"
    return "supervise"


def build_research_graph(
    *,
    checkpointer: Any = None,
    interrupt_before: list[str] | None = None,
) -> Any:
    """构建并编译研究主图。

    Args:
        checkpointer: LangGraph checkpointer；None 表示纯内存运行。
        interrupt_before: 可选的人工审核/测试中断点。生产环境默认为空；
            运维或测试可以在 ``report`` 前中断并从检查点恢复。
    """
    builder: StateGraph = StateGraph(ResearchState)

    builder.add_node("intake", intake_node)
    builder.add_node("supervise", supervise_node)
    for kind in SPECIALIST_KINDS:
        builder.add_node(
            f"agent_{kind.value}",
            build_specialist_subgraph(kind, make_agent_node(kind)),
        )
    builder.add_node("aggregate", aggregate_node)
    builder.add_node("critic", critic_node)
    builder.add_node("supplement", supplement_node)
    builder.add_node("build_graph", graph_build_node)
    builder.add_node("opportunity", opportunity_node)
    builder.add_node("report", report_node)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "intake")
    builder.add_conditional_edges(
        "intake",
        _after_intake,
        {"finalize": "finalize", "supervise": "supervise"},
    )
    builder.add_conditional_edges(
        "supervise",
        dispatch_specialists,
        {
            **{f"agent_{kind.value}": f"agent_{kind.value}" for kind in SPECIALIST_KINDS},
            "aggregate": "aggregate",
        },
    )
    # Send 扇出的每个 Agent 子图执行完后汇入 aggregate；
    # 没有这些出边，LangGraph 会把并行分支视为终点而提前结束。
    for kind in SPECIALIST_KINDS:
        builder.add_edge(f"agent_{kind.value}", "aggregate")
    builder.add_edge("aggregate", "critic")
    builder.add_conditional_edges(
        "critic",
        after_critic,
        {"supplement": "supplement", "build_graph": "build_graph"},
    )
    builder.add_edge("supplement", "supervise")
    builder.add_edge("build_graph", "opportunity")
    builder.add_edge("opportunity", "report")
    builder.add_edge("report", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before or [],
        name="county_research_v2",
    )


__all__ = ["SPECIALIST_KINDS", "build_research_graph"]
