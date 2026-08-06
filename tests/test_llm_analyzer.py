"""LLMAnalyzer 测试(analyze 全流程 + generate_summary + discover_focus + task 路由)。

用 MockLLM 注入,不依赖真实 API。
覆盖: 4 个 task 顺序执行、调用次数、task→模板映射、摘要生成、产业方向自动发现。
"""
from __future__ import annotations

import json

import pytest

from county_research_ai.llm.analyzer import LLMAnalyzer
from county_research_ai.llm.prompt_loader import PromptLoader
from county_research_ai.models import (
    AnalysisResult,
    CountyInfo,
    DiscoveryResult,
    ProcessedData,
    RawDoc,
)


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


class TestDiscoverFocus:
    def test_discovery_returns_result(self, analyzer, mock_llm, sample_county, sample_docs):
        result = analyzer.discover_focus(county=sample_county, raw_docs=sample_docs)
        assert isinstance(result, DiscoveryResult)
        assert result.selected_focus == "特色农业"
        assert len(result.candidates) == 3

    def test_discovery_llm_called_once(self, analyzer, mock_llm, sample_county, sample_docs):
        analyzer.discover_focus(county=sample_county, raw_docs=sample_docs)
        assert mock_llm.call_count == 1

    def test_discovery_prompt_contains_county(self, analyzer, mock_llm, sample_county, sample_docs):
        analyzer.discover_focus(county=sample_county, raw_docs=sample_docs)
        assert sample_county.display() in mock_llm.calls[0]

    def test_discovery_candidates_have_fields(self, analyzer, mock_llm, sample_county, sample_docs):
        result = analyzer.discover_focus(county=sample_county, raw_docs=sample_docs)
        for c in result.candidates:
            assert c.industry
            assert isinstance(c.confidence, float)
            assert c.reason

    def test_discovery_candidates_have_evidence_chain(self, analyzer, mock_llm, sample_county, sample_docs):
        """验证候选产业包含完整证据链字段。"""
        result = analyzer.discover_focus(county=sample_county, raw_docs=sample_docs)
        for c in result.candidates:
            assert isinstance(c.evidence_urls, list)
            assert isinstance(c.related_keywords, list)
            assert isinstance(c.supporting_documents, list)
        # 第一个候选(特色农业)应有非空证据链
        top = result.candidates[0]
        assert top.industry == "特色农业"
        assert len(top.evidence_urls) >= 1
        assert len(top.related_keywords) >= 1
        assert len(top.supporting_documents) >= 1

    def test_discovery_evidence_urls_are_valid(self, analyzer, mock_llm, sample_county, sample_docs):
        """证据 URL 应是合法字符串。"""
        result = analyzer.discover_focus(county=sample_county, raw_docs=sample_docs)
        for c in result.candidates:
            for url in c.evidence_urls:
                assert isinstance(url, str)
                assert url.startswith("http")

    def test_discovery_search_results_rendered_with_url(self, analyzer, mock_llm, sample_county, sample_docs):
        """验证 _render_search_results 将 URL 和标题加入 prompt。"""
        analyzer.discover_focus(county=sample_county, raw_docs=sample_docs)
        prompt = mock_llm.calls[0]
        # 应包含 URL
        assert "URL:" in prompt
        # 应包含标题
        assert "标题:" in prompt

    def test_discovery_empty_docs_fallback(self, analyzer, mock_llm, sample_county):
        result = analyzer.discover_focus(county=sample_county, raw_docs=[])
        assert isinstance(result, DiscoveryResult)
        assert result.selected_focus == ""
        # 空文档降级为通用候选
        assert len(result.candidates) >= 2

    def test_discovery_fallback_has_evidence_chain_fields(self, analyzer, sample_county):
        """降级候选也应有证据链字段(可能为空但字段存在)。"""
        result = analyzer._fallback_discovery(sample_county)
        for c in result.candidates:
            assert hasattr(c, "evidence_urls")
            assert hasattr(c, "related_keywords")
            assert hasattr(c, "supporting_documents")
            # 降级候选的证据链字段应为空列表
            assert c.evidence_urls == []
            assert c.supporting_documents == []

    def test_discovery_parse_json_from_text(self, analyzer):
        """验证 _parse_discovery_response 能从含 JSON 的文本中提取。"""
        text = 'Here is the result:\n```json\n{"candidates": [{"industry": "A", "confidence": 0.9, "reason": "r"}], "selected_focus": "A"}\n```'
        result = analyzer._parse_discovery_response(text)
        assert result.selected_focus == "A"
        assert len(result.candidates) == 1

    def test_discovery_parse_with_evidence_chain(self, analyzer):
        """验证 _parse_discovery_response 解析证据链字段。"""
        text = (
            '{"candidates": ['
            '{"industry": "竹产业", "confidence": 0.9, "reason": "产值120亿", '
            '"evidence_urls": ["https://a.com/1", "https://b.com/2"], '
            '"related_keywords": ["产值", "企业"], '
            '"supporting_documents": ["统计公报", "产业规划"]}'
            '], "selected_focus": "竹产业"}'
        )
        result = analyzer._parse_discovery_response(text)
        c = result.candidates[0]
        assert c.industry == "竹产业"
        assert len(c.evidence_urls) == 2
        assert "https://a.com/1" in c.evidence_urls
        assert len(c.related_keywords) == 2
        assert "产值" in c.related_keywords
        assert len(c.supporting_documents) == 2
        assert "统计公报" in c.supporting_documents

    def test_discovery_parse_handles_missing_evidence_fields(self, analyzer):
        """LLM 返回缺失证据链字段时应优雅降级为空列表。"""
        text = '{"candidates": [{"industry": "A", "confidence": 0.5, "reason": "r"}], "selected_focus": "A"}'
        result = analyzer._parse_discovery_response(text)
        c = result.candidates[0]
        assert c.evidence_urls == []
        assert c.related_keywords == []
        assert c.supporting_documents == []

    def test_discovery_parse_handles_null_evidence_fields(self, analyzer):
        """LLM 返回 null 证据链字段时应降级为空列表。"""
        text = (
            '{"candidates": [{"industry": "A", "confidence": 0.5, "reason": "r", '
            '"evidence_urls": null, "related_keywords": null, "supporting_documents": null}], '
            '"selected_focus": "A"}'
        )
        result = analyzer._parse_discovery_response(text)
        c = result.candidates[0]
        assert c.evidence_urls == []
        assert c.related_keywords == []
        assert c.supporting_documents == []

    def test_discovery_parse_invalid_json(self, analyzer):
        """验证无效 JSON 返回空结果。"""
        result = analyzer._parse_discovery_response("not json at all")
        assert result.selected_focus == ""
        assert len(result.candidates) == 0

    def test_discovery_fallback_generates_default(self, analyzer, sample_county):
        result = analyzer._fallback_discovery(sample_county)
        assert result.selected_focus == ""
        assert len(result.candidates) >= 2
