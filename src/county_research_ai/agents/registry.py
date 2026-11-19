"""专业 Agent 注册表：按 AgentKind 构建真实的 Agent 实例。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..domain.intelligence import AgentKind
from .base import AgentSpec, SpecialistAgent
from .enterprise import agent as enterprise_agent
from .geo import agent as geo_agent
from .industry import agent as industry_agent
from .innovation import agent as innovation_agent
from .macro import agent as macro_agent
from .opportunity import agent as opportunity_agent
from .policy import agent as policy_agent
from .quantitative import agent as quantitative_agent

SpecialistBuilder = Callable[..., SpecialistAgent]

BUILDERS: dict[AgentKind, SpecialistBuilder] = {
    AgentKind.MACRO: macro_agent.build,
    AgentKind.INDUSTRY: industry_agent.build,
    AgentKind.ENTERPRISE: enterprise_agent.build,
    AgentKind.POLICY: policy_agent.build,
    AgentKind.INNOVATION: innovation_agent.build,
    AgentKind.GEO: geo_agent.build,
    AgentKind.QUANTITATIVE: quantitative_agent.build,
    AgentKind.OPPORTUNITY: opportunity_agent.build,
}

SPECS: dict[AgentKind, AgentSpec] = {
    AgentKind.MACRO: macro_agent.SPEC,
    AgentKind.INDUSTRY: industry_agent.SPEC,
    AgentKind.ENTERPRISE: enterprise_agent.SPEC,
    AgentKind.POLICY: policy_agent.SPEC,
    AgentKind.INNOVATION: innovation_agent.SPEC,
    AgentKind.GEO: geo_agent.SPEC,
    AgentKind.QUANTITATIVE: quantitative_agent.SPEC,
    AgentKind.OPPORTUNITY: opportunity_agent.SPEC,
}


def specialist_kinds() -> list[AgentKind]:
    return list(BUILDERS)


def build_specialist(
    kind: AgentKind,
    llm: Any,
    tools: Any,
    *,
    max_steps: int | None = None,
    max_llm_calls: int | None = None,
) -> SpecialistAgent:
    builder = BUILDERS.get(kind)
    if builder is None:
        raise ValueError(f"no specialist agent registered for kind={kind}")
    return builder(llm, tools, max_steps=max_steps, max_llm_calls=max_llm_calls)


def spec_for(kind: AgentKind) -> AgentSpec:
    try:
        return SPECS[kind]
    except KeyError as exc:
        raise ValueError(f"no spec for kind={kind}") from exc


def agent_catalog() -> list[dict[str, Any]]:
    """供 API/文档展示的 Agent 能力清单。"""
    return [
        {
            "kind": spec.kind.value,
            "name": spec.name,
            "description": spec.description,
            "tools": list(spec.tools),
            "max_steps": spec.max_steps,
            "max_llm_calls": spec.max_llm_calls,
        }
        for spec in SPECS.values()
    ]


__all__ = [
    "BUILDERS",
    "SPECS",
    "agent_catalog",
    "build_specialist",
    "spec_for",
    "specialist_kinds",
]
