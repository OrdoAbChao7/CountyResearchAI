"""SearchCollector 测试(并发采集 + 去重 + 粗排 + 截断)。

用 Mock Provider 注入,不发起真实网络请求。
覆盖: collect 多查询合并、URL 去重、关键词粗排、max_results 截断。
"""
from __future__ import annotations

import pytest

from county_research_ai.models import RawDoc
from county_research_ai.search.base import SearchProvider
from county_research_ai.search.collector import SearchCollector


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
