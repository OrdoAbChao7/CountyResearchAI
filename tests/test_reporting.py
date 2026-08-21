"""ReportRenderer 单元测试。

覆盖:Markdown 渲染、文件名渲染、HTML/PDF 预留接口、模板变量替换、空章节处理。
"""
from __future__ import annotations

import pytest

from county_research_ai.exceptions import ConfigError
from county_research_ai.models import (
    AnalysisResult,
    CountyInfo,
    ReportSection,
    ResearchReport,
)
from county_research_ai.reporting import ReportRenderer


@pytest.fixture
def renderer() -> ReportRenderer:
    return ReportRenderer()


@pytest.fixture
def county() -> CountyInfo:
    return CountyInfo(name="安吉县", full_name="浙江省湖州市安吉县")


@pytest.fixture
def sample_report(county) -> ResearchReport:
    """构造一份完整的研究报告。"""
    sections = [
        ReportSection(title="执行摘要", content="本报告针对安吉县竹产业开展研究。", order=1),
        ReportSection(
            title="一、产业现状分析",
            content="2025年产值120亿元。",
            order=2,
            sources=["https://example.gov.cn/tjgb-1"],
        ),
        ReportSection(title="数据来源", content="- [统计公报](https://example.gov.cn/tjgb-1)", order=3),
    ]
    return ResearchReport(
        county=county,
        focus="竹产业",
        sections=sections,
        analyses=[AnalysisResult(task="industry_status", content="...", tokens_used=100)],
    )


# ===== render_markdown 测试 =====


class TestRenderMarkdown:
    def test_returns_string(self, renderer, sample_report):
        md = renderer.render_markdown(sample_report)
        assert isinstance(md, str)
        assert len(md) > 0

    def test_contains_title(self, renderer, sample_report):
        md = renderer.render_markdown(sample_report)
        assert "# 浙江省湖州市安吉县 竹产业产业研究报告" in md

    def test_contains_version_and_date(self, renderer, sample_report):
        md = renderer.render_markdown(sample_report)
        assert "报告版本: 0.1.0" in md
        assert "生成日期:" in md

    def test_contains_all_sections(self, renderer, sample_report):
        md = renderer.render_markdown(sample_report)
        assert "## 执行摘要" in md
        assert "## 一、产业现状分析" in md
        assert "## 数据来源" in md

    def test_contains_section_content(self, renderer, sample_report):
        md = renderer.render_markdown(sample_report)
        assert "本报告针对安吉县竹产业开展研究。" in md
        assert "2025年产值120亿元。" in md

    def test_source_count_annotation(self, renderer, sample_report):
        """非"数据来源"章节应附加来源数注释。"""
        md = renderer.render_markdown(sample_report)
        assert "数据参考来源数: 1" in md

    def test_source_section_no_annotation(self, renderer, sample_report):
        """"数据来源"章节不应附加来源数注释。"""
        md = renderer.render_markdown(sample_report)
        # 数据来源章节本身没有 sources 字段,不应出现"数据参考来源数"
        # 但其他章节有,需确认"数据来源"章节部分没有此注释
        lines = md.split("\n")
        # 找到"## 数据来源"后的内容
        source_section_start = None
        for i, line in enumerate(lines):
            if line.strip() == "## 数据来源":
                source_section_start = i
                break
        assert source_section_start is not None
        # 检查数据来源章节后续 5 行内无"数据参考来源数"
        following_lines = lines[source_section_start:source_section_start + 5]
        assert not any("数据参考来源数" in line for line in following_lines)

    def test_empty_sections(self, renderer, county):
        """空章节列表也能渲染。"""
        report = ResearchReport(county=county, focus="测试", sections=[])
        md = renderer.render_markdown(report)
        assert "# 浙江省湖州市安吉县 测试产业研究报告" in md

    def test_uses_name_when_no_full_name(self, renderer):
        """无 full_name 时使用 name 作为显示名。"""
        county = CountyInfo(name="德清县")
        report = ResearchReport(county=county, focus="通航产业", sections=[])
        md = renderer.render_markdown(report)
        assert "# 德清县 通航产业产业研究报告" in md


# ===== render_filename 测试 =====


class TestRenderFilename:
    def test_basic_rendering(self, renderer):
        result = renderer.render_filename(
            "{{ county }}_{{ focus }}_{{ date }}.md",
            {"county": "安吉县", "focus": "竹产业", "date": "20260806"},
        )
        assert result == "安吉县_竹产业_20260806.md"

    def test_underscore_template(self, renderer):
        result = renderer.render_filename(
            "{{ county }}-{{ focus }}-report.md",
            {"county": "德清县", "focus": "通航产业", "date": "20260806"},
        )
        assert result == "德清县-通航产业-report.md"

    def test_invalid_template_raises(self, renderer):
        """无效 Jinja2 模板应抛 ConfigError。"""
        with pytest.raises(ConfigError):
            renderer.render_filename(
                "{{ county }.md",  # 缺少右花括号
                {"county": "安吉县"},
            )


# ===== 预留接口测试 =====


class TestNotImplemented:
    def test_render_html_not_implemented(self, renderer, sample_report):
        with pytest.raises(NotImplementedError):
            renderer.render_html(sample_report)

    def test_render_pdf_not_implemented(self, renderer, sample_report):
        with pytest.raises(NotImplementedError):
            renderer.render_pdf(sample_report)


# ===== 自定义模板目录测试 =====


class TestCustomTemplateDir:
    def test_custom_template_dir(self, tmp_path):
        """使用自定义模板目录。"""
        # 创建自定义模板
        template_file = tmp_path / "report.md.j2"
        template_file.write_text("# 自定义: {{ county_display }} {{ focus }}", encoding="utf-8")

        renderer = ReportRenderer(template_dir=str(tmp_path))
        county = CountyInfo(name="测试县")
        report = ResearchReport(county=county, focus="测试", sections=[])
        md = renderer.render_markdown(report)
        assert "自定义: 测试县 测试" in md
