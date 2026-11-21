"""动态路由：Supervisor 计划 → Send 并行分发；Critic → 补充研究或收束。"""
from __future__ import annotations

import logging

from langgraph.types import Send

from ..agents.registry import specialist_kinds
from .state import ResearchState

logger = logging.getLogger(__name__)

_SPECIALIST_NODES = {kind.value: f"agent_{kind.value}" for kind in specialist_kinds()}


def specialist_node_name(agent: str) -> str:
    return _SPECIALIST_NODES.get(agent, "")


def dispatch_specialists(state: ResearchState) -> list[Send] | str:
    """把计划中的任务并行发送到各专业 Agent 子图。

    没有任务时直接进入聚合节点，避免空图运行。
    """
    sends: list[Send] = []
    seen: set[str] = set()
    for task in state.get("tasks", []) or []:
        agent = str(task.get("agent", ""))
        node = _SPECIALIST_NODES.get(agent)
        if not node:
            logger.warning("未知 Agent 任务被忽略 | agent=%s", agent)
            continue
        if node in seen:
            # 同一轮同一 Agent 只运行一次（Supervisor 已去重，这里兜底）
            continue
        seen.add(node)
        sends.append(Send(node, {"task": task}))
    return sends or "aggregate"


def after_critic(state: ResearchState) -> str:
    """Critic 判定不充分且仍有轮次预算时，进入补充检索。"""
    critique = state.get("critique") or {}
    round_no = int(state.get("round", 1) or 1)
    max_rounds = int(state.get("max_rounds", 1) or 1)
    followups = [q for q in state.get("followup_queries", []) or [] if q]
    if (
        not bool(critique.get("is_sufficient", False))
        and round_no < max_rounds
        and followups
    ):
        return "supplement"
    return "build_graph"


__all__ = ["after_critic", "dispatch_specialists", "specialist_node_name"]
