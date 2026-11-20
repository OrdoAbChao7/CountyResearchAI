from __future__ import annotations

from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    EvidencePack,
    QuestionSlot,
    SourceDocument,
)
from county_research_ai.evidence.bound_verifier import EvidenceBoundVerifier


def _evidence(metric: str = "地区生产总值") -> EvidencePack:
    slot = QuestionSlot(
        slot_id="snapshot:economic_scale",
        research_question="德清县经济规模",
        required_metrics=["地区生产总值"],
        region="德清县",
    )
    source = SourceDocument(
        doc_id="deqing-report",
        canonical_url="https://deqing.gov.cn/report",
        source_title="德清县统计公报",
        metadata={"credibility_score": 0.95},
    )
    chunk = EvidenceChunk(
        chunk_id="deqing-report:1",
        document_id=source.doc_id,
        text="2024年德清县地区生产总值为722.5亿元。",
    )
    claim = AtomicClaim(
        claim_id="claim:gdp",
        statement="2024年德清县地区生产总值为722.5亿元",
        region_id="德清县",
        metric_id=metric,
        value="722.5",
        unit="亿元",
        period="2024",
        source_ids=[source.doc_id],
        evidence_chunk_ids=[chunk.chunk_id],
        verification_status="supported",
    )
    return EvidencePack(
        research_slot=slot,
        selected_claims=[claim],
        selected_chunks=[chunk],
        source_map={source.doc_id: source},
        token_budget=1000,
        total_chars=len(chunk.text),
        status="complete",
    )


def test_same_value_different_metric_is_not_supported_by_claim_graph():
    verifier = EvidenceBoundVerifier()
    annotated, report = verifier.verify_markdown(
        "德清县工业增加值为722.5亿元。", [_evidence()], county="德清县"
    )

    assert report.verified_claims_count == 0
    assert report.unverified_claims_count == 1
    assert "未找到匹配的指标、数值和来源证据" in annotated
    assert "https://deqing.gov.cn/report" not in annotated


def test_numeric_value_cannot_be_borrowed_from_another_metric_in_same_line():
    verifier = EvidenceBoundVerifier()
    annotated, report = verifier.verify_markdown(
        "2024年德清县地区生产总值待核实，工业增加值为722.5亿元。",
        [_evidence()],
        county="德清县",
    )

    assert report.verified_claims_count == 0
    assert report.unverified_claims_count == 1
    assert "https://deqing.gov.cn/report" not in annotated


def test_national_scope_claim_cannot_support_county_value():
    pack = _evidence()
    pack.selected_claims[0].administrative_scope = "全国范围"

    _, report = EvidenceBoundVerifier().verify_markdown(
        "2024年德清县地区生产总值为722.5亿元。", [pack], county="德清县"
    )

    assert report.verified_claims_count == 0
    assert report.unverified_claims_count == 1


def test_numeric_markdown_table_and_bold_fact_are_audited():
    table = "| 年份 | 地区生产总值 |\n|---|---|\n| 2023 | 999.9亿元 |"
    bold = "**德清县拥有全国领先产业集群。**"

    annotated, report = EvidenceBoundVerifier().verify_markdown(
        f"{table}\n{bold}", [], county="德清县"
    )

    assert report.unverified_claims_count == 2
    assert "未找到匹配的指标、数值和来源证据" in annotated
    assert "未找到匹配的县域事实 Claim/Chunk/Source" in annotated


def test_supported_claim_requires_linked_chunk_and_source_url():
    verifier = EvidenceBoundVerifier()
    annotated, report = verifier.verify_markdown(
        "2024年德清县地区生产总值为722.5亿元。", [_evidence()], county="德清县"
    )

    assert report.verified_claims_count == 1
    assert report.unverified_claims_count == 0
    assert "https://deqing.gov.cn/report" in annotated
    assert "原文：\"2024年德清县地区生产总值为722.5亿元。\"" in annotated


def test_same_metric_and_value_from_another_region_is_not_local_support():
    pack = _evidence()
    pack.selected_claims[0].region_id = "安吉县"
    verifier = EvidenceBoundVerifier()

    annotated, report = verifier.verify_markdown(
        "德清县地区生产总值为722.5亿元。", [pack], county="德清县"
    )

    assert report.verified_claims_count == 0
    assert report.unverified_claims_count == 1
    assert "https://deqing.gov.cn/report" not in annotated


def test_matching_claim_without_canonical_source_url_is_not_cited():
    pack = _evidence()
    pack.source_map["deqing-report"].canonical_url = ""
    verifier = EvidenceBoundVerifier()

    annotated, report = verifier.verify_markdown(
        "德清县地区生产总值为722.5亿元。", [pack], county="德清县"
    )

    assert report.verified_claims_count == 0
    assert report.unverified_claims_count == 1
    assert "https://" not in annotated


def test_reverification_does_not_duplicate_source_citation():
    verifier = EvidenceBoundVerifier()
    first, _ = verifier.verify_markdown(
        "2024年德清县地区生产总值为722.5亿元。", [_evidence()], county="德清县"
    )
    second, _ = verifier.verify_markdown(first, [_evidence()], county="德清县")

    assert second.count("[证据：") == 1


def test_low_confidence_source_is_not_treated_as_verified_support():
    pack = _evidence()
    pack.source_map["deqing-report"].metadata["credibility_score"] = 0.3

    annotated, report = EvidenceBoundVerifier().verify_markdown(
        "德清县地区生产总值为722.5亿元。", [pack], county="德清县"
    )

    assert report.verified_claims_count == 0
    assert report.unverified_claims_count == 1
    assert "https://deqing.gov.cn/report" not in annotated


def test_unsupported_county_specific_attribute_is_flagged_without_numbers():
    annotated, report = EvidenceBoundVerifier().verify_markdown(
        "德清县拥有全国领先的竹产业集群。", [], county="德清县"
    )

    assert report.unverified_claims_count == 1
    assert "未找到匹配的县域事实 Claim/Chunk/Source" in annotated


def test_unmapped_non_numeric_material_statement_is_not_left_as_fact():
    annotated, report = EvidenceBoundVerifier().verify_markdown(
        "当地产业链已形成完整闭环。", [], county="德清县"
    )

    assert report.unverified_claims_count == 1
    assert "未映射的事实/分析陈述" in annotated


def test_same_metric_value_in_wrong_year_is_not_supported():
    annotated, report = EvidenceBoundVerifier().verify_markdown(
        "2023年德清县地区生产总值为722.5亿元。", [_evidence()], county="德清县"
    )

    assert report.verified_claims_count == 0
    assert report.unverified_claims_count == 1
    assert "https://deqing.gov.cn/report" not in annotated
