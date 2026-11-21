"""专业研究 Agent。

每个子包包含独立的 System Prompt、工具白名单、结构化输出模型与
确定性降级策略。Agent 通过 Tools 调用 services，不依赖任何 Workflow。
"""
from .base import AgentContext, AgentSpec, SpecialistAgent, ToolObservation
from .critic import CriticAgent
from .registry import agent_catalog, build_specialist, specialist_kinds
from .report import ReportAgent

__all__ = [
    "AgentContext",
    "AgentSpec",
    "CriticAgent",
    "ReportAgent",
    "SpecialistAgent",
    "ToolObservation",
    "agent_catalog",
    "build_specialist",
    "specialist_kinds",
]
