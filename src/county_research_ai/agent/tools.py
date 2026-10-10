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


class PlanResearchTreeTool(_BaseResearchTool):
    name = "plan_research_questions"
    description = "根据县域、研究方向和模式动态生成多层次研究问题树"

    def spec(self) -> ToolSpec:
        return self._spec({"county": {"type": "string"}, "focus": {"type": "string"}, "mode": {"type": "string"}})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        try:
            from ..research_agent.tree import build_question_tree

            county = str(arguments.get("county") or state.request.county)
            focus = str(arguments.get("focus") or state.request.focus or "")
            mode = str(arguments.get("mode") or state.request.mode)
            qtree = build_question_tree(county=county, focus=focus, mode=mode)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                observation=f"generated question tree with {len(qtree.questions)} research questions",
                state_patch={"question_tree": qtree},
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)


class ReflectAndSupplementTool(_BaseResearchTool):
    name = "reflect_and_supplement"
    description = "审视当前证据充分度，发现资料缺口并执行定向补充检索"

    def spec(self) -> ToolSpec:
        return self._spec({"max_turns": {"type": "integer"}})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        try:
            from ..evidence.store import EvidenceStore
            from ..research_agent.critic import ResearchCritic
            from ..research_agent.tree import build_question_tree

            qtree = state.question_tree or build_question_tree(
                county=state.request.county,
                focus=state.request.focus or "",
                mode=state.request.mode,
            )
            store = EvidenceStore()
            store.ingest_documents(
                state.raw_docs, county=state.request.county, focus=state.request.focus or ""
            )

            critic = ResearchCritic()
            current_turn = len(state.reflection_results) + 1
            reflection = critic.reflect(store, qtree, current_turn=current_turn)

            new_docs = list(state.raw_docs)
            if not reflection.is_sufficient and reflection.followup_queries:
                search_port = self.context.application.search
                # 如果底层搜索支持 collect_supplemental
                collector = getattr(search_port, "provider", getattr(search_port, "collector", search_port))
                supp_func = getattr(collector, "collect_supplemental", None)
                if callable(supp_func):
                    supp_results = supp_func(reflection.followup_queries, max_results=6)
                    new_docs.extend(supp_results)
                else:
                    # 退化为单查询调用
                    for q in reflection.followup_queries[:2]:
                        try:
                            res = collector.search(q, max_results=3)
                            new_docs.extend(res)
                        except Exception:  # noqa: BLE001
                            pass

            ref_history = list(state.reflection_results) + [reflection]
            obs = (
                f"reflection turn {current_turn}: sufficient={reflection.is_sufficient}, "
                f"gaps={len(reflection.gaps)}, total_raw_docs={len(new_docs)}"
            )
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                observation=obs,
                state_patch={
                    "question_tree": qtree,
                    "reflection_results": ref_history,
                    "raw_docs": new_docs,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)


class DeepMultiAgentAnalysisTool(_BaseResearchTool):
    name = "deep_multi_agent_analyze"
    description = "调度经济、政策与产业链专业智能体开展综合深度分析与事实核验"

    def spec(self) -> ToolSpec:
        return self._spec({})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        try:
            from ..evidence.store import EvidenceStore
            from ..models import CountyInfo
            from ..research_agent.specialized import (
                EconomicResearchAgent,
                IndustryResearchAgent,
                PolicyResearchAgent,
                ResearchSynthesizer,
            )

            c_info = CountyInfo.from_name(state.request.county)
            f_name = state.request.focus or "特色产业"
            store = EvidenceStore()
            store.ingest_documents(state.raw_docs, county=state.request.county, focus=f_name)

            if state.request.mode in {"snapshot", "industry"}:
                econ = EconomicResearchAgent().analyze(state.request.county, f_name, store)
                pol = PolicyResearchAgent().analyze(state.request.county, f_name, store)
                ind = IndustryResearchAgent().analyze(state.request.county, f_name, store)

                gaps = state.reflection_results[-1].gaps if state.reflection_results else []
                analyses = ResearchSynthesizer().synthesize(
                    county=c_info,
                    focus=f_name,
                    economic_out=econ,
                    policy_out=pol,
                    industry_out=ind,
                    evidence_store=store,
                    gaps=gaps,
                )
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    observation=f"multi-agent analysis completed with {len(analyses)} sections",
                    state_patch={"snapshot_analyses": analyses},
                )
            elif state.request.mode == "rise-fall":
                from ..llm.rise_fall_analyzer import RiseFallAnalyzer
                from ..processor import DocumentProcessor
                proc_data = state.processed or DocumentProcessor().process(state.raw_docs, county=c_info, focus=f_name)
                modes_reg = getattr(self.context.application, "modes", None)
                rf_handler = modes_reg.get("rise-fall") if modes_reg else None
                analyzer = getattr(rf_handler, "analyzer", None) or RiseFallAnalyzer()
                analysis = analyzer.analyze(county=c_info, data=proc_data)
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    observation=f"multi-agent rise-fall analysis completed for {state.request.county}",
                    state_patch={"rise_fall_analysis": analysis},
                )
            else:
                from ..llm.long_history_analyzer import LongHistoryAnalyzer
                from ..processor import DocumentProcessor
                proc_data = state.processed or DocumentProcessor().process(state.raw_docs, county=c_info, focus=f_name)
                modes_reg = getattr(self.context.application, "modes", None)
                lh_handler = modes_reg.get("long-history") if modes_reg else None
                analyzer = getattr(lh_handler, "analyzer", None) or LongHistoryAnalyzer()
                analysis = analyzer.analyze(county=c_info, data=proc_data)
                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    observation=f"multi-agent long-history analysis completed for {state.request.county}",
                    state_patch={"long_history_analysis": analysis},
                )
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)


def build_research_tools(context: ResearchToolContext) -> list[AgentTool]:
    return [
        SearchMaterialsTool(context),
        FocusDiscoveryTool(context),
        EvidencePackTool(context),
        ResearchAnalysisTool(context),
        ReportTool(context),
        PlanResearchTreeTool(context),
        ReflectAndSupplementTool(context),
        DeepMultiAgentAnalysisTool(context),
    ]
