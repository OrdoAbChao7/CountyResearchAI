"""Web Search Provider 测试(Tavily / Serper / Bing + create_provider 工厂)。

用 monkeypatch 替换 httpx.Client,不发起真实网络请求。
覆盖: 工厂函数、结果解析、HTTP 错误包装。
"""
from __future__ import annotations

import httpx
import pytest

from county_research_ai.exceptions import SearchError
from county_research_ai.search.web_search import (
    PROVIDER_CLASSES,
    BingSearchProvider,
    SerperSearchProvider,
    TavilySearchProvider,
    create_provider,
)

# ===== Mock httpx.Client 工厂 =====


def _make_tavily_mock(monkeypatch, *, status_map: dict | None = None):
    """构造 Tavily 专用的 httpx.Client mock。

    status_map: {query: status_code} 用于模拟错误响应。
    """
    status_map = status_map or {}

    class _MockClient:
        def __init__(self, *a, **kw):
            self.timeout = kw.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def post(self, url, json=None, **kw):
            query = json.get("query", "") if json else ""
            if query in status_map:
                return httpx.Response(status_map[query])
            data = {
                "results": [
                    {"title": "R1", "url": "https://a.com/1", "snippet": "S1"},
                    {"title": "R2", "url": "https://b.com/2", "snippet": "S2"},
                ]
            }
            return httpx.Response(200, json=data)

    monkeypatch.setattr(httpx, "Client", _MockClient)


def _make_serper_mock(monkeypatch):
    class _MockClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def post(self, url, headers=None, json=None, **kw):
            data = {
                "organic": [
                    {"title": "S1", "link": "https://a.com/1", "snippet": "ss1"},
                    {"title": "S2", "link": "https://b.com/2", "snippet": "ss2"},
                ]
            }
            return httpx.Response(200, json=data)

    monkeypatch.setattr(httpx, "Client", _MockClient)


def _make_bing_mock(monkeypatch):
    class _MockClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url, headers=None, params=None, **kw):
            data = {
                "webPages": {
                    "value": [
                        {"name": "B1", "url": "https://a.com/1", "snippet": "bs1"},
                        {"name": "B2", "url": "https://b.com/2", "snippet": "bs2"},
                    ]
                }
            }
            return httpx.Response(200, json=data)

    monkeypatch.setattr(httpx, "Client", _MockClient)


# ===== create_provider 工厂 =====


class TestCreateProvider:
    @pytest.mark.parametrize("name", ["tavily", "serper", "bing"])
    def test_factory_returns_correct_class(self, name, tmp_settings):
        p = create_provider(provider=name, settings=tmp_settings)
        assert type(p) is PROVIDER_CLASSES[name]

    def test_unknown_provider_raises(self, tmp_settings):
        with pytest.raises(SearchError):
            create_provider(provider="unknown", settings=tmp_settings)

    def test_missing_api_key_raises(self, tmp_settings_no_key):
        with pytest.raises(SearchError):
            create_provider(provider="tavily", settings=tmp_settings_no_key)

    def test_factory_reads_provider_from_settings(self, tmp_settings):
        tmp_settings.search.provider = "serper"
        p = create_provider(settings=tmp_settings)
        assert type(p) is SerperSearchProvider


# ===== Tavily =====


class TestTavilyProvider:
    def test_parse_results(self, monkeypatch, tmp_settings):
        _make_tavily_mock(monkeypatch)
        p = TavilySearchProvider(api_key="k", settings=tmp_settings)
        docs = p.search("hello", max_results=5)
        assert len(docs) == 2
        assert docs[0].title == "R1"
        assert docs[0].url == "https://a.com/1"
        assert docs[0].source == "tavily"

    def test_429_raises_search_error(self, monkeypatch, tmp_settings):
        _make_tavily_mock(monkeypatch, status_map={"bad_429": 429})
        p = TavilySearchProvider(api_key="k", settings=tmp_settings)
        with pytest.raises(SearchError):
            p.search("bad_429")

    def test_401_raises_search_error(self, monkeypatch, tmp_settings):
        _make_tavily_mock(monkeypatch, status_map={"bad_401": 401})
        p = TavilySearchProvider(api_key="k", settings=tmp_settings)
        with pytest.raises(SearchError):
            p.search("bad_401")

    def test_empty_api_key_raises(self, tmp_settings_no_key):
        with pytest.raises(SearchError):
            TavilySearchProvider(api_key="", settings=tmp_settings_no_key)


# ===== Serper =====


class TestSerperProvider:
    def test_parse_results(self, monkeypatch, tmp_settings):
        _make_serper_mock(monkeypatch)
        tmp_settings.search.provider = "serper"
        p = SerperSearchProvider(api_key="k", settings=tmp_settings)
        docs = p.search("hello")
        assert len(docs) == 2
        assert docs[0].url == "https://a.com/1"
        assert docs[0].source == "serper"


# ===== Bing =====


class TestBingProvider:
    def test_parse_results(self, monkeypatch, tmp_settings):
        _make_bing_mock(monkeypatch)
        tmp_settings.search.provider = "bing"
        p = BingSearchProvider(api_key="k", settings=tmp_settings)
        docs = p.search("hello")
        assert len(docs) == 2
        assert docs[0].title == "B1"
        assert docs[0].source == "bing"
