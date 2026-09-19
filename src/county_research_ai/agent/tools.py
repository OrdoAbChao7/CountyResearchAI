"""将现有研究能力适配为受控 Agent Tools。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config import Settings, get_settings
from ..llm.analyzer import LLMAnalyzer
from ..llm.long_history_analyzer import LongHistoryAnalyzer
from ..llm.rise_fall_analyzer import RiseFallAnalyzer
from ..models import (
    CountyInfo,
    CountyLongHistoryAnalysis,
    CountyRiseFallAnalysis,
    ReportSection,
    ResearchReport,
)
from ..pipeline import ResearchPipeline
from ..processor import DocumentProcessor
from ..reporting import ReportRenderer
from ..reporting.long_history_renderer import LongHistoryReportRenderer
from ..reporting.rise_fall_renderer import RiseFallReportRenderer
from ..search.base import SearchProvider
from ..search.collector import SearchCollector
from ..storage.base import Storage
from .base import AgentTool, ToolResult, ToolSpec
from .models import AgentState, ToolStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResearchToolContext:
    """一次 Agent 运行共享的研究依赖。"""

    search: SearchProvider
    storage: Storage
    processor: DocumentProcessor
    analyzer: LLMAnalyzer
    rise_fall_analyzer: RiseFallAnalyzer
    long_history_analyzer: LongHistoryAnalyzer
    renderer: ReportRenderer
    rise_fall_renderer: RiseFallReportRenderer
    long_history_renderer: LongHistoryReportRenderer
    settings: Settings

    @classmethod
    def from_pipeline(
        cls, pipeline: ResearchPipeline, settings: Settings | None = None
    ) -> ResearchToolContext:
        effective_settings = settings or get_settings()
        return cls(
            search=pipeline.search,
            storage=pipeline.storage,
            processor=DocumentProcessor(quality_config=effective_settings.quality),
            analyzer=pipeline.analyzer,
            rise_fall_analyzer=pipeline.rise_fall_analyzer,
            long_history_analyzer=pipeline.long_history_analyzer,
            renderer=pipeline.renderer,
            rise_fall_renderer=pipeline.rise_fall_renderer,
            long_history_renderer=pipeline.long_history_renderer,
            settings=effective_settings,
        )


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
        )


class SearchMaterialsTool(_BaseResearchTool):
    name = "search_materials"
    description = "按县名、研究方向和模式收集原始研究资料"

    def spec(self) -> ToolSpec:
        return self._spec({
            "county": {"type": "string"},
            "focus": {"type": "string"},
            "mode": {"type": "string"},
        })

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        county = str(arguments.get("county") or state.request.county)
        focus = str(arguments.get("focus") or state.request.focus or "")
        mode = str(arguments.get("mode") or state.request.mode)
        try:
            docs = self._collect(county=county, focus=focus, mode=mode)
            observation = f"collected {len(docs)} raw documents"
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                observation=observation,
                state_patch={"raw_docs": docs},
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    def _collect(self, *, county: str, focus: str, mode: str):
        if isinstance(self.context.search, SearchCollector):
            return self.context.search.collect(
                county=county,
                focus=focus,
                max_results=self.context.settings.search.max_results,
                mode=mode,
            )

        queries = [
            f"{county} {focus} 产业 发展",
            f"{county} {focus} 产值 企业",
            f"{county} 产业 园区 规划",
        ]
        by_url = {}
        for query in queries:
            for doc in self.context.search.search(
                query, max_results=self.context.settings.search.max_results
            ):
                if doc.url and doc.url not in by_url:
                    by_url[doc.url] = doc
        return list(by_url.values())


class FocusDiscoveryTool(_BaseResearchTool):
    name = "discover_focus"
    description = "从已有搜索资料中发现并选择县域重点产业方向"

    def spec(self) -> ToolSpec:
        return self._spec({})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        try:
            county = CountyInfo.from_name(state.request.county)
            discovery = self.context.analyzer.discover_focus(
                county=county, raw_docs=state.raw_docs,
            )
            focus = discovery.selected_focus or "特色农业"
            request = state.request.model_copy(update={"focus": focus})
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                observation=f"selected focus: {focus}",
                state_patch={"discovery": discovery, "request": request},
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)


class EvidencePackTool(_BaseResearchTool):
    name = "build_evidence_pack"
    description = "清洗、去重、排序并保存研究证据包"

    def spec(self) -> ToolSpec:
        return self._spec({"focus": {"type": "string"}})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        focus = str(arguments.get("focus") or state.request.focus or "特色农业")
        try:
            county = CountyInfo.from_name(state.request.county)
            cache_hours = 0
            if self.context.settings.cache.enabled and not state.request.options.get("no_cache"):
                cache_hours = self.context.settings.cache.ttl_hours
            if cache_hours > 0:
                cached = self.context.storage.load_processed(
                    county.name, focus, max_age_hours=cache_hours,
                )
                if cached is not None:
                    return ToolResult(
                        tool_name=self.name,
                        status=ToolStatus.SUCCESS,
                        observation="evidence pack loaded from cache",
                        state_patch={"processed": cached},
                    )

            processed = self.context.processor.process(
                state.raw_docs, county=county, focus=focus,
            )
            self.context.storage.save_raw(county.name, state.raw_docs)
            self.context.storage.save_processed(county.name, focus, processed)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                observation=f"built evidence pack with {len(processed.docs)} documents",
                state_patch={"processed": processed},
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)


class ResearchAnalysisTool(_BaseResearchTool):
    name = "analyze_research"
    description = "根据研究模式调用对应分析器生成结构化研究结果"

    def spec(self) -> ToolSpec:
        return self._spec({"mode": {"type": "string"}})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        if state.processed is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                observation="processed evidence is missing",
                error="build_evidence_pack must run first",
            )
        mode = str(arguments.get("mode") or state.request.mode)
        county = CountyInfo.from_name(state.request.county)
        focus = state.request.focus or self._default_focus(mode)
        try:
            patch: dict[str, Any] = {}
            if not state.request.focus:
                patch["request"] = state.request.model_copy(update={"focus": focus})
            if mode in {"snapshot", "industry"}:
                patch["snapshot_analyses"] = self.context.analyzer.analyze(
                    county=county, focus=focus, data=state.processed,
                )
            elif mode == "rise-fall":
                patch["rise_fall_analysis"] = self.context.rise_fall_analyzer.analyze(
                    county=county, data=state.processed,
                )
            elif mode == "long-history":
                patch["long_history_analysis"] = self.context.long_history_analyzer.analyze(
                    county=county, data=state.processed,
                )
            else:
                raise ValueError(f"unsupported research mode: {mode}")
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                observation=f"analysis completed for mode {mode}",
                state_patch=patch,
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    @staticmethod
    def _default_focus(mode: str) -> str:
        return {"rise-fall": "兴衰规律", "long-history": "长周期兴衰史"}.get(mode, "特色农业")


class ReportTool(_BaseResearchTool):
    name = "render_report"
    description = "将研究分析结果渲染为带来源的 Markdown 报告并落盘"

    def spec(self) -> ToolSpec:
        return self._spec({"mode": {"type": "string"}})

    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult:
        mode = str(arguments.get("mode") or state.request.mode)
        county = CountyInfo.from_name(state.request.county)
        focus = state.request.focus or ResearchAnalysisTool._default_focus(mode)
        try:
            if mode in {"snapshot", "industry"}:
                report, markdown = self._render_snapshot(state, county, focus)
            elif mode == "rise-fall":
                report, markdown = self._render_rise_fall(state, county, focus)
            elif mode == "long-history":
                report, markdown = self._render_long_history(state, county, focus)
            else:
                raise ValueError(f"unsupported research mode: {mode}")

            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            filename = self.context.renderer.render_filename(
                self.context.settings.app.report_filename_template,
                {"county": county.name, "focus": focus, "date": date_str},
            )
            report_path = self.context.storage.save_report(filename, markdown)
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                observation=f"report written to {report_path}",
                state_patch={"report": report, "report_path": str(report_path)},
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(exc)

    def _render_snapshot(
        self, state: AgentState, county: CountyInfo, focus: str,
    ) -> tuple[ResearchReport, str]:
        analyses = state.snapshot_analyses
        summary = self.context.analyzer.generate_summary(
            county=county, focus=focus, analyses=analyses,
        )
        title_map = {
            "industry_status": "一、产业现状分析",
            "advantages": "二、优势分析",
            "shortcomings": "三、短板分析",
            "recommendations": "四、发展建议",
        }
        sections = [ReportSection(title="执行摘要", content=summary, order=1)]
        for index, analysis in enumerate(analyses, start=2):
            if analysis.task in title_map:
                sections.append(ReportSection(
                    title=title_map[analysis.task],
                    content=analysis.content,
                    order=index,
                    sources=[doc.url for doc in (state.processed.docs if state.processed else [])][:10],
                ))
        source_text = "\n".join(
            f"- [{doc.title}]({doc.url})"
            for doc in (state.processed.docs if state.processed else [])[:20]
            if doc.url
        ) or "_无来源_"
        sections.append(ReportSection(title="数据来源", content=source_text, order=len(sections) + 1))
        report = ResearchReport(county=county, focus=focus, sections=sections, analyses=analyses)
        return report, self.context.renderer.render_markdown(report)

    def _render_rise_fall(
        self, state: AgentState, county: CountyInfo, focus: str,
    ) -> tuple[ResearchReport, str]:
        analysis = state.rise_fall_analysis or CountyRiseFallAnalysis(county=county)
        raw_docs = state.processed.docs if state.processed else state.raw_docs
        markdown = self.context.rise_fall_renderer.render(analysis, raw_docs)
        titles = [
            "执行摘要", "一、县域基本画像", "二、起家产业", "三、兴起逻辑",
            "四、壮大机制", "五、关键拐点", "六、衰落机制", "七、人才流失分析",
            "八、县域兴衰模型归纳", "九、结论",
        ]
        report = _compatibility_report(county, focus, titles)
        return report, markdown

    def _render_long_history(
        self, state: AgentState, county: CountyInfo, focus: str,
    ) -> tuple[ResearchReport, str]:
        analysis = state.long_history_analysis or CountyLongHistoryAnalysis(county=county)
        raw_docs = state.processed.docs if state.processed else state.raw_docs
        markdown = self.context.long_history_renderer.render(analysis, raw_docs)
        titles = [
            "执行摘要", "一、长周期总论", "二、建县与地理逻辑",
            "三、传统时代生存方式", "四、近代冲击与变迁", "五、计划经济时期再组织",
            "六、改革开放后的产业重塑", "七、新世纪以来发展变化",
            "八、长周期兴衰模型", "九、历史规律总结",
        ]
        report = _compatibility_report(county, focus, titles)
        return report, markdown


def _compatibility_report(
    county: CountyInfo, focus: str, titles: list[str],
) -> ResearchReport:
    return ResearchReport(
        county=county,
        focus=focus,
        sections=[
            ReportSection(title=title, content="", order=index)
            for index, title in enumerate(titles, start=1)
        ],
    )


def build_research_tools(context: ResearchToolContext) -> list[AgentTool]:
    return [
        SearchMaterialsTool(context),
        FocusDiscoveryTool(context),
        EvidencePackTool(context),
        ResearchAnalysisTool(context),
        ReportTool(context),
    ]
