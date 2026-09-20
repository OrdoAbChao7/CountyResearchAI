"""默认 Agent 装配：复用现有 ResearchPipeline 依赖。"""
from __future__ import annotations

from pathlib import Path

from ..bootstrap.container import AppContainer, create_app_container
from ..config import get_settings
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
    container = create_app_container(get_settings())
    return _create_agent_from_container(
        container, max_steps=max_steps, save_trace=save_trace, trace_root=trace_root
    )


def _create_agent_from_container(
    container: AppContainer,
    *,
    max_steps: int,
    save_trace: bool,
    trace_root: Path | None,
) -> AgentRuntime:
    settings = container.settings
    context = ResearchToolContext(application=container.application)
    registry = ToolRegistry(build_research_tools(context))

    llm_key = settings.llm.api_key.get_secret_value() if settings.llm.api_key else ""
    planner = LLMPlanner(container.llm, settings=settings) if llm_key else FallbackPlanner()
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
