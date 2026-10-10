"""Agent 运行期间使用的结构化状态模型。"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from ..models import (
    AnalysisResult,
    CountyLongHistoryAnalysis,
    CountyRiseFallAnalysis,
    DiscoveryResult,
    ProcessedData,
    QuestionTree,
    RawDoc,
    ReflectionResult,
    ResearchReport,
    ResearchRequest,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


class AgentPlanStep(BaseModel):
    """Planner 每轮选择的一个动作。"""

    tool: str
    reason: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    is_final: bool = False
    planner_source: Literal["llm", "fallback"] = "llm"


class AgentError(BaseModel):
    code: str
    message: str
    tool_name: str = ""
    step_index: int | None = None
    retryable: bool = False


class AgentObservation(BaseModel):
    """一次工具调用的可审计摘要。"""

    step_index: int
    tool_name: str
    status: ToolStatus
    reason: str = ""
    input_summary: str = ""
    output_summary: str = ""
    error: str = ""
    elapsed_ms: int = 0


class AgentState(BaseModel):
    """单次 Agent 运行的可序列化状态。"""

    request: ResearchRequest
    status: AgentStatus = AgentStatus.PENDING
    plan: list[AgentPlanStep] = Field(default_factory=list)
    current_step: int = 0
    steps_used: int = 0
    raw_docs: list[RawDoc] = Field(default_factory=list)
    discovery: DiscoveryResult | None = None
    processed: ProcessedData | None = None
    snapshot_analyses: list[AnalysisResult] = Field(default_factory=list)
    rise_fall_analysis: CountyRiseFallAnalysis | None = None
    long_history_analysis: CountyLongHistoryAnalysis | None = None
    report: ResearchReport | None = None
    report_path: str = ""
    question_tree: QuestionTree | None = None
    reflection_results: list[ReflectionResult] = Field(default_factory=list)
    observations: list[AgentObservation] = Field(default_factory=list)
    errors: list[AgentError] = Field(default_factory=list)

    @classmethod
    def from_request(cls, request: ResearchRequest) -> AgentState:
        return cls(request=request.model_copy(deep=True))

    def apply_patch(self, patch: dict[str, Any]) -> None:
        """应用工具返回的受控状态更新。"""
        allowed = {
            "request",
            "raw_docs",
            "discovery",
            "processed",
            "snapshot_analyses",
            "rise_fall_analysis",
            "long_history_analysis",
            "report",
            "report_path",
            "status",
            "question_tree",
            "reflection_results",
        }
        unknown = set(patch) - allowed
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unknown agent state patch fields: {names}")
        for field, value in patch.items():
            if field == "request" and not isinstance(value, ResearchRequest):
                raise ValueError("agent state request patch must be ResearchRequest")
            setattr(self, field, value)


class AgentTrace(BaseModel):
    """面向回放和排错的 Agent 执行轨迹。"""

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    request: ResearchRequest
    status: AgentStatus = AgentStatus.PENDING
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None
    observations: list[AgentObservation] = Field(default_factory=list)
    errors: list[AgentError] = Field(default_factory=list)
    report_path: str = ""
    failure_code: str = ""


class AgentRunResult(BaseModel):
    """Runtime 返回给 CLI 或调用方的结果。"""

    state: AgentState
    trace: AgentTrace
    report_path: Path | None = None
    trace_path: Path | None = None
