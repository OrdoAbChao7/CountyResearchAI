"""报告服务:平台报告与历史兼容报告的渲染、落盘。"""
from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

from ..domain.intelligence import IntelligenceReport
from ..models import AnalysisResult, CountyInfo, ReportSection, ResearchReport
from ..reporting.renderer import ReportRenderer
from ..storage.base import Storage

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "reporting" / "templates"


class ReportService:
    """统一报告渲染与保存入口。"""

    def __init__(
        self,
        storage: Storage,
        *,
        legacy_renderer: ReportRenderer | None = None,
        template_dir: Path | None = None,
    ) -> None:
        self._storage = storage
        self._legacy_renderer = legacy_renderer or ReportRenderer()
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir or _TEMPLATE_DIR)),
            autoescape=select_autoescape(default=False),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    # ---- V2 平台报告 ----

    def render_platform(self, report: IntelligenceReport) -> str:
        template = self._env.get_template("platform_report.md.j2")
        markdown = template.render(
            report=report,
            county=report.county,
            focus=report.focus or "（未指定，由系统发现）",
            generated_at=report.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        )
        report.markdown = markdown
        return markdown

    def save_platform(self, report: IntelligenceReport, *, filename: str = "") -> Path:
        if not report.markdown:
            self.render_platform(report)
        name = filename or f"{report.county}_{report.focus or '产业研究'}_{report.run_id or 'report'}.md"
        path = self._storage.save_report(name, report.markdown)
        report.report_path = str(path)
        return path

    # ---- 历史兼容报告 ----

    def build_legacy_report(
        self,
        county: CountyInfo,
        focus: str,
        analyses: list[AnalysisResult],
        *,
        summary: str = "",
        sources: list[str] | None = None,
    ) -> ResearchReport:
        title_map = {
            "industry_status": "一、产业现状分析",
            "advantages": "二、优势分析",
            "shortcomings": "三、短板分析",
            "recommendations": "四、发展建议",
        }
        sections = [ReportSection(title="执行摘要", content=summary, order=1)]
        for order, analysis in enumerate(analyses, start=2):
            sections.append(
                ReportSection(
                    title=title_map.get(analysis.task, analysis.task),
                    content=analysis.content,
                    order=order,
                )
            )
        source_text = "\n".join(f"- {url}" for url in (sources or [])[:20]) or "_无来源_"
        sections.append(
            ReportSection(title="数据来源", content=source_text, order=len(sections) + 1)
        )
        return ResearchReport(county=county, focus=focus, sections=sections, analyses=analyses)

    def render_legacy(self, report: ResearchReport) -> str:
        return self._legacy_renderer.render_markdown(report)

    def save_legacy(self, report: ResearchReport, *, filename: str = "") -> tuple[str, Path]:
        markdown = self.render_legacy(report)
        name = filename or f"{report.county.name}_{report.focus}.md"
        path = self._storage.save_report(name, markdown)
        return markdown, path

    @staticmethod
    def render_filename(template: str, context: dict[str, str]) -> str:
        return Template(template).render(**context)


__all__ = ["ReportService"]
