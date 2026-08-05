"""GovDataProvider 测试(白名单匹配 + source 标记)。

用 Mock Web Provider 注入,不发起真实网络请求。
覆盖: gov.cn 域名放行、非 gov 过滤、path_keywords 路径过滤。
"""
from __future__ import annotations

import pytest

from county_research_ai.models import RawDoc
from county_research_ai.search.base import SearchProvider
from county_research_ai.search.gov_data import GovDataProvider


class MockWebProvider(SearchProvider):
    """返回固定 URL 集合的 Mock Web Provider。"""

    name = "mock-web"

    def search(self, query, max_results=10):
        return [
            RawDoc(title="1", url="https://www.stats.gov.cn/some_tjgb_page", snippet="s"),
            RawDoc(title="2", url="https://news.sina.com.cn/xxx", snippet="s"),
            RawDoc(title="3", url="https://zhejiang.gov.cn/fzgh/jihua.html", snippet="s"),
            RawDoc(title="4", url="https://beijing.gov.cn/random_home", snippet="s"),
        ]


class TestGovWhitelist:
    def test_filters_non_gov_domains(self, tmp_settings):
        gp = GovDataProvider(web_provider=MockWebProvider(), settings=tmp_settings, fetch_detail=False)
        docs = gp.search("安吉县 统计公报", max_results=10)
        # sina.com.cn 不是 gov 域名,应被过滤
        urls = {d.url for d in docs}
        assert "https://news.sina.com.cn/xxx" not in urls

    def test_keeps_stats_gov_cn(self, tmp_settings):
        gp = GovDataProvider(web_provider=MockWebProvider(), settings=tmp_settings, fetch_detail=False)
        docs = gp.search("安吉县 统计公报", max_results=10)
        urls = {d.url for d in docs}
        assert "https://www.stats.gov.cn/some_tjgb_page" in urls

    def test_keeps_gov_cn_with_path_keywords(self, tmp_settings):
        gp = GovDataProvider(web_provider=MockWebProvider(), settings=tmp_settings, fetch_detail=False)
        docs = gp.search("安吉县 统计公报", max_results=10)
        urls = {d.url for d in docs}
        # zhejiang.gov.cn/fzgh/jihua.html → path 含 fzgh 和 jihua,应保留
        assert "https://zhejiang.gov.cn/fzgh/jihua.html" in urls

    def test_filters_gov_without_path_keywords(self, tmp_settings):
        gp = GovDataProvider(web_provider=MockWebProvider(), settings=tmp_settings, fetch_detail=False)
        docs = gp.search("安吉县 统计公报", max_results=10)
        urls = {d.url for d in docs}
        # beijing.gov.cn/random_home → path 不含任何关键词,应过滤
        assert "https://beijing.gov.cn/random_home" not in urls

    def test_source_marked_as_gov(self, tmp_settings):
        gp = GovDataProvider(web_provider=MockWebProvider(), settings=tmp_settings, fetch_detail=False)
        docs = gp.search("安吉县 统计公报", max_results=10)
        assert len(docs) == 2  # stats.gov.cn + zhejiang.gov.cn/fzgh
        assert all(d.source == "gov" for d in docs)

    def test_empty_url_filtered(self, tmp_settings):
        class _Empty(SearchProvider):
            name = "empty"
            def search(self, query, max_results=10):
                return [RawDoc(title="t", url="", snippet="s")]
        gp = GovDataProvider(web_provider=_Empty(), settings=tmp_settings, fetch_detail=False)
        docs = gp.search("test")
        assert docs == []
