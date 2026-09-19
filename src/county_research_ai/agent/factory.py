"""默认 Agent 装配：复用现有 ResearchPipeline 依赖。"""
from __future__ import annotations

from pathlib import Path

from ..config import get_settings
from ..pipeline import create_default_pipeline
from .planner import FallbackPlanner, LLMPlanner
from .registry import ToolRegistry
from .runtime import AgentRuntime
from .tools import ResearchToolContext, build_research_tools
from .trace import JsonTraceStore
from .verifier import AgentVerifier


def create_default_agent(
    *,
    max_steps: int = 8,
    save_trace: bool = True,
    trace_root: Path | None = None,
) -> AgentRuntime:
    """创建复用默认 Pipeline 组件的研究 Agent。"""
    settings = get_settings()
    pipeline = create_default_pipeline()
    context = ResearchToolContext.from_pipeline(pipeline, settings=settings)
    registry = ToolRegistry(build_research_tools(context))

    llm_key = settings.llm.api_key.get_secret_value() if settings.llm.api_key else ""
    planner = LLMPlanner(pipeline.llm, settings=settings) if llm_key else FallbackPlanner()
    trace_store = None
    if save_trace:
        trace_store = JsonTraceStore(trace_root or (settings.project_root / "agent_traces"))

    return AgentRuntime(
        planner=planner,
        registry=registry,
        verifier=AgentVerifier(),
        trace_store=trace_store,
        max_steps=max_steps,
    )
