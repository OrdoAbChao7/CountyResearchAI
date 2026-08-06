"""DocumentProcessor 单元测试。

覆盖:去重(URL/标题相似度/内容 hash)、清洗(HTML/空白/截断)、排序、筛选、证据包构造。
"""
from __future__ import annotations

import pytest

from county_research_ai.config import QualityConfig
from county_research_ai.models import CountyInfo, ProcessedData, RawDoc
from county_research_ai.processor import DocumentProcessor


@pytest.fixture
def processor() -> DocumentProcessor:
    return DocumentProcessor()


@pytest.fixture
def strict_processor() -> DocumentProcessor:
    """严格质量配置:min_credibility=0.8,min_content_length=100。"""
    qc = QualityConfig(
        min_credibility_score=0.8,
        min_content_length=100,
    )
    return DocumentProcessor(quality_config=qc)


@pytest.fixture
def county() -> CountyInfo:
    return CountyInfo(name="安吉县")


def _make_doc(
    title: str = "标题",
    url: str = "https://example.com",
    content: str = "内容",
    snippet: str = "摘要",
    domain_type: str = "unknown",
    credibility_score: float = 0.5,
    source_summary: str = "",
) -> RawDoc:
    return RawDoc(
        title=title,
        url=url,
        content=content,
        snippet=snippet,
        domain_type=domain_type,
        credibility_score=credibility_score,
        source_summary=source_summary,
    )


# ===== 去重测试 =====


class TestDeduplicate:
    def test_url_dedup(self, processor):
        """相同 URL 应被去重。"""
        docs = [
            _make_doc(title="A", url="https://example.com/1"),
            _make_doc(title="B", url="https://example.com/1"),  # 相同 URL
            _make_doc(title="C", url="https://example.com/2"),
        ]
        result = processor.deduplicate(docs)
        assert len(result) == 2

    def test_title_similarity_dedup(self, processor):
        """标题相似度 > 0.85 应被去重。"""
        docs = [
            _make_doc(title="安吉县竹产业产值突破百亿", url="https://a.com/1"),
            _make_doc(title="安吉县竹产业产值突破百亿元大关", url="https://b.com/2"),  # 高相似
            _make_doc(title="完全不同的标题", url="https://c.com/3"),
        ]
        result = processor.deduplicate(docs)
        assert len(result) == 2

    def test_content_hash_dedup(self, processor):
        """相同内容 hash 应被去重。"""
        docs = [
            _make_doc(title="A", url="https://a.com/1", content="相同内容XYZ" * 20),
            _make_doc(title="B", url="https://b.com/2", content="相同内容XYZ" * 20),  # 相同内容
            _make_doc(title="C", url="https://c.com/3", content="不同内容ABC" * 20),
        ]
        result = processor.deduplicate(docs)
        assert len(result) == 2

    def test_empty_docs(self, processor):
        result = processor.deduplicate([])
        assert result == []

    def test_no_duplicates(self, processor):
        docs = [
            _make_doc(title=f"标题{i}", url=f"https://example.com/{i}")
            for i in range(5)
        ]
        result = processor.deduplicate(docs)
        assert len(result) == 5


# ===== 清洗测试 =====


class TestClean:
    def test_html_tags_removed(self, processor):
        doc = _make_doc(content="<p>正文<b>加粗</b></p>")
        result = processor.clean(doc)
        assert "<" not in result.content
        assert "正文" in result.content
        assert "加粗" in result.content

    def test_whitespace_normalized(self, processor):
        doc = _make_doc(content="多个空格   和\t\t制表符")
        result = processor.clean(doc)
        assert "  " not in result.content  # 无连续空格

    def test_truncation(self, processor):
        qc = QualityConfig(max_evidence_length=100)
        p = DocumentProcessor(quality_config=qc)
        doc = _make_doc(content="x" * 200)
        result = p.clean(doc)
        assert len(result.content) <= 100

    def test_domain_type_inferred(self, processor):
        doc = _make_doc(url="https://www.gov.cn/tjgb", domain_type="unknown")
        result = processor.clean(doc)
        assert result.domain_type == "government"

    def test_credibility_inferred(self, processor):
        doc = _make_doc(url="https://www.gov.cn/x", domain_type="unknown", credibility_score=0.5)
        result = processor.clean(doc)
        assert result.credibility_score == 0.9  # government 默认可信度

    def test_source_summary_generated(self, processor):
        doc = _make_doc(snippet="这是一段摘要内容用于测试", source_summary="")
        result = processor.clean(doc)
        assert result.source_summary != ""

    def test_already_clean_doc_unchanged(self, processor):
        doc = _make_doc(content="干净的文本", domain_type="government", credibility_score=0.9)
        result = processor.clean(doc)
        assert result.content == "干净的文本"
        assert result.domain_type == "government"


# ===== 筛选测试 =====


class TestFilterByQuality:
    def test_filters_low_credibility(self, processor):
        docs = [
            _make_doc(title="高可信", url="https://a.com", credibility_score=0.9, content="x" * 100),
            _make_doc(title="低可信", url="https://b.com", credibility_score=0.1, content="x" * 100),
        ]
        result = processor.filter_by_quality(docs)
        assert len(result) == 1
        assert result[0].title == "高可信"

    def test_filters_short_content(self, processor):
        docs = [
            _make_doc(title="长内容", url="https://a.com", content="x" * 200, credibility_score=0.9),
            _make_doc(title="短内容", url="https://b.com", content="ab", credibility_score=0.9),
        ]
        result = processor.filter_by_quality(docs)
        assert len(result) == 1
        assert result[0].title == "长内容"

    def test_empty_docs(self, processor):
        result = processor.filter_by_quality([])
        assert result == []

    def test_all_pass(self, processor):
        docs = [
            _make_doc(title=f"doc{i}", url=f"https://e.com/{i}", content="x" * 200, credibility_score=0.9)
            for i in range(3)
        ]
        result = processor.filter_by_quality(docs)
        assert len(result) == 3


# ===== 排序测试 =====


class TestRankBySource:
    def test_government_ranks_first(self, processor):
        docs = [
            _make_doc(title="企业", url="https://company.com", domain_type="company", credibility_score=0.6, content="x" * 100),
            _make_doc(title="政府", url="https://gov.cn", domain_type="government", credibility_score=0.9, content="x" * 100),
            _make_doc(title="新闻", url="https://news.com", domain_type="news", credibility_score=0.7, content="x" * 100),
        ]
        result = processor.rank_by_source(docs)
        assert result[0].title == "政府"

    def test_same_type_sorted_by_credibility(self, processor):
        docs = [
            _make_doc(title="低", url="https://a.com", domain_type="news", credibility_score=0.5, content="x" * 100),
            _make_doc(title="高", url="https://b.com", domain_type="news", credibility_score=0.9, content="x" * 100),
        ]
        result = processor.rank_by_source(docs)
        assert result[0].title == "高"

    def test_empty_docs(self, processor):
        result = processor.rank_by_source([])
        assert result == []


# ===== 证据包构造测试 =====


class TestBuildEvidencePack:
    def test_returns_processed_data(self, processor, county):
        docs = [
            _make_doc(title="A", url="https://a.com", content="hello", snippet="world"),
            _make_doc(title="B", url="https://b.com", content="foo", snippet="bar"),
        ]
        result = processor.build_evidence_pack(docs, county=county, focus="竹产业")
        assert isinstance(result, ProcessedData)
        assert result.county.name == "安吉县"
        assert result.focus == "竹产业"
        assert len(result.docs) == 2
        assert result.total_chars == len("helloworld") + len("foobar")

    def test_empty_docs(self, processor, county):
        result = processor.build_evidence_pack([], county=county, focus="竹产业")
        assert result.total_chars == 0
        assert result.docs == []


# ===== 完整流程测试 =====


class TestProcess:
    def test_full_pipeline(self, processor, county):
        """完整处理流程:输入 → 去重 → 清洗 → 筛选 → 排序 → 证据包。"""
        docs = [
            _make_doc(title="政府公告", url="https://gov.cn/1", content="x" * 200, domain_type="government", credibility_score=0.9),
            _make_doc(title="新闻报道", url="https://news.com/1", content="y" * 200, domain_type="news", credibility_score=0.7),
            _make_doc(title="重复的政府公告", url="https://gov.cn/1", content="x" * 200),  # 重复 URL
            _make_doc(title="低质量", url="https://spam.com", content="短", credibility_score=0.1),  # 低可信度
        ]
        result = processor.process(docs, county=county, focus="竹产业")
        assert isinstance(result, ProcessedData)
        # 去重+筛选后应剩 2 篇(政府+新闻)
        assert len(result.docs) == 2
        # 排序:政府应排第一
        assert result.docs[0].domain_type == "government"
        assert result.total_chars > 0

    def test_empty_input(self, processor, county):
        result = processor.process([], county=county, focus="竹产业")
        assert result.total_chars == 0
        assert result.docs == []

    def test_all_filtered_out(self, strict_processor, county):
        """所有文档都不满足严格质量门槛。"""
        docs = [
            _make_doc(title="低质量", url="https://a.com", content="短", credibility_score=0.5),
        ]
        result = strict_processor.process(docs, county=county, focus="竹产业")
        assert result.total_chars == 0
        assert result.docs == []

    def test_backward_compat(self, county):
        """不传 QualityConfig 时使用默认配置。"""
        p = DocumentProcessor()
        docs = [
            _make_doc(title="A", url="https://a.com", content="x" * 200),
        ]
        result = p.process(docs, county=county, focus="test")
        assert len(result.docs) == 1
