from __future__ import annotations

from ..application.context import ResearchContext
from ..models import CountyRiseFallAnalysis, ReportSection, ResearchReport
from ..ports.analysis import RiseFallAnalyzerPort
from ..ports.reporting import RiseFallRendererPort
from .base import RenderedReport

_TITLES = [
    "执行摘要", "一、县域基本画像", "二、起家产业", "三、兴起逻辑",
    "四、壮大机制", "五、关键拐点", "六、衰落机制", "七、人才流失分析",
    "八、县域兴衰模型归纳", "九、结论",
]


class RiseFallModeHandler:
    name = "rise-fall"
    default_focus = "兴衰规律"

    def __init__(
        self,
        analyzer: RiseFallAnalyzerPort,
        renderer: RiseFallRendererPort,
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
            update={"focus": focus, "rise_fall_analysis": analysis}
        )

    def render(self, context: ResearchContext) -> RenderedReport:
        focus = context.focus or self.default_focus
        analysis = context.rise_fall_analysis or CountyRiseFallAnalysis(
            county=context.county
        )
        docs = context.processed.docs if context.processed else context.raw_docs
        report = _compatibility_report(context.county, focus, _TITLES)
        return RenderedReport(
            report=report,
            markdown=self.renderer.render(analysis, docs),
        )


def _compatibility_report(county, focus: str, titles: list[str]) -> ResearchReport:
    return ResearchReport(
        county=county,
        focus=focus,
        sections=[
            ReportSection(title=title, content="", order=index)
            for index, title in enumerate(titles, start=1)
        ],
    )
