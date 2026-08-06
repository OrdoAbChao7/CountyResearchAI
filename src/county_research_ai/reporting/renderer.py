"""报告渲染层。

将 ResearchReport 渲染为最终输出格式(Markdown / HTML / PDF)。
当前实现 Markdown,HTML/PDF 为预留接口。

设计原则:
- ReportRenderer 只负责格式化输出,不调用 Storage
- Pipeline 负责在 renderer 返回字符串后落盘
- 模板使用 Jinja2,便于扩展多格式
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

from ..config import PROJECT_ROOT
from ..exceptions import ConfigError
from ..models import ReportSection, ResearchReport

logger = logging.getLogger(__name__)

# 模板目录:src/county_research_ai/reporting/templates/
_DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


class ReportRenderer:
    """报告渲染器。

    Usage:
        renderer = ReportRenderer()
        md = renderer.render_markdown(report)
        filename = renderer.render_filename("{{ county }}_{{ focus }}_{{ date }}.md", {...})
    """

    def __init__(self, template_dir: str | Path | None = None) -> None:
        """初始化渲染器。

        Args:
            template_dir: 模板目录路径;None 则使用默认 reporting/templates/
        """
        self._template_dir = Path(template_dir) if template_dir else _DEFAULT_TEMPLATE_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=select_autoescape(default=False),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        logger.debug("ReportRenderer 初始化 | template_dir=%s", self._template_dir)

    def render_markdown(self, report: ResearchReport) -> str:
        """渲染为 Markdown 字符串。

        Args:
            report: 完整研究报告对象

        Returns:
            Markdown 格式的字符串
        """
        template = self._env.get_template("report.md.j2")
        try:
            md = template.render(
                county_display=report.county.display(),
                focus=report.focus,
                generated_at=report.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
                version=report.version,
                sections=[s.model_dump() for s in report.sections],
            )
        except Exception as e:
            logger.error("Markdown 渲染失败 | err=%s", e, exc_info=True)
            raise ConfigError(
                "Markdown 报告渲染失败",
                context={"error": str(e)},
            ) from e
        return md

    def render_html(self, report: ResearchReport) -> str:
        """渲染为 HTML(预留接口,当前未实现)。

        未来扩展时实现:Markdown → HTML 或直接 HTML 模板。
        """
        raise NotImplementedError("HTML 渲染尚未实现,当前仅支持 Markdown")

    def render_pdf(self, report: ResearchReport) -> bytes:
        """渲染为 PDF(预留接口,当前未实现)。

        未来扩展时实现:Markdown → PDF(通过 weasyprint/pandoc)。
        """
        raise NotImplementedError("PDF 渲染尚未实现,当前仅支持 Markdown")

    def render_filename(self, template: str, context: dict[str, str]) -> str:
        """用 Jinja2 渲染报告文件名。

        Args:
            template: 文件名模板,如 "{{ county }}_{{ focus }}_{{ date }}.md"
            context: 模板变量,如 {"county": "安吉县", "focus": "竹产业", "date": "20260806"}

        Returns:
            渲染后的文件名字符串

        Raises:
            ConfigError: 模板渲染失败
        """
        try:
            return Template(template).render(**context)
        except Exception as e:
            raise ConfigError(
                "报告文件名模板渲染失败",
                context={"template": template, "context": context, "error": str(e)},
            ) from e
