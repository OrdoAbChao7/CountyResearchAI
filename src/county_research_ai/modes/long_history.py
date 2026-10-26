from __future__ import annotations

from typing import Any

from ..application.context import ResearchContext
from ..models import CountyLongHistoryAnalysis
from ..ports.analysis import LongHistoryAnalyzerPort
from ..ports.reporting import LongHistoryRendererPort
from .base import RenderedReport, audit_markdown, render_evidence_pack_appendix
from .rise_fall import _compatibility_report

_TITLES = [
    "执行摘要", "一、长周期总论", "二、建县与地理逻辑",
    "三、传统时代生存方式", "四、近代冲击与变迁", "五、计划经济时期再组织",
    "六、改革开放后的产业重塑", "七、新世纪以来发展变化",
    "八、长周期兴衰模型", "九、历史规律总结",
]


class LongHistoryModeHandler:
    name = "long-history"
    default_focus = "长周期兴衰史"

    def __init__(
        self,
        analyzer: LongHistoryAnalyzerPort,
        renderer: LongHistoryRendererPort,
        search: Any = None,
    ) -> None:
        self.analyzer = analyzer
        self.renderer = renderer
        self.search = search

    def analyze(self, context: ResearchContext) -> ResearchContext:
        if context.processed is None:
            raise ValueError("processed evidence is required before analysis")
        focus = context.focus or self.default_focus
        analyzer = self.analyzer
        checkpoint_path = context.request.options.get("analysis_checkpoint_path")
        if checkpoint_path:
            configure_checkpoint = getattr(analyzer, "with_checkpoint", None)
            if not callable(configure_checkpoint):
                raise TypeError("long-history analyzer does not support checkpoints")
            analyzer = configure_checkpoint(checkpoint_path)
        if context.request.options.get("deep_research"):
            from ..research_agent.coordinator import DeepResearchCoordinator

            collector = getattr(self.search, "collector", getattr(self.search, "provider", self.search))
            coordinator = DeepResearchCoordinator(
                search_collector=collector,
                long_history_analyzer=analyzer,
            )
            docs = context.processed.docs if context.processed else context.raw_docs
            result = coordinator.run_deep_research(
                county=context.county.name,
                focus=focus,
                mode="long-history",
                existing_docs=docs,
            )
            research_packs = list(result.evidence_packs or context.evidence_packs)
            period_packs = (
                result.long_history_analysis.evidence_packs
                if result.long_history_analysis is not None
                else []
            )
            seen_pack_ids = {pack.pack_id for pack in research_packs}
            research_packs.extend(
                pack for pack in period_packs if pack.pack_id not in seen_pack_ids
            )
            return context.model_copy(
                update={
                    "focus": focus,
                    "long_history_analysis": result.long_history_analysis,
                    "raw_docs": result.all_raw_docs,
                    "research_spec": result.research_spec or context.research_spec,
                    "evidence_packs": research_packs,
                    "evidence_pack": (research_packs[0] if research_packs else context.evidence_pack),
                }
            )
        else:
            analysis = analyzer.analyze(
                county=context.county,
                data=context.processed,
            )
            return context.model_copy(
                update={
                    "focus": focus,
                    "long_history_analysis": analysis,
                    "evidence_packs": analysis.evidence_packs or context.evidence_packs,
                    "evidence_pack": (
                        analysis.evidence_packs[0]
                        if analysis.evidence_packs
                        else context.evidence_pack
                    ),
                }
            )

    def render(self, context: ResearchContext) -> RenderedReport:
        focus = context.focus or self.default_focus
        analysis = context.long_history_analysis or CountyLongHistoryAnalysis(
            county=context.county
        )
        docs = context.processed.docs if context.processed else context.raw_docs
        report = _compatibility_report(context.county, focus, _TITLES)
        rendered_md = self.renderer.render(analysis, docs)
        rendered_md = audit_markdown(context, rendered_md)
        if context.request.options.get("deep_research"):
            from ..evidence.store import EvidenceStore
            store = EvidenceStore()
            store.ingest_documents(docs, county=context.county.name, focus=focus)
            appendix = (
                f"\n\n---\n### 附录：研究证据链与可信度审计记录\n\n"
                f"{store.render_conflicts_section()}\n\n"
                f"#### 核心参考文献与证据溯源表\n{store.render_citations_table()}\n"
            )
            rendered_md = f"{rendered_md}{appendix}"
        rendered_md = f"{rendered_md}{render_evidence_pack_appendix(context)}"
        return RenderedReport(
            report=report,
            markdown=rendered_md,
        )
