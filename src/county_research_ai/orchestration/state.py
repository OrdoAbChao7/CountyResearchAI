"""LangGraph 共享状态。

状态保持 JSON 可序列化，以便 SqliteSaver 检查点可以跨进程恢复。
运行期对象（证据服务、事件发射器）放在 ``RunnableConfig.configurable`` 中，
绝不进入状态。
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class ResearchState(TypedDict, total=False):
    """一次研究运行的主图状态。"""

    run_id: str
    county: str
    focus: str
    mode: str
    objectives: list[str]
    research_question: str

    # Supervisor 规划
    round: int
    max_rounds: int
    plan: dict[str, Any]
    tasks: list[dict[str, Any]]

    # 专业 Agent 结果（并行分支通过 reducer 合并）
    results: Annotated[list[dict[str, Any]], operator.add]
    aggregated: dict[str, Any]

    # Critic 审计与补充研究
    critique: dict[str, Any] | None
    followup_queries: list[str]
    supplements: Annotated[list[dict[str, Any]], operator.add]

    # 知识图谱
    graph_stats: dict[str, Any]

    # 机会与报告
    opportunities: list[dict[str, Any]]
    opportunity_notes: list[str]
    report: dict[str, Any]

    # 运行状态
    status: str
    error: str
    degraded: bool
    evidence_count: int
    progress: float


class SpecialistState(TypedDict, total=False):
    """专业 Agent 子图状态。

    子图输出 ``results``，与父图同名 reducer 合并；这样父图无需为
    每个专业 Agent 维护不同的状态字段。
    """

    task: dict[str, Any]
    results: Annotated[list[dict[str, Any]], operator.add]


def initial_state(
    *,
    run_id: str,
    county: str,
    focus: str = "",
    mode: str = "snapshot",
    objectives: list[str] | None = None,
    max_rounds: int = 2,
) -> ResearchState:
    return ResearchState(
        run_id=run_id,
        county=county,
        focus=focus,
        mode=mode,
        objectives=objectives or [],
        research_question="",
        round=0,
        max_rounds=max_rounds,
        plan=None,  # type: ignore[typeddict-item]
        tasks=[],
        results=[],
        aggregated={},
        critique=None,
        followup_queries=[],
        supplements=[],
        graph_stats={},
        opportunities=[],
        opportunity_notes=[],
        report={},
        status="running",
        error="",
        degraded=False,
        evidence_count=0,
        progress=0.0,
    )


__all__ = ["ResearchState", "SpecialistState", "initial_state"]
