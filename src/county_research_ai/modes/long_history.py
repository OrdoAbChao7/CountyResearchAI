from __future__ import annotations

from ..application.context import ResearchContext
from ..models import CountyLongHistoryAnalysis
from ..ports.analysis import LongHistoryAnalyzerPort
from ..ports.reporting import LongHistoryRendererPort
from .base import RenderedReport
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
    ) -> None:
        self.analyzer = analyzer
        self.renderer = renderer

    def analyze(self, context: ResearchContext) -> ResearchContext:
        if context.processed is None:
            raise ValueError("processed evidence is required before analysis")
        focus = context.focus or self.default_focus
        analysis = self.analyzer.analyze(
            county=context.county,
            data=context.processed,
        )
        return context.model_copy(
            update={"focus": focus, "long_history_analysis": analysis}
        )

    def render(self, context: ResearchContext) -> RenderedReport:
        focus = context.focus or self.default_focus
        analysis = context.long_history_analysis or CountyLongHistoryAnalysis(
            county=context.county
        )
        docs = context.processed.docs if context.processed else context.raw_docs
        report = _compatibility_report(context.county, focus, _TITLES)
        return RenderedReport(
            report=report,
            markdown=self.renderer.render(analysis, docs),
        )
