"""报告生成层。

负责将 LLM 分析结果渲染为最终 Markdown 报告:
    - templates.py  报告章节骨架(封面/摘要/现状/优势/风险/建议/来源)
    - renderer.py   将 ReportSection 列表渲染为 Markdown 文档
    - exporter.py   未来导出 PDF/HTML(MVP 阶段仅 Markdown)

报告输出到 reports/ 目录,文件名由 settings.app.report_filename_template 决定。
"""
from __future__ import annotations
