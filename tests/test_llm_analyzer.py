"""LLMAnalyzer 测试(analyze 全流程 + generate_summary + task 路由)。

用 MockLLM 注入,不依赖真实 API。
覆盖: 4 个 task 顺序执行、调用次数、task→模板映射、摘要生成。
"""
from __future__ import annotations

import pytest

from county_research_ai.llm.analyzer import LLMAnalyzer
from county_research_ai.llm.prompt_loader import PromptLoader
from county_research_ai.models import AnalysisResult, CountyInfo, ProcessedData, RawDoc


@pytest.fixture
def analyzer(mock_llm):
    """使用 mock_llm + 真实 PromptLoader。"""
    from county_research_ai.config import get_settings, reset_settings
    reset_settings()
    settings = get_settings()
    loader = PromptLoader(settings=settings)
    return LLMAnalyzer(llm=mock_llm, prompt_loader=loader, settings=settings)


@pytest.fixture
def processed_data(sample_county):
    docs = [
        RawDoc(title="doc1", url="u1", content="竹产业产值120亿" * 5),
        RawDoc(title="doc2", url="u2", content="龙头企业XX股份" * 5),
    ]
    return ProcessedData(county=sample_county, focus="竹产业", docs=docs, total_chars=200)


class TestAnalyze:
    def test_returns_4_results(self, analyzer, mock_llm, processed_data, sample_county):
        results = analyzer.analyze(county=sample_county, focus="竹产业", data=processed_data)
        assert len(results) == 4

    def test_all_results_have_content(self, analyzer, mock_llm, processed_data, sample_county):
        results = analyzer.analyze(county=sample_county, focus="竹产业", data=processed_data)
        assert all(r.content for r in results)
        assert all(r.task for r in results)

    def test_llm_called_4_times(self, analyzer, mock_llm, processed_data, sample_county):
        analyzer.analyze(county=sample_county, focus="竹产业", data=processed_data)
        assert mock_llm.call_count == 4

    def test_task_order_matches_settings(self, analyzer, processed_data, sample_county):
        results = analyzer.analyze(county=sample_county, focus="竹产业", data=processed_data)
        from county_research_ai.config import get_settings
        expected = get_settings().llm.tasks
        actual = [r.task for r in results]
        assert actual == expected

    def test_model_and_tokens_recorded(self, analyzer, mock_llm, processed_data, sample_county):
        results = analyzer.analyze(county=sample_county, focus="竹产业", data=processed_data)
        assert all(r.model == "test-mock-v1" for r in results)
        assert all(r.tokens_used == 1300 for r in results)

    def test_industry_status_uses_template(self, analyzer, mock_llm, processed_data, sample_county):
        """industry_status 有模板文件,渲染后 prompt 应含模板特征。"""
        analyzer.analyze(county=sample_county, focus="竹产业", data=processed_data)
        # industry_analysis.md 模板内容应被渲染进 prompt
        assert any(
            "产业概况" in c or "产业链结构" in c or "产值" in c
            for c in mock_llm.calls
        ), f"industry_status 应使用模板, calls={mock_llm.calls[:1]}"

    def test_advantages_uses_fallback(self, analyzer, mock_llm, processed_data, sample_county):
        """advantages 无模板文件,用 fallback prompt(含'核心优势')。"""
        analyzer.analyze(county=sample_county, focus="竹产业", data=processed_data)
        assert any("核心优势" in c for c in mock_llm.calls)


class TestGenerateSummary:
    def test_summary_calls_llm_once(self, analyzer, mock_llm, sample_county):
        analyses = [
            AnalysisResult(task="industry_status", content="产业现状内容...", model="m", tokens_used=100),
            AnalysisResult(task="advantages", content="优势内容...", model="m", tokens_used=100),
        ]
        analyzer.generate_summary(county=sample_county, focus="竹产业", analyses=analyses)
        assert mock_llm.call_count == 1

    def test_summary_not_empty(self, analyzer, mock_llm, sample_county):
        analyses = [
            AnalysisResult(task="industry_status", content="内容", model="m", tokens_used=100),
        ]
        summary = analyzer.generate_summary(county=sample_county, focus="竹产业", analyses=analyses)
        assert len(summary) > 0

    def test_summary_prompt_contains_analysis_content(self, analyzer, mock_llm, sample_county):
        analyses = [
            AnalysisResult(task="industry_status", content="产业现状内容...", model="m", tokens_used=100),
        ]
        analyzer.generate_summary(county=sample_county, focus="竹产业", analyses=analyses)
        assert "产业现状内容" in mock_llm.calls[0]
