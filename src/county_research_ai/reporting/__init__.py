"""报告生成层。

负责将 LLM 分析结果渲染为最终 Markdown 报告:
    - templates/report.md.j2  Markdown 报告模板(Jinja2)
    - renderer.py             ReportRenderer:渲染为 Markdown / HTML / PDF

报告输出到 reports/ 目录,文件名由 settings.app.report_filename_template 决定。
"""
from __future__ import annotations

from .renderer import ReportRenderer

__all__ = ["ReportRenderer"]
