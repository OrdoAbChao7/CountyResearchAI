from __future__ import annotations

from typing import Any

from ..application.context import ResearchContext
from ..models import ReportSection, ResearchReport
from ..ports.analysis import SnapshotAnalyzerPort
from ..ports.reporting import SnapshotRendererPort
from .base import RenderedReport


class SnapshotModeHandler:
    name = "snapshot"
    default_focus = "特色农业"

    def __init__(
        self,
        analyzer: SnapshotAnalyzerPort,
        renderer: SnapshotRendererPort,
        search: Any = None,
    ) -> None:
        self.analyzer = analyzer
        self.renderer = renderer
        self.search = search

    def analyze(self, context: ResearchContext) -> ResearchContext:
        if context.processed is None:
            raise ValueError("processed evidence is required before analysis")
        focus = context.focus or self.default_focus
        if context.request.options.get("deep_research"):
            from ..research_agent.coordinator import DeepResearchCoordinator

            collector = getattr(self.search, "collector", getattr(self.search, "provider", self.search))
            coordinator = DeepResearchCoordinator(
                search_collector=collector,
                analyzer=self.analyzer,
            )
            docs = context.processed.docs if context.processed else context.raw_docs
            result = coordinator.run_deep_research(
                county=context.county.name,
                focus=focus,
                mode="snapshot",
                existing_docs=docs,
            )
            return context.model_copy(
                update={
                    "focus": focus,
                    "snapshot_analyses": result.analyses,
                    "raw_docs": result.all_raw_docs,
                }
            )
        else:
            analyses = self.analyzer.analyze(
                county=context.county,
                focus=focus,
                data=context.processed,
            )
        return context.model_copy(
            update={"focus": focus, "snapshot_analyses": analyses}
        )

    def render(self, context: ResearchContext) -> RenderedReport:
        focus = context.focus or self.default_focus
        analyses = context.snapshot_analyses
        if context.request.options.get("deep_research"):
            from ..research_agent.specialized import ResearchSynthesizer
            summary = ResearchSynthesizer().generate_executive_summary(
                county=context.county,
                focus=focus,
                analyses=analyses,
            )
        else:
            summary = self.analyzer.generate_summary(
                county=context.county,
                focus=focus,
                analyses=analyses,
            )
        title_map = {
            "industry_status": "一、产业现状分析",
            "advantages": "二、优势分析",
            "shortcomings": "三、短板分析",
            "recommendations": "四、发展建议",
        }
        sections = [ReportSection(title="执行摘要", content=summary, order=1)]
        docs = context.processed.docs if context.processed else context.raw_docs
        for order, analysis in enumerate(analyses, start=2):
            if analysis.task in title_map:
                sections.append(
                    ReportSection(
                        title=title_map[analysis.task],
                        content=analysis.content,
                        order=order,
                        sources=[doc.url for doc in docs[:10]],
                    )
                )
        source_text = "\n".join(
            f"- [{doc.title}]({doc.url})" for doc in docs[:20] if doc.url
        ) or "_无来源_"
        sections.append(
            ReportSection(title="数据来源", content=source_text, order=len(sections) + 1)
        )
        report = ResearchReport(
            county=context.county,
            focus=focus,
            sections=sections,
            analyses=analyses,
        )
        return RenderedReport(
            report=report,
            markdown=self.renderer.render_markdown(report),
        )
