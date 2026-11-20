"""Web Search Provider 测试(Tavily / Serper / Bing + create_provider 工厂)。

用 monkeypatch 替换 httpx.Client,不发起真实网络请求。
覆盖: 工厂函数、结果解析、HTTP 错误包装。
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from county_research_ai.exceptions import SearchError
from county_research_ai.search.web_search import (
    PROVIDER_CLASSES,
    BingSearchProvider,
    DeepSeekSearchProvider,
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

    def test_factory_supports_deepseek_without_enabling_paid_search(self, tmp_settings):
        tmp_settings.search.provider = "deepseek"
        p = create_provider(provider="deepseek", settings=tmp_settings)

        assert type(p) is DeepSeekSearchProvider
        with pytest.raises(SearchError, match="disabled_by_policy"):
            p.search("县域产业")


class TestDeepSeekProvider:
    def test_enabled_search_parses_results_and_tracks_stats(self, monkeypatch, tmp_settings):
        requests = []

        class Response:
            status_code = 200

            def json(self):
                return {
                    "results": [
                        {
                            "title": "官方统计",
                            "url": "https://example.gov.cn/stat",
                            "snippet": "摘要",
                            "content": "正文",
                            "published_date": "2026-01-02",
                            "score": 0.91,
                        }
                    ]
                }

        class Client:
            def __init__(self, *, timeout):
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def post(self, endpoint, *, headers, json):
                requests.append({"endpoint": endpoint, "headers": headers, "json": json})
                return Response()

        monkeypatch.setattr("county_research_ai.search.web_search.httpx.Client", Client)
        p = DeepSeekSearchProvider(api_key="secret", settings=tmp_settings, enabled=True)

        documents = p.search("县域产业", max_results=7)

        assert len(documents) == 1
        assert documents[0].source == "deepseek"
        assert documents[0].metadata["published_date"] == "2026-01-02"
        assert requests[0]["endpoint"] == p.SEARCH_ENDPOINT
        assert requests[0]["json"] == {"query": "县域产业", "count": 7}
        assert p.stats() == {
            "requests": 1,
            "successful_requests": 1,
            "failed_requests": 0,
        }

    def test_fetch_uses_deepseek_fetch_endpoint(self, monkeypatch, tmp_settings):
        class Response:
            status_code = 200

            def json(self):
                return {"url": "https://example.gov.cn/page", "content": "正文"}

        class Client:
            def __init__(self, *, timeout):
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def post(self, endpoint, *, headers, json):
                assert endpoint == DeepSeekSearchProvider.FETCH_ENDPOINT
                assert json == {"url": "https://example.gov.cn/page"}
                return Response()

        monkeypatch.setattr("county_research_ai.search.web_search.httpx.Client", Client)
        p = DeepSeekSearchProvider(api_key="secret", settings=tmp_settings, enabled=True)

        assert p.fetch("https://example.gov.cn/page")["content"] == "正文"

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

    def test_published_date_is_parsed_and_body_year_stays_body_text(
        self, monkeypatch, tmp_settings
    ):
        raw = "2018年安吉县竹产业总产值达到180亿元。" + "统计背景" * 40

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, json=None, **kwargs):
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "title": "安吉县竹产业统计",
                                "url": "https://anji.gov.cn/stat",
                                "snippet": "安吉县竹产业统计",
                                "raw_content": raw,
                                "published_date": "2024-01-08",
                            }
                        ]
                    },
                )

        monkeypatch.setattr(httpx, "Client", Client)
        docs = TavilySearchProvider(api_key="k", settings=tmp_settings).search("q")

        assert docs[0].published_at == datetime(2024, 1, 8, tzinfo=timezone.utc)
        assert docs[0].metadata["published_date"] == "2024-01-08"
        assert "2018年" in docs[0].content

    def test_provider_truncation_records_original_length(self, monkeypatch, tmp_settings):
        raw = "统计正文" * 100

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, json=None, **kwargs):
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "title": "长公报",
                                "url": "https://anji.gov.cn/long",
                                "snippet": "摘要",
                                "raw_content": raw,
                            }
                        ]
                    },
                )

        monkeypatch.setattr(httpx, "Client", Client)
        p = TavilySearchProvider(
            api_key="k", settings=tmp_settings, detail_max_chars=50
        )
        docs = p.search("q")

        assert len(docs[0].content) == 50
        assert docs[0].content_truncated is True
        assert docs[0].content_original_length == len(raw)
        assert docs[0].truncation_reason == "detail_max_chars:50"


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
