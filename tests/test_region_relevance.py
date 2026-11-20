"""Region relevance gate tests.

The fixture set is the eight source titles/URLs persisted by the second live
smoke (2026-11-20). Five of them are national or another region's pages; the
gate must keep only the three that are about 安吉县 before ranking/ingestion.
"""
from __future__ import annotations

from county_research_ai.models import RawDoc
from county_research_ai.search.adaptive_retrieval import (
    AdaptiveRetrievalController,
    RetrievalBudget,
)
from county_research_ai.search.base import SearchProvider
from county_research_ai.search.collector import SearchCollector
from county_research_ai.search.query_engine import QueryEngine
from county_research_ai.search.region_relevance import (
    RegionVerdict,
    assess_region_relevance,
    filter_documents_for_region,
)

ANJI_BULLETIN_TITLE = (
    "(湖州市)2025年安吉县国民经济和社会发展统计公报-红黑统计公报库"
)
ANJI_ANALYSIS_TITLE = "小蜂观察：浙江省安吉县竹产业高质量发展路径分析-农小蜂"
ANJI_2011_TITLE = (
    "浙江省安吉县竹产业2011年预计产值可达130多亿_产业动态_产业发展_国际竹藤中心"
)
NATIONAL_2023_TITLE = "中华人民共和国2023年国民经济和社会发展统计公报 - 国家统计局"
NATIONAL_2026_INDUSTRY_TITLE = "2026年8月份规模以上工业增加值增长5.2% - 国家统计局"
NATIONAL_DISCLOSURE_TITLE = "国家统计局信息公开"
FUJIAN_TITLE = "统计公报_ 数据发布_ 福建省人民政府门户网站"
LUOYANG_TITLE = (
    "洛阳市人民政府关于印发洛阳市国民经济和社会发展第十五个五年规划纲要的通知"
    "_2026年_洛阳市人民政府"
)

RECORDED_SOURCES: tuple[tuple[str, str], ...] = (
    (ANJI_BULLETIN_TITLE, "https://tjgb.hongheiku.com/xjtjgb/xj2020/69856.html"),
    (
        NATIONAL_2026_INDUSTRY_TITLE,
        "https://stats.gov.cn/sj/zxfb/202609/t20260915_1965308.html",
    ),
    (
        NATIONAL_2023_TITLE,
        "https://stats.gov.cn/sj/zxfb/202402/t20240228_1947915.html",
    ),
    (
        NATIONAL_DISCLOSURE_TITLE,
        "https://stats.gov.cn/WZWSREL3h4Z2svc2pmYi96eGZiMjAyMC8yMDI1MTAvdDIwMjUxMDIwXzE5NjE2MTEuaHRtbA==",
    ),
    (ANJI_ANALYSIS_TITLE, "https://abeedata.com/home/article/detail/id/25883"),
    (LUOYANG_TITLE, "https://ly.gov.cn/2026/06-17/1067947.html"),
    (
        ANJI_2011_TITLE,
        "https://icbr.ac.cn/cyfz/cydt/content_7847",
    ),
    (FUJIAN_TITLE, "https://fujian.gov.cn/zwgk/sjfb/tjgb"),
)

EXPECTED_VERDICTS = {
    ANJI_BULLETIN_TITLE: RegionVerdict.REGION,
    NATIONAL_2026_INDUSTRY_TITLE: RegionVerdict.NATIONAL,
    NATIONAL_2023_TITLE: RegionVerdict.NATIONAL,
    NATIONAL_DISCLOSURE_TITLE: RegionVerdict.NATIONAL,
    ANJI_ANALYSIS_TITLE: RegionVerdict.REGION,
    LUOYANG_TITLE: RegionVerdict.OTHER_REGION,
    ANJI_2011_TITLE: RegionVerdict.REGION,
    FUJIAN_TITLE: RegionVerdict.OTHER_REGION,
}


def _recorded_documents() -> list[RawDoc]:
    return [RawDoc(title=title, url=url) for title, url in RECORDED_SOURCES]


def test_recorded_live_sources_are_classified_by_region():
    for document in _recorded_documents():
        assessment = assess_region_relevance(document, "安吉县")
        assert assessment.verdict is EXPECTED_VERDICTS[document.title], (
            document.title,
            assessment,
        )


def test_recorded_sources_keep_only_the_three_anji_pages():
    result = filter_documents_for_region(_recorded_documents(), "安吉县")

    kept_titles = {document.title for document in result.kept}
    assert kept_titles == {ANJI_BULLETIN_TITLE, ANJI_ANALYSIS_TITLE, ANJI_2011_TITLE}
    assert len(result.dropped) == 5


def test_county_mention_wins_over_national_source_marker():
    document = RawDoc(
        title="国家统计局：安吉县竹产业产值创新高",
        url="https://stats.gov.cn/example",
    )
    assert assess_region_relevance(document, "安吉县").verdict is RegionVerdict.REGION


def test_prefecture_bulletin_without_county_is_context_not_evidence():
    document = RawDoc(
        title="湖州市2024年国民经济和社会发展统计公报",
        url="https://huzhou.gov.cn/tjgb/2024.html",
    )
    assessment = assess_region_relevance(document, "安吉县")
    assert assessment.verdict is RegionVerdict.CONTEXT
    assert assessment.evidence_bearing is False


def test_unidentified_region_is_kept_for_manual_context():
    document = RawDoc(
        title="某某科技有限公司投产",
        url="https://example.com/news/1",
        snippet="公司新增生产线一条。",
    )
    assessment = assess_region_relevance(document, "安吉县")
    assert assessment.verdict is RegionVerdict.UNKNOWN
    assert assessment.evidence_bearing is True


def test_short_county_name_in_content_is_enough_to_match():
    document = RawDoc(
        title="竹产业高质量发展观察",
        url="https://example.com/analysis",
        content="安吉县坚持绿水青山就是金山银山理念，全县竹林面积达101万亩。",
    )
    assert assess_region_relevance(document, "安吉县").verdict is RegionVerdict.REGION


def test_no_county_requested_keeps_everything():
    document = RawDoc(title="2024年统计公报", url="https://stats.gov.cn/x")
    assessment = assess_region_relevance(document, "")
    assert assessment.verdict is RegionVerdict.UNKNOWN
    assert assessment.evidence_bearing is True


class RecordedSourceProvider(SearchProvider):
    """Returns the same recorded live payload for every query."""

    name = "recorded"

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        return [document.model_copy() for document in _recorded_documents()]


def test_collect_drops_off_region_results(tmp_settings):
    collector = SearchCollector(
        web_provider=RecordedSourceProvider(),
        gov_provider=RecordedSourceProvider(),
        settings=tmp_settings,
    )

    docs = collector.collect(county="安吉县", focus="竹产业")

    assert {doc.title for doc in docs} == {
        ANJI_BULLETIN_TITLE,
        ANJI_ANALYSIS_TITLE,
        ANJI_2011_TITLE,
    }


def test_collect_supplemental_accepts_the_region_hint(tmp_settings):
    collector = SearchCollector(
        web_provider=RecordedSourceProvider(),
        gov_provider=RecordedSourceProvider(),
        settings=tmp_settings,
    )

    docs = collector.collect_supplemental(
        ["安吉县 竹产业 政策"], max_results=10, county="安吉县"
    )

    assert {doc.title for doc in docs} == {
        ANJI_BULLETIN_TITLE,
        ANJI_ANALYSIS_TITLE,
        ANJI_2011_TITLE,
    }


def test_collect_adaptive_reports_region_filtered_count(tmp_settings):
    spec = QueryEngine().generate_research_spec("安吉县", "竹产业", "snapshot")
    controller = AdaptiveRetrievalController(
        spec, budget=RetrievalBudget(max_queries=3)
    )
    plan = controller.initial_plan()
    collector = SearchCollector(
        web_provider=RecordedSourceProvider(),
        gov_provider=RecordedSourceProvider(),
        settings=tmp_settings,
    )

    result = collector.collect_adaptive(plan, controller=controller)

    assert {doc.title for doc in result.documents} == {
        ANJI_BULLETIN_TITLE,
        ANJI_ANALYSIS_TITLE,
        ANJI_2011_TITLE,
    }
    assert result.usage["region_filtered_documents"] > 0
    assert result.usage["returned_documents"] == 3
