from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    SourceDocument,
)
from county_research_ai.evidence.graph import (
    ClaimRelationKind,
    EvidenceGraphStore,
    classify_claim_relation,
)
from county_research_ai.evidence.ledger import EvidenceLedger
from county_research_ai.evidence.measure import derive_measure_key, normalize_measure


def _claim(claim_id: str, *, measure: str, value: str, unit: str = "亿元") -> AtomicClaim:
    return AtomicClaim(
        claim_id=claim_id,
        statement=f"第一产业增加值{value}{unit}",
        region_id="德清县",
        metric_id="产值与收入",
        measure_id=measure,
        value=value,
        unit=unit,
        period="2024",
        administrative_scope="县域本级",
        statistical_caliber="产值与收入",
    )


def test_fragment_measure_uses_the_surrounding_subject():
    chunk = (
        "其中，第一产业增加值33.0亿元，增长4.3%；"
        "第二产业增加值385.9亿元，增长6.6%。"
    )
    first = derive_measure_key("增长4.3%", chunk_text=chunk, value="4.3%")
    second = derive_measure_key("增长6.6%", chunk_text=chunk, value="6.6%")

    assert first.startswith("第一产业增加值")
    assert second.startswith("第二产业增加值")
    assert first != second


def test_level_measure_prefers_the_statement_subject():
    key = derive_measure_key(
        "第一产业增加值33.0亿元",
        chunk_text="其中，第一产业增加值33.0亿元，增长4.3%",
        value="33.0",
    )

    assert key == "第一产业增加值"


def test_gdp_and_industry_measures_are_different():
    gdp = derive_measure_key(
        "全县实现生产总值（GDP）722.5亿元",
        chunk_text="初步核算，2024年，全县实现生产总值（GDP）722.5亿元",
        value="722.5",
    )
    primary = derive_measure_key("第一产业增加值31.4亿元", value="31.4")

    assert gdp
    assert primary
    assert gdp != primary


def test_different_measure_is_related_not_contradicted():
    left = _claim("left", measure="第一产业增加值", value="31.4")
    right = _claim("right", measure="第二产业增加值", value="378.1")

    relation = classify_claim_relation(left, right)

    assert relation is not None
    assert relation.relation is ClaimRelationKind.RELATED
    assert relation.rationale.startswith("different_measure:")


def test_same_measure_different_value_is_still_a_contradiction():
    left = _claim("left", measure="第一产业增加值", value="31.4")
    right = _claim("right", measure="第一产业增加值", value="30.0")

    relation = classify_claim_relation(left, right)

    assert relation is not None
    assert relation.relation is ClaimRelationKind.CONTRADICTS


def test_measure_key_is_persisted_and_reloaded(tmp_path):
    content = "德清县2024年第一产业增加值31.4亿元。"
    source = SourceDocument(
        doc_id="snap-1",
        title="德清县统计公报",
        url="https://dq.gov.cn/1",
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        retrieved_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        chunks=[
            EvidenceChunk(
                chunk_id="snap-1:chunk:1",
                source_id="snap-1",
                text=content,
                start_offset=0,
                end_offset=len(content),
                offset_status="exact",
            )
        ],
    )
    claim = AtomicClaim(
        claim_id="claim-1",
        statement="第一产业增加值31.4亿元",
        region_id="德清县",
        metric_id="产值与收入",
        measure_id="第一产业增加值",
        value="31.4",
        unit="亿元",
        period="2024",
        source_ids=["snap-1"],
        evidence_chunk_ids=["snap-1:chunk:1"],
    )
    ledger = EvidenceLedger()
    ledger.add_source(source)
    ledger.add_claim(claim)
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")

    store.save_ledger(ledger)

    assert store.get_claim("claim-1").measure_id == "第一产业增加值"
    assert normalize_measure("第一产业增加值31.4亿元") == "第一产业增加值"


def test_measure_identity_can_be_disabled_for_the_old_ablation():
    left = _claim("left", measure="第一产业增加值", value="31.4")
    right = _claim("right", measure="第二产业增加值", value="378.1")

    relation = classify_claim_relation(
        left, right, use_measure_identity=False
    )

    assert relation is not None
    assert relation.relation is ClaimRelationKind.CONTRADICTS


def test_common_measure_aliases_are_canonicalized():
    assert normalize_measure("一产增加值") == "第一产业增加值"
    assert normalize_measure("第一产业增加值") == "第一产业增加值"
    assert normalize_measure("规上工业增加值") == "规模以上工业增加值"


def test_period_is_inferred_only_from_evidence():
    from county_research_ai.evidence.measure import infer_period

    assert infer_period("2024年线上销售额3.6亿元") == "2024"
    assert (
        infer_period(
            "加工产值突破20亿元",
            chunk_text="2024年，信丰县脐橙加工产值突破20亿元。",
            value="20",
        )
        == "2024"
    )
    assert infer_period("种植面积28.5万亩", title="2025年安吉县统计公报") == "2025"
    assert (
        infer_period(
            "种植面积28.5万亩",
            content_prefix="发布日期：2025-11-12 10:31:07",
        )
        == ""
    )
    assert infer_period("没有年份的声明") == ""


def test_infer_claim_period_prefers_local_data_year():
    from county_research_ai.evidence.measure import infer_claim_period

    assert (
        infer_claim_period(
            "2018年安吉县竹产业总产值达到280亿元",
            title="2023年安吉县竹产业专报",
            document_year="2023",
        )
        == "2018"
    )
    assert (
        infer_claim_period(
            "到2030年，安吉县竹产业总产值目标达到500亿元",
            title="2026年安吉县竹产业发展规划",
            document_year="2026",
        )
        == "2030"
    )


def test_infer_claim_period_keeps_multi_year_span():
    from county_research_ai.evidence.measure import infer_claim_period

    assert (
        infer_claim_period(
            "2024-2025年安吉县竹产业累计产值达到500亿元",
            title="2025年安吉县统计公报",
            document_year="2025",
        )
        == "2024-2025"
    )


def test_infer_claim_period_uses_document_year_only_without_any_local_year():
    from county_research_ai.evidence.measure import infer_claim_period

    assert (
        infer_claim_period(
            "安吉县竹产业总产值达到280亿元",
            title="安吉县竹产业专报",
            document_year="2018",
        )
        == "2018"
    )
    assert (
        infer_claim_period(
            "2026年发布的数据显示安吉县竹产业产值达到280亿元",
            title="安吉县竹产业专报",
            document_year="2026",
        )
        == ""
    )
