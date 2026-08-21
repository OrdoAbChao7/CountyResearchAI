"""数据模型测试(CountyInfo / RawDoc / ProcessedData / ReportSection / ResearchReport / DiscoveryResult)。"""
from __future__ import annotations

from datetime import datetime, timezone

from county_research_ai.models import (
    AnalysisResult,
    CountyInfo,
    DiscoveryCandidate,
    DiscoveryResult,
    ProcessedData,
    RawDoc,
    ReportSection,
    ResearchReport,
    ResearchRequest,
)

# ===== CountyInfo =====


class TestCountyInfo:
    def test_from_name_only_sets_name(self):
        ci = CountyInfo.from_name("安吉县")
        assert ci.name == "安吉县"
        assert ci.province == ""
        assert ci.prefecture == ""
        assert ci.full_name == ""

    def test_display_fallback_to_name(self):
        ci = CountyInfo.from_name("安吉县")
        assert ci.display() == "安吉县"

    def test_display_uses_full_name_when_set(self):
        ci = CountyInfo(name="安吉县", full_name="浙江省湖州市安吉县")
        assert ci.display() == "浙江省湖州市安吉县"


# ===== RawDoc =====


class TestRawDoc:
    def test_required_fields(self):
        doc = RawDoc(title="标题", url="https://example.com")
        assert doc.title == "标题"
        assert doc.url == "https://example.com"
        assert doc.snippet == ""
        assert doc.content == ""
        assert doc.source == ""

    def test_fetched_at_auto_filled(self):
        doc = RawDoc(title="t", url="u")
        assert isinstance(doc.fetched_at, datetime)
        assert doc.fetched_at.tzinfo is not None

    def test_metadata_default_empty(self):
        doc = RawDoc(title="t", url="u")
        assert doc.metadata == {}

    def test_new_quality_fields_defaults(self):
        """新增质量评估字段默认值(向后兼容)。"""
        doc = RawDoc(title="t", url="u")
        assert doc.published_at is None
        assert doc.domain_type == "unknown"
        assert doc.credibility_score == 0.5
        assert doc.evidence_type == "unknown"
        assert doc.source_summary == ""

    def test_new_quality_fields_custom(self):
        """新增质量评估字段可自定义赋值。"""
        now = datetime.now(timezone.utc)
        doc = RawDoc(
            title="t", url="u",
            published_at=now,
            domain_type="government",
            credibility_score=0.95,
            evidence_type="fact",
            source_summary="2025年统计公报",
        )
        assert doc.published_at == now
        assert doc.domain_type == "government"
        assert doc.credibility_score == 0.95
        assert doc.evidence_type == "fact"
        assert doc.source_summary == "2025年统计公报"

    def test_backward_compat_json(self):
        """旧 JSON(不含新字段)反序列化不应报错。"""
        old_json = '{"title": "旧文档", "url": "https://example.com/old", "snippet": "摘要", "content": "正文"}'
        doc = RawDoc.model_validate_json(old_json)
        assert doc.title == "旧文档"
        assert doc.published_at is None  # 默认值
        assert doc.domain_type == "unknown"
        assert doc.credibility_score == 0.5


# ===== ProcessedData =====


class TestProcessedData:
    def test_render_for_llm_no_truncation(self, sample_county, sample_docs):
        pd = ProcessedData(county=sample_county, focus="竹产业", docs=sample_docs, total_chars=100)
        text = pd.render_for_llm(max_chars=0)
        assert "[1]" in text
        assert "[2]" in text
        assert "安吉县竹产业产值突破百亿" in text
        assert "---" in text  # 分隔符

    def test_render_for_llm_truncation(self, sample_county):
        long_doc = RawDoc(title="长文档", url="https://example.com/long", content="x" * 500)
        pd = ProcessedData(county=sample_county, focus="竹产业", docs=[long_doc], total_chars=500)
        text = pd.render_for_llm(max_chars=50)
        assert "(已截断)" in text
        assert "长文档" in text

    def test_render_for_llm_empty_docs(self, sample_county):
        pd = ProcessedData(county=sample_county, focus="竹产业", docs=[], total_chars=0)
        text = pd.render_for_llm()
        assert text == ""

    def test_processed_at_auto_filled(self, sample_county):
        pd = ProcessedData(county=sample_county, focus="竹产业")
        assert isinstance(pd.processed_at, datetime)
        assert pd.processed_at.tzinfo is not None


# ===== AnalysisResult =====


class TestAnalysisResult:
    def test_fields(self):
        r = AnalysisResult(task="industry_status", content="内容", model="m", tokens_used=100)
        assert r.task == "industry_status"
        assert r.content == "内容"
        assert r.model == "m"
        assert r.tokens_used == 100

    def test_defaults(self):
        r = AnalysisResult(task="t", content="c")
        assert r.model == ""
        assert r.tokens_used == 0


# ===== ReportSection =====


class TestReportSection:
    def test_defaults(self):
        s = ReportSection(title="章节", content="内容")
        assert s.order == 0
        assert s.sources == []


# ===== ResearchRequest =====


class TestResearchRequest:
    def test_minimal(self):
        r = ResearchRequest(county="安吉县", focus="竹产业")
        assert r.county == "安吉县"
        assert r.focus == "竹产业"
        assert r.options == {}

    def test_with_options(self):
        r = ResearchRequest(county="安吉县", focus="竹产业", options={"no_cache": True})
        assert r.options["no_cache"] is True


# ===== ResearchReport =====


class TestResearchReport:
    def test_section_count(self, sample_county):
        report = ResearchReport(
            county=sample_county,
            focus="竹产业",
            sections=[
                ReportSection(title="一", content="c1", order=1),
                ReportSection(title="二", content="c2", order=2),
            ],
        )
        assert report.section_count == 2

    def test_get_section_found(self, sample_county):
        report = ResearchReport(
            county=sample_county,
            focus="竹产业",
            sections=[ReportSection(title="执行摘要", content="摘要内容", order=1)],
        )
        s = report.get_section("执行摘要")
        assert s is not None
        assert s.content == "摘要内容"

    def test_get_section_not_found(self, sample_county):
        report = ResearchReport(county=sample_county, focus="竹产业")
        assert report.get_section("不存在") is None

    def test_version_default(self, sample_county):
        report = ResearchReport(county=sample_county, focus="竹产业")
        assert report.version == "0.1.0"


# ===== DiscoveryCandidate / DiscoveryResult =====


class TestDiscoveryCandidate:
    def test_defaults(self):
        c = DiscoveryCandidate(industry="特色农业")
        assert c.industry == "特色农业"
        assert c.confidence == 0.5
        assert c.reason == ""
        # 新增证据链字段默认空
        assert c.evidence_urls == []
        assert c.related_keywords == []
        assert c.supporting_documents == []

    def test_custom_fields(self):
        c = DiscoveryCandidate(industry="竹产业", confidence=0.9, reason="产值120亿")
        assert c.industry == "竹产业"
        assert c.confidence == 0.9
        assert c.reason == "产值120亿"

    def test_evidence_chain_fields(self):
        """证据链字段完整赋值。"""
        c = DiscoveryCandidate(
            industry="特色农业",
            confidence=0.85,
            reason="搜索结果显示该县农业占GDP 30%",
            evidence_urls=[
                "https://example.gov.cn/tjgb-1",
                "https://example.gov.cn/fzgh-2",
            ],
            related_keywords=["年产值", "规上企业", "产业链"],
            supporting_documents=["某县2025年统计公报", "十四五产业发展规划"],
        )
        assert len(c.evidence_urls) == 2
        assert "https://example.gov.cn/tjgb-1" in c.evidence_urls
        assert len(c.related_keywords) == 3
        assert "年产值" in c.related_keywords
        assert len(c.supporting_documents) == 2
        assert "某县2025年统计公报" in c.supporting_documents

    def test_backward_compat_json(self):
        """旧 JSON(不含新证据链字段)反序列化不应报错。"""
        old_json = '{"industry": "A", "confidence": 0.8, "reason": "r"}'
        c = DiscoveryCandidate.model_validate_json(old_json)
        assert c.industry == "A"
        assert c.evidence_urls == []
        assert c.related_keywords == []
        assert c.supporting_documents == []


class TestDiscoveryResult:
    def test_defaults(self):
        r = DiscoveryResult()
        assert r.candidates == []
        assert r.selected_focus == ""
        assert r.model == ""
        assert r.tokens_used == 0
        assert isinstance(r.discovered_at, datetime)

    def test_with_candidates(self):
        c1 = DiscoveryCandidate(industry="A", confidence=0.9)
        c2 = DiscoveryCandidate(industry="B", confidence=0.5)
        r = DiscoveryResult(candidates=[c1, c2], selected_focus="A")
        assert len(r.candidates) == 2
        assert r.selected_focus == "A"

    def test_focus_can_be_none_in_request(self):
        """ResearchRequest.focus 支持 None（自动发现模式）。"""
        r = ResearchRequest(county="安吉县")
        assert r.county == "安吉县"
        assert r.focus is None
