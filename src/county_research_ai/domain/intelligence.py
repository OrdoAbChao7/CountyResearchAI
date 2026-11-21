"""V2 智能产业研究平台的核心领域模型。

这些模型定义 Multi-Agent 研究、证据约束、机会发现与报告输出的
共享契约。所有 Agent 的最终产物都必须能落到这里的结构上。
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentKind(str, Enum):
    """专业 Agent 类型。"""

    SUPERVISOR = "supervisor"
    MACRO = "macro"
    INDUSTRY = "industry"
    ENTERPRISE = "enterprise"
    POLICY = "policy"
    INNOVATION = "innovation"
    GEO = "geo"
    QUANTITATIVE = "quantitative"
    CRITIC = "critic"
    OPPORTUNITY = "opportunity"
    REPORT = "report"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VerificationStatus(str, Enum):
    """结论/关系的证据状态。

    - VERIFIED:      有可追溯证据支撑，且证据可信度达标
    - INFERRED:      模型推断，尚未被独立证据证实
    - PENDING:       待核实（有线索但证据不足）
    - UNVERIFIED:    未发现证据
    """

    VERIFIED = "verified"
    INFERRED = "inferred"
    PENDING = "pending"
    UNVERIFIED = "unverified"


class Claim(BaseModel):
    """一条可审计的研究结论。"""

    claim_id: str = ""
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    source_agent: str = ""

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence_ids)


class ResearchTask(BaseModel):
    """Supervisor 分配给某个专业 Agent 的研究任务。"""

    task_id: str
    agent: AgentKind
    objective: str
    queries: list[str] = Field(default_factory=list)
    priority: int = 3
    round: int = 1
    parent_gap: str = ""  # 由 Critic 缺口触发时记录来源

    def summary_line(self) -> str:
        return f"[{self.agent.value}] {self.objective[:80]}"


class ResearchPlan(BaseModel):
    """Supervisor 的一轮研究计划。"""

    research_question: str = ""
    objectives: list[str] = Field(default_factory=list)
    tasks: list[ResearchTask] = Field(default_factory=list)
    rationale: str = ""
    round: int = 1
    planner_source: str = "llm"  # llm / deterministic

    def agents(self) -> list[AgentKind]:
        seen: list[AgentKind] = []
        for task in self.tasks:
            if task.agent not in seen:
                seen.append(task.agent)
        return seen


class AgentResult(BaseModel):
    """专业 Agent 的结构化输出。"""

    task_id: str = ""
    agent: AgentKind
    summary: str = ""
    claims: list[Claim] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    findings: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.5
    gaps: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    llm_calls: int = 0
    tool_calls: int = 0
    degraded: bool = False
    error: str = ""
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime = Field(default_factory=_utcnow)

    def all_evidence_ids(self) -> list[str]:
        ids: list[str] = list(self.evidence_ids)
        for claim in self.claims:
            ids.extend(claim.evidence_ids)
        # 去重且保持顺序
        return list(dict.fromkeys(i for i in ids if i))


class CritiqueFinding(BaseModel):
    """Critic 审计发现。"""

    kind: str  # unsupported_claim / missing_evidence / conflict / weak_source / gap
    description: str
    severity: str = "medium"  # high / medium / low
    agent: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    followup_queries: list[str] = Field(default_factory=list)


class CritiqueReport(BaseModel):
    """Critic Agent 的结构化审计报告。"""

    is_sufficient: bool = False
    coverage: float = 0.0
    findings: list[CritiqueFinding] = Field(default_factory=list)
    followup_queries: list[str] = Field(default_factory=list)
    audited_claims: int = 0
    unsupported_claims: int = 0
    round: int = 1
    reasoning: str = ""

    def high_severity(self) -> list[CritiqueFinding]:
        return [f for f in self.findings if f.severity == "high"]


class GapType(str, Enum):
    MISSING_SEGMENT = "missing_segment"          # 产业链环节缺失
    WEAK_LOCAL_SUPPLY = "weak_local_supply"      # 本地配套不足
    EXTERNAL_DEPENDENCY = "external_dependency"  # 外部依赖
    LOW_SPECIALIZATION = "low_specialization"    # 区位熵偏低
    POLICY_GAP = "policy_gap"                    # 政策空白
    TALENT_TECH_GAP = "talent_tech_gap"          # 人才/技术缺口


class OpportunityCandidate(BaseModel):
    """产业链缺口对应的招商/培育机会。"""

    opportunity_id: str = ""
    title: str
    gap_type: GapType
    segment: str = ""
    description: str = ""
    rationale: str = ""
    score: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    target_enterprises: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.INFERRED


class OpportunityReport(BaseModel):
    """Star A: Industrial Chain Gap Radar 输出。"""

    county: str = ""
    industry: str = ""
    generated_at: datetime = Field(default_factory=_utcnow)
    opportunities: list[OpportunityCandidate] = Field(default_factory=list)
    missing_segments: list[str] = Field(default_factory=list)
    weak_segments: list[str] = Field(default_factory=list)
    external_dependencies: list[str] = Field(default_factory=list)
    specialization_score: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    degraded: bool = False


class ReportSectionV2(BaseModel):
    """平台报告章节。"""

    title: str
    content: str
    order: int = 0
    agent: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class IntelligenceReport(BaseModel):
    """研究运行的最终交付物。"""

    run_id: str = ""
    county: str
    focus: str = ""
    research_question: str = ""
    executive_summary: str = ""
    sections: list[ReportSectionV2] = Field(default_factory=list)
    opportunities: list[OpportunityCandidate] = Field(default_factory=list)
    evidence_index: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    agent_summaries: dict[str, str] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=_utcnow)
    markdown: str = ""
    report_path: str = ""
    degraded: bool = False
    model_used: str = ""

    @property
    def section_count(self) -> int:
        return len(self.sections)


class ResearchRunRequest(BaseModel):
    """API/服务层的研究请求。"""

    county: str
    focus: str | None = None
    objectives: list[str] = Field(default_factory=list)
    mode: str = "snapshot"
    options: dict[str, Any] = Field(default_factory=dict)


class ResearchRunRecord(BaseModel):
    """研究运行的持久化状态（API 与恢复机制共用）。"""

    run_id: str
    request: ResearchRunRequest
    status: RunStatus = RunStatus.QUEUED
    created_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current_agent: str = ""
    current_node: str = ""
    progress: float = 0.0
    plan: ResearchPlan | None = None
    agent_results: list[AgentResult] = Field(default_factory=list)
    critique: CritiqueReport | None = None
    opportunities: list[OpportunityCandidate] = Field(default_factory=list)
    report_path: str = ""
    error: str = ""
    degraded: bool = False
    evidence_count: int = 0
    graph_entities: int = 0
    graph_relations: int = 0
    checkpoint_thread: str = ""


__all__ = [
    "AgentKind",
    "AgentResult",
    "Claim",
    "CritiqueFinding",
    "CritiqueReport",
    "GapType",
    "IntelligenceReport",
    "OpportunityCandidate",
    "OpportunityReport",
    "ReportSectionV2",
    "ResearchPlan",
    "ResearchRunRecord",
    "ResearchRunRequest",
    "ResearchTask",
    "RunStatus",
    "VerificationStatus",
]
