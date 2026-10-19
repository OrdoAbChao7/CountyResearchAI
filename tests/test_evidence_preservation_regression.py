"""Regression tests for county-level evidence preservation.

These cases reproduce data loss seen in the 2026-10-19 Deqing experiment.
"""
import json
from pathlib import Path

from county_research_ai.config import QualityConfig
from county_research_ai.evidence.source_contract import serialize_source_documents
from county_research_ai.evidence.store import EvidenceStore
from county_research_ai.models import CountyInfo, ProcessedData, RawDoc
from county_research_ai.processor import DocumentProcessor

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEQING_SNAPSHOT_C = (
    _REPO_ROOT
    / "experiments/independent_comparison/runs/continuation_natural_stage_b_deepseek_flash_20261019"
    / "continuation_natural_stage_b_deepseek_flash_20261019_region_01_snapshot_r1_C"
)


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


def test_saved_deqing_c_archive_regression_generates_scorable_source_contract():
    """Real Deqing RawDocs must produce source content usable by offline scoring."""
    raw_path = _DEQING_SNAPSHOT_C / "data/raw/德清县/20261018/raw_docs.json"
    processed_path = _DEQING_SNAPSHOT_C / (
        "data/processed/德清县/德清县产业现状与2024年主要经济指标.json"
    )
    raw_docs = [RawDoc(**item) for item in json.loads(raw_path.read_text(encoding="utf-8"))]
    processed = ProcessedData(
        **json.loads(processed_path.read_text(encoding="utf-8"))
    )
    facts = EvidenceStore().ingest_documents(
        processed.docs, county="德清县", focus="2024年主要经济指标"
    )
    context = processed.render_for_llm(max_chars=15000)
    required = ("722.5", "300.6", "5.8%", "7.7%")

    assert all(any(value in doc.model_dump_json() for doc in raw_docs) for value in required)
    assert all(any(value in doc.model_dump_json() for doc in processed.docs) for value in required)
    assert all(any(value in fact.model_dump_json() for fact in facts) for value in required)
    assert all(value in context for value in required)

    legacy_source_archive = json.loads(
        (_DEQING_SNAPSHOT_C / "sources.json").read_text(encoding="utf-8")
    )
    assert isinstance(legacy_source_archive, dict)

    source_archive = serialize_source_documents(raw_docs)
    assert isinstance(source_archive, list) and source_archive
    assert all(item.get("content") for item in source_archive)
    assert all(item.get("doc_id") for item in source_archive)
    assert all(item.get("content_hash") for item in source_archive)
    assert all(item.get("fetch_status") == "fetched" for item in source_archive)
    assert all(
        {
            "title",
            "url",
            "content",
            "provider",
            "source_type",
            "document_timestamp",
            "chunks",
        }.issubset(item)
        for item in source_archive
    )
    assert all(item["chunks"] for item in source_archive)
    assert all(
        {"chunk_id", "text", "start_offset", "end_offset"}.issubset(item["chunks"][0])
        for item in source_archive
    )
    assert all(
        any(value in json.dumps(item, ensure_ascii=False) for item in source_archive)
        for value in required
    )


def test_compressed_one_line_statistics_keep_metric_value_and_unit_together():
    doc = RawDoc(
        title="2024年德清县统计公报",
        url="https://deqing.gov.cn/bulletin",
        content=(
            "历史统计背景" * 70
            + "规模以上工业增加值300.6亿元，同比增长7.7%"
            + "其他统计背景" * 70
        ),
    )

    facts = EvidenceStore().extract_evidence_from_doc(doc, county="德清县")

    assert any("300.6亿元" in item.claim for item in facts)
    assert any("规模以上工业增加值" in item.claim for item in facts)


def test_processing_records_content_truncation_reason():
    processor = DocumentProcessor(
        QualityConfig(max_evidence_length=40, min_content_length=10)
    )
    doc = RawDoc(
        title="长统计公报",
        url="https://deqing.gov.cn/long",
        content="原始统计正文" * 20,
    )

    processed = processor.clean(doc)

    assert processed.content_truncated is True
    assert processed.content_original_length == len("原始统计正文" * 20)
    assert processed.truncation_reason == "max_evidence_length:40"


def test_context_audit_keeps_late_local_facts_and_records_budget_use():
    national = RawDoc(
        title="全国2024年统计公报",
        url="https://stats.gov.cn/2024",
        content="全国背景信息" * 300,
    )
    local = RawDoc(
        title="2024年德清县统计公报",
        url="https://deqing.gov.cn/2024",
        content=(
            "县级背景信息" * 250
            + "2024年德清县GDP为722.5亿元，同比增长5.8%。"
            + "规模以上工业增加值300.6亿元，同比增长7.7%。"
        ),
    )
    processed = ProcessedData(
        county=CountyInfo(name="德清县"),
        focus="2024年主要经济指标",
        docs=[national, local],
    )

    rendered = processed.render_for_llm(max_chars=900)

    assert len(rendered) <= 900
    assert "2024年德清县统计公报" in rendered
    assert "722.5亿元" in rendered
    assert "300.6亿元" in rendered
    assert processed.render_audit.truncated_doc_indices == [1, 2]
    assert processed.render_audit.excluded_doc_indices == []
    assert processed.render_audit.exclusion_reasons["2"] == "budget_excerpt"


def test_national_gdp_is_not_classified_as_deqing_county_gdp():
    national = RawDoc(
        title="2024年国民经济和社会发展统计公报",
        url="https://stats.gov.cn/national-2024",
        content="初步核算，2024年国内生产总值（GDP）1349084亿元，比上年增长5.0%。",
        domain_type="government",
        credibility_score=0.95,
    )
    local = RawDoc(
        title="2024年德清县国民经济和社会发展统计公报",
        url="https://deqing.gov.cn/local-2024",
        content="初步核算，2024年德清县生产总值（GDP）722.5亿元，同比增长5.8%。",
        domain_type="government",
        credibility_score=0.95,
    )

    facts = EvidenceStore().ingest_documents(
        [national, local], county="德清县", focus="2024年主要经济指标"
    )

    national_fact = next(item for item in facts if "1349084" in item.claim)
    local_fact = next(item for item in facts if "722.5" in item.claim)
    assert national_fact.administrative_scope == "全国范围"
    assert local_fact.administrative_scope == "县域本级"
