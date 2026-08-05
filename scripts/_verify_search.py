"""Search 层验证:web_search(provider)、gov_data、collector 全部走 httpx mock。

覆盖:
    1. create_provider 工厂(名称识别+缺key抛错)
    2. TavilySearchProvider 解析 + 429/401 错误包装
    3. SerperSearchProvider 解析
    4. BingSearchProvider 解析
    5. GovDataProvider 白名单匹配(*.gov.cn 通配)
    6. SearchCollector.collect 并发 + 去重 + 粗排
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import httpx

from county_research_ai.config import Settings
from county_research_ai.exceptions import SearchError
from county_research_ai.models import RawDoc
from county_research_ai.search.base import SearchProvider
from county_research_ai.search.collector import SearchCollector
from county_research_ai.search.gov_data import GovDataProvider, GovDomain
from county_research_ai.search.web_search import (
    BingSearchProvider,
    SerperSearchProvider,
    TavilySearchProvider,
    create_provider,
)
from county_research_ai.search.web_search import PROVIDER_CLASSES


def make_settings(api_key: str = "test-key", provider: str = "tavily") -> Settings:
    from pydantic import SecretStr
    from county_research_ai.config import (
        SearchConfig, SearchRetryConfig, PipelineConfig, LLMConfig, AppConfig,
        StorageConfig, CacheConfig, LoggingConfig, PipelineStages,
    )
    return Settings(
        app=AppConfig(),
        llm=LLMConfig(),
        search=SearchConfig(
            provider=provider,
            api_key=SecretStr(api_key),
            max_results=5,
            timeout=5,
            concurrency=2,
            retry=SearchRetryConfig(max_attempts=1, backoff_seconds=0),
            fetch_detail=False,
        ),
        storage=StorageConfig(),
        cache=CacheConfig(enabled=False),
        pipeline=PipelineConfig(fail_fast=True, stages=PipelineStages()),
        logging=LoggingConfig(level="WARNING"),
    )


# ---- 1. create_provider 工厂 ----
def test_provider_factory():
    failures: list[str] = []
    # 识别三个名称
    for name, cls in PROVIDER_CLASSES.items():
        s = make_settings(provider=name)
        try:
            p = create_provider(provider=name, settings=s)
            assert type(p) is cls, f"{name} 应返回 {cls.__name__}, 实际 {type(p).__name__}"
            print(f"[OK] 1a. create_provider({name}) -> {type(p).__name__}")
        except Exception as e:
            failures.append(f"factory {name}: {e}")
            print(f"[FAIL] 1a. {name}: {e}")

    # 未知名称
    try:
        create_provider(provider="unknown", settings=make_settings())
        failures.append("factory 未知名称应抛 SearchError")
        print(f"[FAIL] 1b. 未知名称应抛 SearchError")
    except SearchError as e:
        print(f"[OK] 1b. 未知名称抛 SearchError | msg={e.message}")
    except Exception as e:
        failures.append(f"factory 未知名称: {type(e).__name__}: {e}")

    # 缺 key
    try:
        s = make_settings(api_key="")
        create_provider(provider="tavily", settings=s)
        failures.append("缺 key 应抛 SearchError")
        print(f"[FAIL] 1c. 缺 key 应抛 SearchError")
    except SearchError:
        print(f"[OK] 1c. 缺 key 抛 SearchError")
    except Exception as e:
        failures.append(f"1c.: {type(e).__name__}: {e}")
    return failures


# ---- 2. Tavily 解析 + 错误 ----
def test_tavily():
    failures: list[str] = []

    # Mock 成功响应
    def handler(request: httpx.Request) -> httpx.Response:
        if "results" in str(request.url):
            return httpx.Response(500)
        data = {
            "results": [
                {"title": "R1", "url": "https://a.com/1", "snippet": "S1", "score": 0.9},
                {"title": "R2", "url": "https://b.com/2", "snippet": "S2", "score": 0.8},
                {"title": "R3 安吉县", "url": "https://c.com/3", "snippet": "安吉县竹产业产值百亿", "score": 0.7},
            ]
        }
        return httpx.Response(200, json=data)

    s = make_settings()
    # 注入 mock httpx client(通过 monkeypatch)
    orig = httpx.Client
    class _MockClient:
        def __init__(self, *a, **kw): self.timeout = kw.get("timeout")
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, json=None, **kw):
            if json.get("query") == "bad_429": return httpx.Response(429)
            if json.get("query") == "bad_401": return httpx.Response(401)
            data = {"results": [
                {"title": "R1", "url": "https://a.com/1", "snippet": "S1"},
                {"title": "R2", "url": "https://b.com/2", "snippet": "S2"},
            ]}
            return httpx.Response(200, json=data)
    httpx.Client = _MockClient  # type: ignore[assignment]

    try:
        p = TavilySearchProvider(api_key="k", settings=s)
        docs = p.search("hello", max_results=5)
        assert len(docs) == 2, f"应返回 2 条, 实际 {len(docs)}"
        assert docs[0].title == "R1", f"title 错误: {docs[0].title}"
        assert docs[0].source == "tavily", f"source 错误: {docs[0].source}"
        print(f"[OK] 2a. Tavily 解析 | docs={len(docs)} title={docs[0].title}")

        # 429
        try:
            p.search("bad_429")
            failures.append("429 应抛 SearchError")
            print(f"[FAIL] 2b. 429 应抛 SearchError")
        except SearchError:
            print(f"[OK] 2b. 429 抛 SearchError")

        # 401
        try:
            p.search("bad_401")
            failures.append("401 应抛 SearchError")
            print(f"[FAIL] 2c. 401 应抛 SearchError")
        except SearchError:
            print(f"[OK] 2c. 401 抛 SearchError")
    finally:
        httpx.Client = orig  # type: ignore[assignment]

    return failures


# ---- 3. Serper 解析 ----
def test_serper():
    failures: list[str] = []
    orig = httpx.Client
    class _MockClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, headers=None, json=None, **kw):
            data = {"organic": [
                {"title": "S1", "link": "https://a.com/1", "snippet": "ss1"},
                {"title": "S2", "link": "https://b.com/2", "snippet": "ss2"},
            ]}
            return httpx.Response(200, json=data)
    httpx.Client = _MockClient  # type: ignore[assignment]
    try:
        s = make_settings(provider="serper")
        p = SerperSearchProvider(api_key="k", settings=s)
        docs = p.search("hello")
        assert len(docs) == 2, f"应返回 2 条, 实际 {len(docs)}"
        assert docs[0].url == "https://a.com/1", f"url 错误: {docs[0].url}"
        assert docs[0].source == "serper", f"source 错误: {docs[0].source}"
        print(f"[OK] 3. Serper 解析 | docs={len(docs)}")
    except Exception as e:
        failures.append(f"serper: {type(e).__name__}: {e}")
        print(f"[FAIL] 3. {type(e).__name__}: {e}")
    finally:
        httpx.Client = orig  # type: ignore[assignment]
    return failures


# ---- 4. Bing 解析 ----
def test_bing():
    failures: list[str] = []
    orig = httpx.Client
    class _MockClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, url, headers=None, params=None, **kw):
            data = {"webPages": {"value": [
                {"name": "B1", "url": "https://a.com/1", "snippet": "bs1"},
                {"name": "B2", "url": "https://b.com/2", "snippet": "bs2"},
            ]}}
            return httpx.Response(200, json=data)
    httpx.Client = _MockClient  # type: ignore[assignment]
    try:
        s = make_settings(provider="bing")
        p = BingSearchProvider(api_key="k", settings=s)
        docs = p.search("hello")
        assert len(docs) == 2, f"应返回 2 条, 实际 {len(docs)}"
        assert docs[0].title == "B1", f"title 错误: {docs[0].title}"
        assert docs[0].source == "bing", f"source 错误: {docs[0].source}"
        print(f"[OK] 4. Bing 解析 | docs={len(docs)}")
    except Exception as e:
        failures.append(f"bing: {type(e).__name__}: {e}")
        print(f"[FAIL] 4. {type(e).__name__}: {e}")
    finally:
        httpx.Client = orig  # type: ignore[assignment]
    return failures


# ---- 5. GovDataProvider 白名单匹配 ----
def test_gov_whitelist():
    failures: list[str] = []
    # 先用 Mock Web Provider,内部再测 match_whitelist
    class _WP(SearchProvider):
        name = "mock-web"
        def search(self, query, max_results=10):
            # 构造一堆 url:有 gov 有非 gov
            return [
                RawDoc(title="1", url="https://www.stats.gov.cn/some_tjgb_page", snippet="s"),
                RawDoc(title="2", url="https://news.sina.com.cn/xxx", snippet="s"),
                RawDoc(title="3", url="https://zhejiang.gov.cn/fzgh/jihua.html", snippet="s"),
                RawDoc(title="4", url="https://beijing.gov.cn/random_home", snippet="s"),  # 没 path 关键词
            ]

    s = make_settings()
    # 不抓详情页
    gp = GovDataProvider(web_provider=_WP(), settings=s, fetch_detail=False)
    docs = gp.search("安吉县 统计公报", max_results=10)
    assert len(docs) == 2, f"白名单应过滤为 2 条, 实际 {len(docs)}"
    urls = {d.url for d in docs}
    assert "https://www.stats.gov.cn/some_tjgb_page" in urls, "stats 应在"
    assert "https://zhejiang.gov.cn/fzgh/jihua.html" in urls, "zhejiang fzgh 应在"
    assert "https://news.sina.com.cn/xxx" not in urls, "sina 不应在"
    # beijing.gov.cn/random_home: 不包含任何 path 关键词(tjgb/fzgh/cyfz/zmhd/zhengce/jihua)应被过滤
    assert "https://beijing.gov.cn/random_home" not in urls, "beijing home 应过滤"
    # 所有 source 应变为 gov
    assert all(d.source == "gov" for d in docs), "source 应改为 gov"
    print(f"[OK] 5. Gov 白名单匹配 | 过滤后 {len(docs)} 条")
    return failures


# ---- 6. SearchCollector 并发 + 去重 + 粗排 ----
def test_collector():
    failures: list[str] = []
    class _WP(SearchProvider):
        name = "mock-web"
        def search(self, query, max_results=10):
            # 每个 query 给 2 条不同 URL,保证去重后集合足够大
            q_key = hash(query) % 1000
            return [
                RawDoc(title=f"W1-{q_key}", url=f"https://a.com/{q_key}", snippet="安吉县竹产业产值"),
                RawDoc(title=f"W2-{q_key}", url=f"https://b.com/{q_key}", snippet="无关"),
            ]

    class _GP(SearchProvider):
        name = "mock-gov"
        def search(self, query, max_results=10):
            return [
                RawDoc(title="G1", url="https://a.com/dup", snippet="重复URL"),
                RawDoc(title="G2", url="https://gov.cn/good", snippet="安吉县 竹产业 十四五 规划"),
            ]

    s = make_settings()
    s.search.max_results = 3
    col = SearchCollector(
        web_provider=_WP(),
        gov_provider=_GP(),
        settings=s,
        # 简化:只用 2 个 query 避免太多任务
        query_templates=["{county} {focus} 现状", "{county} {focus} 企业"],
        gov_query_templates=["{county} 统计公报"],
    )
    docs = col.collect(county="安吉县", focus="竹产业")
    # web 2 query × 2条 = 4条(不同 URL); gov 1 query × 2条;共 6 条输入
    urls = [d.url for d in docs]
    unique_urls = set(urls)
    assert len(urls) == len(unique_urls), f"去重未生效: {urls}"
    assert len(unique_urls) >= 3, f"去重后至少 3 个 URL, 实际 {unique_urls}"
    # max_results=3 截断
    assert len(docs) == 3, f"max_results=3 应截断为 3, 实际 {len(docs)}"
    # 粗排: 关键词命中多的 URL 应在最前,用固定集合验证 _dedup_and_rank
    from county_research_ai.search.collector import SearchCollector as _C
    all_docs: list[RawDoc] = [
        RawDoc(title="W1", url="https://a.com/1", snippet="安吉县竹产业产值"),
        RawDoc(title="W2", url="https://b.com/2", snippet="无关"),
        RawDoc(title="G1", url="https://a.com/1", snippet="重复URL"),
        RawDoc(title="G2 安吉县竹产业", url="https://gov.cn/good", snippet="安吉县 竹产业 十四五 规划 安吉县 竹产业"),
    ]
    ranked = _C._dedup_and_rank(_C, all_docs, top=10, keywords=["安吉县", "竹产业"])  # type: ignore[arg-type]
    ranked_urls = [d.url for d in ranked]
    # a.com/1: 安吉县×1,竹产业×1 = 2; gov.cn/good: title含两次各+2,snippet含各2次+4 = 总共 4+4=8
    assert ranked_urls[0] == "https://gov.cn/good", f"dedup_rank 首条应 gov.cn/good: {ranked_urls}"
    print(f"[OK] 6. Collector 去重+粗排+截断 | dedup={len(unique_urls)} rank首={ranked_urls[0]}")
    return failures


def main() -> int:
    all_failures: list[str] = []
    all_failures += test_provider_factory()
    all_failures += test_tavily()
    all_failures += test_serper()
    all_failures += test_bing()
    all_failures += test_gov_whitelist()
    all_failures += test_collector()
    print()
    if all_failures:
        print(f"❌ {len(all_failures)} 项失败:")
        for f in all_failures:
            print(f"  - {f}")
        return 1
    print("✅ Search 层(web + gov + collector)全部 6 组测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
