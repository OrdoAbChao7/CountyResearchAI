"""报告生成层。

负责将 LLM 分析结果渲染为最终 Markdown 报告:
    - templates/report.md.j2          snapshot 模式报告模板(Jinja2)
    - templates/rise_fall_report.md.j2  rise-fall 模式兴衰规律报告模板
    - renderer.py                     ReportRenderer:snapshot 模式渲染器
    - rise_fall_renderer.py           RiseFallReportRenderer:rise-fall 模式渲染器

报告输出到 reports/ 目录,文件名由 settings.app.report_filename_template 决定。
"""
from __future__ import annotations

from .renderer import ReportRenderer
from .rise_fall_renderer import RiseFallReportRenderer

__all__ = ["ReportRenderer", "RiseFallReportRenderer"]
