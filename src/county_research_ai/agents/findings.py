"""各专业 Agent 的结构化输出模型。

共同字段：
- summary: 面向 Supervisor 的结论摘要
- claims: 证据绑定结论 [{text, evidence_ids, confidence}]
- gaps: 未解决的问题
- confidence / metrics
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentOutput(BaseModel):
    summary: str = ""
    claims: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    metrics: dict[str, Any] = Field(default_factory=dict)


class MacroFindings(AgentOutput):
    gdp: str = ""
    growth: str = ""
    fiscal: str = ""
    population: str = ""
    indicators: list[dict[str, Any]] = Field(default_factory=list)


class IndustryFindings(AgentOutput):
    segments: list[str] = Field(default_factory=list)
    chain_structure: str = ""
    leading_industries: list[str] = Field(default_factory=list)
    location_quotient: float | None = None
    output_value: str = ""


class EnterpriseFindings(AgentOutput):
    enterprises: list[dict[str, Any]] = Field(default_factory=list)
    key_relations: list[dict[str, Any]] = Field(default_factory=list)
    concentration: str = ""


class PolicyFindings(AgentOutput):
    policies: list[dict[str, Any]] = Field(default_factory=list)
    support_measures: list[str] = Field(default_factory=list)


class InnovationFindings(AgentOutput):
    technologies: list[str] = Field(default_factory=list)
    patents: list[str] = Field(default_factory=list)
    institutions: list[str] = Field(default_factory=list)


class GeoFindings(AgentOutput):
    parks: list[dict[str, Any]] = Field(default_factory=list)
    transport: str = ""
    land: str = ""
    resource_endowment: str = ""


class QuantFindings(AgentOutput):
    computed_metrics: list[dict[str, Any]] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class OpportunityFindings(AgentOutput):
    opportunities: list[dict[str, Any]] = Field(default_factory=list)
    missing_segments: list[str] = Field(default_factory=list)
    weak_segments: list[str] = Field(default_factory=list)
    external_dependencies: list[str] = Field(default_factory=list)
    specialization_score: float = 0.0


class ReportDraft(AgentOutput):
    executive_summary: str = ""
    sections: list[dict[str, Any]] = Field(default_factory=list)
    top_opportunities: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "AgentOutput",
    "EnterpriseFindings",
    "GeoFindings",
    "IndustryFindings",
    "InnovationFindings",
    "MacroFindings",
    "OpportunityFindings",
    "PolicyFindings",
    "QuantFindings",
    "ReportDraft",
]
