"""PromptLoader 测试(模板加载 + 渲染 + fallback)。

覆盖: has_template 预检、render 变量渲染、render_string fallback、
      get_template 不存在抛 LLMError。
"""
from __future__ import annotations

import pytest

from county_research_ai.exceptions import LLMError
from county_research_ai.llm.prompt_loader import PromptLoader


@pytest.fixture
def loader():
    """使用项目真实的 prompts/ 目录。"""
    from county_research_ai.config import get_settings, reset_settings
    reset_settings()
    return PromptLoader(settings=get_settings())


class TestHasTemplate:
    def test_existing_templates(self, loader):
        assert loader.has_template("industry_analysis") is True
        assert loader.has_template("summary") is True
        assert loader.has_template("recommendations") is True

    def test_nonexistent_template(self, loader):
        assert loader.has_template("nonexistent_xyz") is False

    def test_prompts_dir_matches_settings(self, loader):
        from county_research_ai.config import get_settings
        assert loader.prompts_dir == get_settings().prompts_dir


class TestRender:
    def test_render_substitutes_variables(self, loader):
        rendered = loader.render(
            "industry_analysis",
            county="安吉县",
            focus="竹产业",
            date="2026-08-05",
            processed_data="这里是清洗后的数据...",
        )
        assert "安吉县" in rendered
        assert "竹产业" in rendered
        assert "2026-08-05" in rendered
        assert "这里是清洗后的数据" in rendered

    def test_render_produces_substantial_output(self, loader):
        rendered = loader.render(
            "industry_analysis",
            county="安吉县",
            focus="竹产业",
            date="2026-08-05",
            processed_data="数据",
        )
        assert len(rendered) > 200


class TestRenderString:
    def test_render_string_fallback(self, loader):
        result = loader.render_string(
            "分析 {{ county }} 的 {{ focus }} 产业",
            county="安吉县",
            focus="竹产业",
        )
        assert result == "分析 安吉县 的 竹产业 产业"

    def test_render_string_with_conditional(self, loader):
        result = loader.render_string(
            "{% if focus %}有方向: {{ focus }}{% else %}无方向{% endif %}",
            focus="竹产业",
        )
        assert result == "有方向: 竹产业"


class TestGetTemplateError:
    def test_missing_template_raises_llm_error(self, loader):
        with pytest.raises(LLMError) as exc_info:
            loader.get_template("nonexistent_xyz")
        assert "nonexistent_xyz" in str(exc_info.value)
