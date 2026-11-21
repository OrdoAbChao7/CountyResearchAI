"""Agent 运行事件模型（SSE / 审计轨迹共用）。"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventType:
    RUN_QUEUED = "run_queued"
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_RESUMED = "run_resumed"
    NOTICE = "notice"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    PLAN_CREATED = "plan_created"
    AGENT_STARTED = "agent_started"
    AGENT_TOOL_CALL = "agent_tool_call"
    AGENT_TOOL_RESULT = "agent_tool_result"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    CRITIQUE = "critique"
    SUPPLEMENT = "supplement"
    GRAPH_BUILT = "graph_built"
    OPPORTUNITIES = "opportunities"
    REPORT_READY = "report_ready"
    CHECKPOINT_SAVED = "checkpoint_saved"


class RunEvent(BaseModel):
    seq: int = 0
    run_id: str = ""
    type: str = ""
    agent: str = ""
    node: str = ""
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


EventCallback = Callable[[str, str, str, dict[str, Any]], None]


__all__ = ["EventCallback", "EventType", "RunEvent"]
