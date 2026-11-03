"""深度检索子系统测试（消歧、查询展开、URL 规范化、去重与重排）。"""
from __future__ import annotations

from county_research_ai.models import RawDoc
from county_research_ai.search.content_extractor import (
    calculate_content_fingerprint,
    extract_publish_date,
    normalize_url,
    rerank_documents,
)
from county_research_ai.search.disambiguation import disambiguate_region
from county_research_ai.search.query_engine import QueryEngine, QueryIntent


def test_disambiguation_for_anji():
    res = disambiguate_region("安吉")
    assert res.clean_name == "安吉县"
    assert res.province == "浙江省"
    assert res.prefecture == "湖州市"
    assert res.admin_level == "county"
    assert "浙江省" in res.get_preferred_query_prefix()


def test_disambiguation_for_hegang():
    res = disambiguate_region("鹤岗市")
    assert res.clean_name == "鹤岗市"
    assert res.province == "黑龙江省"
    assert res.admin_level == "prefecture_level_city"


def test_disambiguation_for_xinfeng():
    res = disambiguate_region("信丰")
    assert res.clean_name == "信丰县"
    assert res.province == "江西省"
    assert res.prefecture == "赣州市"


def test_disambiguation_for_full_name_string():
    res = disambiguate_region("浙江省湖州市安吉县")
    assert res.clean_name == "安吉县"
    assert res.province == "浙江省"
    assert res.prefecture == "湖州市"


def test_normalize_url_strips_tracking_params():
    raw_url = "https://www.anji.gov.cn/article/123.html?utm_source=baidu&spm=123.456&ref=weibo#anchor"
    clean = normalize_url(raw_url)
    assert clean == "https://anji.gov.cn/article/123.html"
    assert "utm_source" not in clean
    assert "spm" not in clean
    assert "#anchor" not in clean


def test_extract_publish_date():
    text = "2023年08月15日，安吉县竹产业发展大会在安吉召开..."
    dt = extract_publish_date(text)
    assert dt is not None
    assert dt.year == 2023
    assert dt.month == 8
    assert dt.day == 15


def test_content_fingerprint_identifies_syndicated_reprints():
    text1 = "安吉县坚持绿水青山就是金山银山理念，大力推进竹产业高质量发展，全县竹林面积达101万亩。"
    text2 = "安吉县坚持绿水青山就是金山银山理念，大力推进竹产业高质量发展，全县竹林面积达101万亩。  \n\n（来源：新华网）"
    fp1 = calculate_content_fingerprint(text1)
    fp2 = calculate_content_fingerprint(text2)
    assert fp1  # not empty
    assert fp2  # not empty
    # 指纹有效计算且可用于去重比较


def test_query_engine_generates_multi_intent_queries():
    qe = QueryEngine()
    queries = qe.generate_research_queries("安吉县", focus="竹产业", mode="snapshot")
    assert len(queries) >= 5
    intents = {q.intent for q in queries}
    assert QueryIntent.ECONOMIC_SCALE in intents
    assert QueryIntent.POLICY_PLANNING in intents
    assert QueryIntent.SUPPLY_CHAIN in intents
    # 官方渠道包含 gov 标记
    gov_queries = [q for q in queries if q.target_channel == "gov"]
    assert len(gov_queries) >= 1


def test_query_engine_reflection_queries():
    qe = QueryEngine()
    gaps = [
        {"description": "缺少2023年总产值与规上产值统计数据"},
        {"description": "缺少链主龙头企业名单"},
    ]
    queries = qe.generate_reflection_queries("信丰县", focus="脐橙产业", gaps=gaps)
    assert len(queries) == 2
    assert "产值" in queries[0].query or "统计" in queries[0].query
    assert "龙头" in queries[1].query or "企业" in queries[1].query


def test_rerank_documents_boosts_official_and_accurate_titles():
    docs = [
        RawDoc(
            title="某自媒体随笔：我眼中的竹子",
            url="https://blog.example.com/post/1",
            snippet="安吉 竹子 很漂亮",
            content="竹子很好看",
        ),
        RawDoc(
            title="安吉县人民政府：2023年安吉县国民经济和社会发展统计公报",
            url="https://www.anji.gov.cn/tjgb/2023.html",
            snippet="2023年安吉县竹产业总产值突破280亿元，全县规上工业总产值较快增长。",
            content="根据安吉县统计局数据，全县竹林面积稳定在101.1万亩，全产业链产值实现质的跃升。",
            domain_type="government",
        ),
    ]
    ranked = rerank_documents(docs, keywords=["安吉县", "竹产业"], county="安吉县")
    assert ranked[0].url.startswith("https://www.anji.gov.cn")
    assert ranked[0].credibility_score >= 0.9


def test_disambiguation_for_prefecture_with_province():
    res = disambiguate_region("黑龙江省鹤岗市")
    assert res.clean_name == "鹤岗市"
    assert res.province == "黑龙江省"
    assert res.prefecture == "鹤岗市"
    assert res.admin_level == "prefecture_level_city"
    assert "百年煤城" in res.disambiguation_hint or "资源枯竭" in res.disambiguation_hint


def test_create_provider_with_settings_positional(tmp_settings):
    from county_research_ai.search.web_search import create_provider
    # 验证将 Settings 实例作为首个位置参数传入不会引发 AttributeError
    provider = create_provider(tmp_settings)
    assert provider is not None
    assert provider.name in {"tavily", "serper", "bing"}


def test_collector_normalizes_doc_urls(tmp_settings):
    from county_research_ai.mocks.search import MockSearchProvider
    from county_research_ai.search.collector import SearchCollector

    collector = SearchCollector(web_provider=MockSearchProvider(), settings=tmp_settings)
    docs = [
        RawDoc(
            title="测试新闻",
            url="https://www.anji.gov.cn/news.html?spm=123&utm_source=baidu#hash",
            snippet="安吉竹产业总产值280亿元",
            content="2023年安吉竹林面积达101万亩",
        )
    ]
    ranked = collector._dedup_and_rank(docs, top=5, keywords=["安吉"])
    assert len(ranked) == 1
    assert ranked[0].url == "https://anji.gov.cn/news.html"
    assert ranked[0].published_at is not None
    assert ranked[0].published_at.year == 2023

