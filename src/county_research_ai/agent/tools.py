"""将共享研究应用适配为受控 Agent Tools。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..application.config import ResearchApplicationConfig
from ..application.context import ResearchContext
from ..application.research import ResearchApplication
from ..config import Settings, get_settings
from ..domain.modes import normalize_mode
from ..modes.long_history import LongHistoryModeHandler
from ..modes.registry import ModeRegistry
from ..modes.rise_fall import RiseFallModeHandler
from ..modes.snapshot import SnapshotModeHandler
from ..pipeline import ResearchPipeline
from ..processor import DocumentProcessor
from ..search.base import SearchProvider
from .base import AgentTool, ToolResult, ToolSpec
from .models import AgentState, ToolStatus

logger = logging.getLogger(__name__)


class _LegacySearchAdapter:
    def __init__(self, provider: SearchProvider) -> None:
        self.provider = provider

    def collect(self, county: str, focus: str, max_results: int, *, mode: str):
        collect = getattr(self.provider, "collect", None)
        if callable(collect):
            return collect(county, focus, max_results, mode=mode)
        return self.provider.search(f"{county} {focus or '产业'}", max_results=max_results)


@dataclass(frozen=True, init=False)
class ResearchToolContext:
    """Agent 运行只依赖共享 ResearchApplication。"""

    application: ResearchApplication
    _legacy_analyzer: Any = None

    def __init__(self, application: ResearchApplication | None = None, **legacy: Any) -> None:
        if application is None:
            application = _build_legacy_application(legacy)
        object.__setattr__(self, "application", application)
        object.__setattr__(self, "_legacy_analyzer", legacy.get("analyzer"))

    @property
    def analyzer(self) -> Any:
        """Compatibility accessor for integrations that inspect the old context."""
        return self._legacy_analyzer

    @classmethod
    def from_pipeline(
        cls, pipeline: ResearchPipeline, settings: Settings | None = None
    ) -> ResearchToolContext:
        return cls(application=pipeline.application)


def _build_legacy_application(legacy: dict[str, Any]) -> ResearchApplication:
    settings = legacy.get("settings") or get_settings()
    analyzer = legacy["analyzer"]
    renderer = legacy["renderer"]
    return ResearchApplication(
        search=_LegacySearchAdapter(legacy["search"]),
        storage=legacy["storage"],
        processor=legacy.get("processor") or DocumentProcessor(quality_config=settings.quality),
        discovery=analyzer,
        modes=ModeRegistry([
            SnapshotModeHandler(analyzer, renderer),
            RiseFallModeHandler(legacy["rise_fall_analyzer"], legacy["rise_fall_renderer"]),
            LongHistoryModeHandler(legacy["long_history_analyzer"], legacy["long_history_renderer"]),
        ]),
        config=ResearchApplicationConfig(
            max_search_results=settings.search.max_results,
            cache_enabled=settings.cache.enabled,
            cache_ttl_hours=settings.cache.ttl_hours,
            report_filename_template=settings.app.report_filename_template,
        ),
        render_filename=renderer.render_filename,
    )


def _context_for_state(state: AgentState, *, focus: str | None = None) -> ResearchContext:
    request = state.request
    if focus and not request.focus:
        request = request.model_copy(update={"focus": focus})
    context = ResearchContext.from_request(request)
    return context.model_copy(update={
        "raw_docs": state.raw_docs,
        "discovery": state.discovery,
        "processed": state.processed,
        "snapshot_analyses": state.snapshot_analyses,
        "rise_fall_analysis": state.rise_fall_analysis,
        "long_history_analysis": state.long_history_analysis,
    })


def _state_patch(context: ResearchContext) -> dict[str, Any]:
    patch: dict[str, Any] = {
        "request": context.request,
        "raw_docs": context.raw_docs,
        "discovery": context.discovery,
        "processed": context.processed,
        "snapshot_analyses": context.snapshot_analyses,
        "rise_fall_analysis": context.rise_fall_analysis,
        "long_history_analysis": context.long_history_analysis,
    }
    return {key: value for key, value in patch.items() if value is not None}


class _BaseResearchTool:
    def __init__(self, context: ResearchToolContext) -> None:
        self.context = context

    def _spec(self, arguments: dict[str, Any]) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, arguments=arguments)

    def _error(self, exc: Exception) -> ToolResult:
        logger.warning("Agent tool failed | tool=%s | err=%s", self.name, exc)
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.ERROR,
            observation=f"{self.name} failed",
            error=str(exc),
            error_code=getattr(exc, "code", "tool_error"),
            retryable=bool(getattr(exc, "retryable", False)),
        )


class SearchMaterialsTool(_BaseResearchTool):
    name = "search_materials"
    description = "按县名、研究方向和模式收集原始研究资料"

    def spec(self) -> ToolSpec:
        return self._spec({"county": {"type": "string"}, "focus": {"type": "string"}, "mode": {"type": "string"}})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        try:
            context = _context_for_state(state, focus=str(arguments.get("focus") or ""))
            context = self.context.application.collect_materials(context)
            return ToolResult(tool_name=self.name, status=ToolStatus.SUCCESS,
                              observation=f"collected {len(context.raw_docs)} raw documents",
                              state_patch=_state_patch(context))
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)


class FocusDiscoveryTool(_BaseResearchTool):
    name = "discover_focus"
    description = "从已有搜索资料中发现并选择县域重点产业方向"

    def spec(self) -> ToolSpec:
        return self._spec({})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        try:
            context = self.context.application.discover_focus(_context_for_state(state))
            return ToolResult(tool_name=self.name, status=ToolStatus.SUCCESS,
                              observation=f"selected focus: {context.focus}",
                              state_patch=_state_patch(context))
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)


class EvidencePackTool(_BaseResearchTool):
    name = "build_evidence_pack"
    description = "清洗、去重、排序并保存研究证据包"

    def spec(self) -> ToolSpec:
        return self._spec({"focus": {"type": "string"}})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        try:
            context = _context_for_state(state, focus=str(arguments.get("focus") or ""))
            context = self.context.application.build_evidence(context)
            count = len(context.processed.docs) if context.processed else 0
            return ToolResult(tool_name=self.name, status=ToolStatus.SUCCESS,
                              observation=f"built evidence pack with {count} documents",
                              state_patch=_state_patch(context))
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)


class ResearchAnalysisTool(_BaseResearchTool):
    name = "analyze_research"
    description = "根据研究模式调用对应分析器生成结构化研究结果"

    def spec(self) -> ToolSpec:
        return self._spec({"mode": {"type": "string", "enum": ["snapshot", "industry", "rise-fall", "long-history"]}})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        try:
            context = self.context.application.analyze(_context_for_state(state))
            mode = normalize_mode(state.request.mode)
            return ToolResult(tool_name=self.name, status=ToolStatus.SUCCESS,
                              observation=f"analysis completed for mode {mode}",
                              state_patch=_state_patch(context))
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)


class ReportTool(_BaseResearchTool):
    name = "render_report"
    description = "将研究分析结果渲染为带来源的 Markdown 报告并落盘"

    def spec(self) -> ToolSpec:
        return self._spec({"mode": {"type": "string", "enum": ["snapshot", "industry", "rise-fall", "long-history"]}})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        try:
            result = self.context.application.render_report(_context_for_state(state))
            return ToolResult(tool_name=self.name, status=ToolStatus.SUCCESS,
                              observation=f"report written to {result.report_path}",
                              state_patch={"report": result.report, "report_path": str(result.report_path)})
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)


def build_research_tools(context: ResearchToolContext) -> list[AgentTool]:
    return [SearchMaterialsTool(context), FocusDiscoveryTool(context), EvidencePackTool(context),
            ResearchAnalysisTool(context), ReportTool(context)]
