"""Regression tests for county-level evidence preservation.

These cases reproduce data loss seen in the 2026-10-19 Deqing experiment.
"""
from county_research_ai.models import CountyInfo, ProcessedData, RawDoc
from county_research_ai.processor import DocumentProcessor
from county_research_ai.evidence.store import EvidenceStore


def test_long_statistics_report_is_extractable_after_cleaning():
    local = RawDoc(
        title="2024年德清县国民经济和社会发展统计公报",
        url="https://deqing.gov.cn/tjgb/2024",
        domain_type="government",
        credibility_score=0.95,
        content=(
            "导航菜单 " * 100
            + "初步核算，2024年，全县实现生产总值（GDP）722.5亿元，同比增长5.8%。"
            + "全县实现规模以上工业增加值300.6亿元，同比增长7.7%。"
            + "其他统计信息 " * 100
        ),
    )
    processed = DocumentProcessor().process(
        [local], county=CountyInfo(name="德清县"), focus="产业现状"
    )
    store = EvidenceStore()
    facts = store.ingest_documents(processed.docs, county="德清县", focus="产业现状")
    assert any("722.5亿元" in item.claim for item in facts)
    assert any("300.6亿元" in item.claim for item in facts)


def test_bounded_context_keeps_later_county_specific_evidence():
    national = RawDoc(
        title="中华人民共和国2024年国民经济和社会发展统计公报",
        url="https://stats.gov.cn/2024",
        content="全国宏观指标 " * 1200,
    )
    local = RawDoc(
        title="2024年德清县国民经济和社会发展统计公报",
        url="https://deqing.gov.cn/tjgb/2024",
        content=(
            "网页导航 " * 50
            + "2024年德清县GDP为722.5亿元，同比增长5.8%。"
            + "其他县级统计信息 " * 900
        ),
    )
    evidence = ProcessedData(
        county=CountyInfo(name="德清县"),
        focus="2024年主要经济指标",
        docs=[national, local],
    )
    text = evidence.render_for_llm(max_chars=15000)
    assert "中华人民共和国" in text
    assert "德清县国民经济" in text
    assert "722.5亿元" in text
    assert "5.8%" in text
    assert len(text) <= 15000


def test_cleaner_preserves_newline_boundaries():
    cleaned = DocumentProcessor._clean_text(
        "2024年德清县GDP为722.5亿元。\n\n规模以上工业增加值300.6亿元。"
    )
    assert "\n" in cleaned
    assert "722.5亿元" in cleaned
    assert "300.6亿元" in cleaned
