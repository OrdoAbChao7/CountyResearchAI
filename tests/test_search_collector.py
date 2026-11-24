"""SearchCollector 测试(并发采集 + 去重 + 粗排 + 截断)。

用 Mock Provider 注入,不发起真实网络请求。
覆盖: collect 多查询合并、URL 去重、关键词粗排、max_results 截断。
"""
from __future__ import annotations

from concurrent.futures import Future
from threading import Event

import pytest

from county_research_ai.domain.research_contracts import ResearchContract
from county_research_ai.exceptions import SearchError
from county_research_ai.models import RawDoc
from county_research_ai.search.adaptive_retrieval import (
    AdaptiveQueryPlan,
    AdaptiveRetrievalController,
    RetrievalBudget,
)
from county_research_ai.search.base import SearchProvider
from county_research_ai.search.collector import SearchCollector
from county_research_ai.search.gov_data import GovDataProvider
from county_research_ai.search.query_engine import GeneratedQuery, QueryEngine, QueryIntent
from county_research_ai.search.request_history import SearchRequestHistory, bind_search_history


class MockWebProvider(SearchProvider):
    """每个 query 返回不同 URL 的 Mock Web Provider。"""

    name = "mock-web"

    def search(self, query, max_results=10):
        q_key = abs(hash(query)) % 1000
        return [
            RawDoc(title=f"W1-{q_key}", url=f"https://a.com/{q_key}", snippet="安吉县竹产业产值"),
            RawDoc(title=f"W2-{q_key}", url=f"https://b.com/{q_key}", snippet="无关内容"),
        ]


class MockGovProvider(SearchProvider):
    """返回含重复 URL 的 Mock Gov Provider。"""

    name = "mock-gov"

    def search(self, query, max_results=10):
        return [
            RawDoc(title="G1", url="https://a.com/dup", snippet="重复URL"),
            RawDoc(
                title="G2 安吉县竹产业",
                url="https://gov.cn/good",
                snippet="安吉县 竹产业 十四五 规划 安吉县 竹产业",
            ),
        ]


class TestCollect:
    def test_collect_deduplicates_by_url(self, tmp_settings):
        tmp_settings.search.max_results = 10
        col = SearchCollector(
            web_provider=MockWebProvider(),
            gov_provider=MockGovProvider(),
            settings=tmp_settings,
            query_templates=["{county} {focus} 现状", "{county} {focus} 企业"],
            gov_query_templates=["{county} 统计公报"],
        )
        docs = col.collect(county="安吉县", focus="竹产业")
        urls = [d.url for d in docs]
        assert len(urls) == len(set(urls)), "URL 去重未生效"

    def test_collect_truncates_to_max_results(self, tmp_settings):
        tmp_settings.search.max_results = 3
        col = SearchCollector(
            web_provider=MockWebProvider(),
            gov_provider=MockGovProvider(),
            settings=tmp_settings,
            query_templates=["{county} {focus} 现状", "{county} {focus} 企业"],
            gov_query_templates=["{county} 统计公报"],
        )
        docs = col.collect(county="安吉县", focus="竹产业")
        assert len(docs) <= 3

    def test_collect_returns_at_least_some_docs(self, tmp_settings):
        tmp_settings.search.max_results = 10
        col = SearchCollector(
            web_provider=MockWebProvider(),
            gov_provider=MockGovProvider(),
            settings=tmp_settings,
            query_templates=["{county} {focus} 现状"],
            gov_query_templates=["{county} 统计公报"],
        )
        docs = col.collect(county="安吉县", focus="竹产业")
        assert len(docs) >= 1


class TestDedupAndRank:
    """直接测试 _dedup_and_rank 的去重与排序逻辑。"""

    def test_dedup_keeps_longer_content(self):
        docs = [
            RawDoc(title="A", url="https://a.com/1", content="短"),
            RawDoc(title="A2", url="https://a.com/1", content="更长的内容更长的内容"),
        ]
        ranked = SearchCollector._dedup_and_rank(
            SearchCollector, docs, top=10, keywords=["安吉县"],
        )
        assert len(ranked) == 1


        assert ranked[0].content == "更长的内容更长的内容"

    def test_rank_by_keyword_frequency(self):
        """关键词命中次数多的 URL 应排在前面。"""
        docs = [
            RawDoc(title="W1", url="https://a.com/1", snippet="安吉县竹产业产值"),
            RawDoc(title="W2", url="https://b.com/2", snippet="无关"),
            RawDoc(
                title="G2 安吉县竹产业",
                url="https://gov.cn/good",
                snippet="安吉县 竹产业 十四五 规划 安吉县 竹产业",
            ),
        ]
        ranked = SearchCollector._dedup_and_rank(
            SearchCollector, docs, top=10, keywords=["安吉县", "竹产业"],
        )
        # gov.cn/good 命中次数最多,应排第一
        assert ranked[0].url == "https://gov.cn/good"

    def test_truncate_to_top(self):
        docs = [
            RawDoc(title=f"D{i}", url=f"https://x.com/{i}", snippet="安吉县")
            for i in range(10)
        ]
        ranked = SearchCollector._dedup_and_rank(
            SearchCollector, docs, top=3, keywords=["安吉县"],
        )
        assert len(ranked) == 3

    def test_no_url_uses_title_as_key(self):
        """无 URL 的文档用 title 去重。"""
        docs = [
            RawDoc(title="无URL文档", url="", snippet="安吉县"),
            RawDoc(title="无URL文档", url="", snippet="竹产业"),
        ]
        ranked = SearchCollector._dedup_and_rank(
            SearchCollector, docs, top=10, keywords=[],
        )
        assert len(ranked) == 1


def test_collect_adaptive_executes_queries_already_reserved_by_controller(tmp_settings):
    class CountingProvider(SearchProvider):
        name = "counting"

        def __init__(self):
            self.calls = []

        def search(self, query, max_results=10):
            self.calls.append(query)
            return [RawDoc(title="县统计公报", url="https://gov.cn/report", snippet="德清县 GDP")]

    class OneQueryEngine(QueryEngine):
        def generate_research_queries(self, *args, **kwargs):
            return [GeneratedQuery(query="德清县 GDP", intent=QueryIntent.ECONOMIC_SCALE, slot_id="snapshot:economic_scale")]

    provider = CountingProvider()
    controller = AdaptiveRetrievalController(
        OneQueryEngine().generate_research_spec("德清县", "经济", "snapshot"),
        query_engine=OneQueryEngine(),
        budget=RetrievalBudget(max_queries=1),
    )
    plan = controller.initial_plan()
    collector = SearchCollector(web_provider=provider, gov_provider=provider, settings=tmp_settings)

    result = collector.collect_adaptive(plan, controller=controller)

    assert len(plan.queries) == 1
    assert provider.calls == ["德清县 GDP"]
    assert result.usage["search_queries"] == 1


class EmptyProvider(SearchProvider):
    """A provider that successfully returns no result."""

    name = "empty"

    def __init__(self, name: str = "empty") -> None:
        self.name = name
        self.calls: list[str] = []

    def search(self, query, max_results=10):
        self.calls.append(query)
        return []


class FailingProvider(SearchProvider):
    name = "failing"

    def search(self, query, max_results=10):
        raise RuntimeError("provider down")


def _gov_plan():
    spec = QueryEngine().generate_research_spec("安吉县", "竹产业", "snapshot")
    query = GeneratedQuery(
        query="安吉县 2024年 统计公报 国民经济 竹产业",
        intent=QueryIntent.ECONOMIC_SCALE,
        slot_id="snapshot:economic_scale",
        target_channel="gov",
    )
    return AdaptiveQueryPlan(spec, [query], 2), query


def test_empty_gov_followup_is_not_a_search_failure(tmp_settings):
    plan, query = _gov_plan()
    gov = EmptyProvider("empty-gov")
    collector = SearchCollector(
        web_provider=EmptyProvider("empty-web"),
        gov_provider=gov,
        settings=tmp_settings,
    )

    result = collector.collect_adaptive(plan)

    assert gov.calls == [query.query]
    assert result.documents == ()
    assert result.usage["search_queries"] == 1
    assert result.usage["fetched_documents"] == 0


def test_all_provider_errors_still_fail_fast(tmp_settings):
    collector = SearchCollector(
        web_provider=FailingProvider(),
        gov_provider=FailingProvider(),
        settings=tmp_settings,
        query_templates=["{county} {focus} 现状"],
        gov_query_templates=["{county} 统计公报"],
    )

    with pytest.raises(SearchError) as excinfo:
        collector.collect(county="安吉县", focus="竹产业")

    context = excinfo.value.context
    assert context["tasks_count"] == 2
    assert context["failed_tasks"] == 2


def test_mixed_empty_and_error_does_not_fail_fast(tmp_settings):
    collector = SearchCollector(
        web_provider=EmptyProvider("empty-web"),
        gov_provider=FailingProvider(),
        settings=tmp_settings,
        query_templates=["{county} {focus} 现状"],
        gov_query_templates=["{county} 统计公报"],
    )

    assert collector.collect(county="安吉县", focus="竹产业") == []


def test_shared_web_backend_runs_once_for_gov_and_web_routes(tmp_settings):
    class RecordingProvider(EmptyProvider):
        def search(self, query, max_results=10):
            super().search(query, max_results)
            return [
                RawDoc(title="安吉县统计公报", url="https://anji.gov.cn/tjgb/2024"),
                RawDoc(title="安吉县竹业交流", url="https://news.example/bamboo"),
            ]

    provider = RecordingProvider()
    collector = SearchCollector(web_provider=provider, settings=tmp_settings)
    plan, gov_query = _gov_plan()
    web_query = GeneratedQuery(
        query=gov_query.query,
        intent=QueryIntent.ECONOMIC_SCALE,
        slot_id="snapshot:economic_scale",
    )

    gov_only = collector.collect_adaptive(plan)
    assert [doc.url for doc in gov_only.documents] == ["https://anji.gov.cn/tjgb/2024"]
    provider.calls.clear()
    combined = collector.collect_adaptive(AdaptiveQueryPlan(plan.spec, (web_query, gov_query)))

    assert {doc.url for doc in combined.documents} == {
        "https://anji.gov.cn/tjgb/2024", "https://news.example/bamboo",
    }
    assert provider.calls == [gov_query.query]
    assert combined.usage["search_queries"] == 1


def test_gov_detail_timeout_preserves_the_shared_web_response(tmp_settings, monkeypatch):
    official = RawDoc(title="安吉县公报", url="https://anji.gov.cn/tjgb/2024")
    news = RawDoc(title="安吉县竹产业新闻", url="https://news.example/bamboo")

    class RecordingProvider(EmptyProvider):
        def search(self, query, max_results=10):
            super().search(query, max_results)
            return [official, news]

    release_detail = Event()
    detail_started = Event()
    result = Future.result

    def slow_detail(self, doc):
        detail_started.set()
        release_detail.wait(5)
        return doc

    def short_result_wait(self, timeout=None):
        try:
            return result(self, timeout=min(timeout, 0.25) if timeout is not None else None)
        except TimeoutError:
            release_detail.set()
            raise

    monkeypatch.setattr(GovDataProvider, "_enrich_with_detail", slow_detail)
    monkeypatch.setattr(Future, "result", short_result_wait)
    tmp_settings.search.fetch_detail = True
    provider = RecordingProvider()
    collector = SearchCollector(web_provider=provider, settings=tmp_settings)
    plan, gov_query = _gov_plan()
    web_query = GeneratedQuery(gov_query.query, gov_query.intent, slot_id=gov_query.slot_id)

    combined = collector.collect_adaptive(AdaptiveQueryPlan(plan.spec, (gov_query, web_query)))

    assert detail_started.is_set()
    assert release_detail.is_set()
    assert {doc.url for doc in combined.documents} == {official.url, news.url}
    assert provider.calls == [gov_query.query]
    assert combined.usage["search_queries"] == 1


def test_cached_gov_route_applies_its_whitelist_to_web_results(tmp_settings):
    official = RawDoc(title="安吉县公报", url="https://anji.gov.cn/tjgb/2024", source="web")
    lookalike = RawDoc(title="安吉县公报转载", url="https://notgov.cn/tjgb/2024", source="web")
    other_path = RawDoc(title="安吉县部门主页", url="https://anji.gov.cn/home", source="web")

    class RecordingProvider(EmptyProvider):
        def search(self, query, max_results=10):
            super().search(query, max_results)
            return [official, lookalike, other_path]

    provider = RecordingProvider()
    collector = SearchCollector(web_provider=provider, settings=tmp_settings)
    gov_plan, gov_query = _gov_plan()
    web_query = GeneratedQuery(gov_query.query, gov_query.intent, slot_id=gov_query.slot_id)
    with bind_search_history(SearchRequestHistory()):
        web_result = collector.collect_adaptive(AdaptiveQueryPlan(gov_plan.spec, (web_query,)))
        gov_result = collector.collect_adaptive(gov_plan)

    assert {doc.source for doc in web_result.documents} == {"web"}
    assert {doc.url for doc in web_result.documents} == {official.url, lookalike.url, other_path.url}
    assert [(doc.url, doc.source) for doc in gov_result.documents] == [(official.url, "gov")]
    assert provider.calls == [gov_query.query]
    assert gov_result.usage["search_queries"] == 0


def test_same_text_uses_each_distinct_provider(tmp_settings):
    web = EmptyProvider("recording")
    gov = EmptyProvider("recording")
    collector = SearchCollector(web_provider=web, gov_provider=gov, settings=tmp_settings)
    plan, gov_query = _gov_plan()
    web_query = GeneratedQuery(query=gov_query.query, intent=QueryIntent.ECONOMIC_SCALE)

    result = collector.collect_adaptive(AdaptiveQueryPlan(plan.spec, (web_query, gov_query)))

    assert web.calls == gov.calls == [gov_query.query]
    assert result.usage["search_queries"] == 2


def test_search_history_keeps_year_region_and_site_constraints(tmp_settings):
    texts = [
        "安吉县 2024年 site:stats.gov.cn 统计公报",
        "安吉县 2025年 site:stats.gov.cn 统计公报",
        "德清县 2024年 site:stats.gov.cn 统计公报",
        "安吉县 2024年 site:anji.gov.cn 统计公报",
    ]
    provider = EmptyProvider()
    collector = SearchCollector(web_provider=provider, settings=tmp_settings)
    spec = QueryEngine().generate_research_spec("安吉县", "竹产业", "snapshot")
    with bind_search_history(SearchRequestHistory()):
        for text in [*texts, texts[0].replace(" ", "  ")]:
            query = GeneratedQuery(text, QueryIntent.ECONOMIC_SCALE, slot_id="snapshot:economic_scale")
            collector.collect_adaptive(AdaptiveQueryPlan(spec, (query,)))

    assert provider.calls == texts


def test_same_provider_with_different_result_limits_runs_separate_searches(tmp_settings):
    class LimitRecordingProvider(SearchProvider):
        name = "recording-limits"

        def __init__(self):
            self.limits: list[int] = []

        def search(self, query, max_results=10):
            self.limits.append(max_results)
            return []

    provider = LimitRecordingProvider()
    spec = QueryEngine().generate_research_spec("安吉县", "竹产业", "snapshot")
    plan = AdaptiveQueryPlan(spec, (GeneratedQuery("安吉县 竹产业", QueryIntent.ECONOMIC_SCALE),))
    limits = [1, 2]

    with bind_search_history(SearchRequestHistory()):
        for limit in limits:
            tmp_settings.search.max_results = limit
            collector = SearchCollector(web_provider=provider, settings=tmp_settings)
            collector.collect_adaptive(plan)

    assert provider.limits == limits


def test_collect_adaptive_ranks_shared_query_for_every_slot(tmp_settings, monkeypatch):
    class MetricProvider(EmptyProvider):
        def search(self, query, max_results=10):
            super().search(query, max_results)
            return [
                RawDoc(
                    title="安吉县竹业经济统计",
                    url="https://example.com/economy",
                    content="安吉县竹产业地区生产总值、总产值、增加值与增速。",
                ),
                RawDoc(
                    title="安吉县竹业市场",
                    url="https://example.com/market",
                    content="安吉县竹产业的销售情况。",
                ),
            ]

    provider = MetricProvider()
    collector = SearchCollector(web_provider=provider, settings=tmp_settings)
    spec = QueryEngine().generate_research_spec("安吉县", "竹产业", "snapshot")
    queries = (
        GeneratedQuery("安吉县 竹产业", QueryIntent.ECONOMIC_SCALE, slot_id="snapshot:economic_scale"),
        GeneratedQuery("安吉县 竹产业", QueryIntent.MARKET_CHANNELS, slot_id="snapshot:market"),
    )

    monkeypatch.setattr(QueryEngine, "generate_research_queries", lambda *args, **kwargs: list(queries))
    controller = AdaptiveRetrievalController(
        spec, budget=RetrievalBudget(max_queries=1), request_keys=collector.adaptive_request_keys
    )
    plan = controller.initial_plan()

    result = collector.collect_adaptive(plan, controller=controller, max_results=1)

    assert plan.queries == queries
    assert [doc.url for doc in result.documents] == ["https://example.com/economy"]
    assert provider.calls == ["安吉县 竹产业"]
    assert controller.budget.used_queries == 1


def test_contract_query_trace_distinguishes_reuse_empty_and_failure(tmp_settings):
    class TraceProvider(EmptyProvider):
        def search(self, query, max_results=10):
            super().search(query, max_results)
            if query == "安吉县 竹产业 查询失败":
                raise SearchError("synthetic provider failure")
            if query == "安吉县 竹产业 资料":
                return [RawDoc(title="安吉县竹产业年度资料", url="https://example.com/anji", content="安吉县竹产业资料。")]
            return []

    contract = ResearchContract(
        objective="核验竹产业数据", regions=["安吉县"], required_questions=["总产值是多少？", "有哪些龙头企业？"],
    )
    spec = contract.to_research_spec()
    provider = TraceProvider()
    collector = SearchCollector(web_provider=provider, settings=tmp_settings)
    history = SearchRequestHistory()
    shared_query = "安吉县 竹产业 资料"
    first = GeneratedQuery(shared_query, QueryIntent.ECONOMIC_SCALE, slot_id="contract:0")
    second = GeneratedQuery(shared_query, QueryIntent.SUPPLY_CHAIN, slot_id="contract:1")
    empty = GeneratedQuery("安吉县 竹产业 无结果", QueryIntent.ECONOMIC_SCALE, slot_id="contract:0")
    failed = GeneratedQuery("安吉县 竹产业 查询失败", QueryIntent.SUPPLY_CHAIN, slot_id="contract:1")

    with bind_search_history(history):
        collector.collect_adaptive(AdaptiveQueryPlan(spec, (first, second)))
        collector.collect_adaptive(AdaptiveQueryPlan(spec, (empty, failed, first), round_number=2))

    assert sorted(provider.calls) == sorted([shared_query, empty.query, failed.query])
    assert [
        (entry.slot_id, entry.round, entry.request, entry.status, entry.returned_documents)
        for entry in history.executions
    ] == [
        ("contract:0", 1, "executed", "results", 1),
        ("contract:1", 1, "reused", "results", 1),
        ("contract:0", 2, "executed", "empty", 0),
        ("contract:1", 2, "executed", "failed", 0),
        ("contract:0", 2, "skipped", "skipped", 0),
    ]
    assert history.executions[3].reason == "provider_failed"
    assert [item.url for item in history.executions[0].documents] == ["https://example.com/anji"]
    assert history.executions[1].documents[0].url == "https://example.com/anji"
    assert history.executions[2].documents == []
    assert history.executions[3].documents == []


def test_contract_query_trace_records_each_provider_document(tmp_settings):
    class DocumentProvider(EmptyProvider):
        def search(self, query, max_results=10):
            super().search(query, max_results)
            return [
                RawDoc(
                    title="2024年度认定公告附件",
                    url="https://example.gov.cn/notice/2024.pdf",
                    snippet="安吉县竹产业龙头企业认定公告",
                    metadata={"content_type": "application/pdf"},
                ),
                RawDoc(
                    title="安吉县竹产业报道",
                    url="https://example.gov.cn/news/2024",
                    content="安吉县竹产业总产值达到280亿元。",
                    metadata={"content_type": "text/html; charset=utf-8"},
                ),
            ]

    contract = ResearchContract(
        objective="核验竹产业数据", regions=["安吉县"], required_questions=["总产值是多少？"],
    )
    spec = contract.to_research_spec()
    provider = DocumentProvider()
    collector = SearchCollector(web_provider=provider, settings=tmp_settings)
    history = SearchRequestHistory()
    query = GeneratedQuery("安吉县 竹产业 资料", QueryIntent.ECONOMIC_SCALE, slot_id="contract:0")

    with bind_search_history(history):
        collector.collect_adaptive(AdaptiveQueryPlan(spec, (query,)))

    execution, = history.executions
    documents = {item.url: item for item in execution.documents}
    pdf = documents["https://example.gov.cn/notice/2024.pdf"]
    assert (pdf.content_type, pdf.parse_status) == ("application/pdf", "pdf_not_parsed")
    assert pdf.content_chars == 0
    assert pdf.text_origin == "snippet" and len(pdf.text_sha256) == 64
    page = documents["https://example.gov.cn/news/2024"]
    assert (page.content_type, page.parse_status) == ("text/html; charset=utf-8", "text")
    assert page.content_chars == len("安吉县竹产业总产值达到280亿元。")
    assert page.text_origin == "content" and page.text_sha256 != pdf.text_sha256


def test_pdf_url_without_content_type_is_still_not_parsed(tmp_settings):
    class PdfUrlProvider(EmptyProvider):
        def search(self, query, max_results=10):
            super().search(query, max_results)
            return [RawDoc(title="附件", url="https://example.gov.cn/attach/notice.PDF?download=1", snippet="通知")]

    contract = ResearchContract(
        objective="核验资格", regions=["安吉县"], required_questions=["有哪些龙头企业？"],
    )
    spec = contract.to_research_spec()
    collector = SearchCollector(web_provider=PdfUrlProvider(), settings=tmp_settings)
    history = SearchRequestHistory()
    query = GeneratedQuery("安吉县 竹产业 龙头企业", QueryIntent.SUPPLY_CHAIN, slot_id="contract:0")

    with bind_search_history(history):
        collector.collect_adaptive(AdaptiveQueryPlan(spec, (query,)))

    execution, = history.executions
    document, = execution.documents
    assert (document.content_type, document.parse_status) == ("", "pdf_not_parsed")
    assert document.content_chars == 0


def test_pdf_provider_text_is_distinguished_from_unparsed_pdf(tmp_settings):
    class PdfProvider(EmptyProvider):
        def search(self, query, max_results=10):
            super().search(query, max_results)
            return [
                RawDoc(
                    title="附件正文",
                    url="https://example.gov.cn/notice/2024.pdf",
                    content="编委会 主编：韩杰 目录 第一章 总报告",
                    metadata={"content_type": "application/pdf"},
                ),
                RawDoc(
                    title="无正文附件",
                    url="https://example.gov.cn/attach/blank.pdf",
                    metadata={"content_type": "application/pdf"},
                ),
            ]

    contract = ResearchContract(
        objective="核验资格", regions=["安吉县"], required_questions=["有哪些龙头企业？"],
    )
    spec = contract.to_research_spec()
    collector = SearchCollector(web_provider=PdfProvider(), settings=tmp_settings)
    history = SearchRequestHistory()
    query = GeneratedQuery("安吉县 竹产业 龙头企业", QueryIntent.SUPPLY_CHAIN, slot_id="contract:0")

    with bind_search_history(history):
        collector.collect_adaptive(AdaptiveQueryPlan(spec, (query,)))

    execution, = history.executions
    with_text, blank = execution.documents
    assert (with_text.parse_status, with_text.parse_reason) == (
        "pdf_text_from_provider", "pdf_body_not_parsed_by_app")
    assert with_text.content_chars == len("编委会 主编：韩杰 目录 第一章 总报告")
    assert with_text.text_origin == "content" and len(with_text.text_sha256) == 64
    assert (blank.parse_status, blank.parse_reason) == (
        "pdf_not_parsed", "pdf_content_not_supported")
    assert blank.content_chars == 0 and blank.text_origin == "none"
    assert blank.text_sha256 == ""
