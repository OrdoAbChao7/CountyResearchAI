from __future__ import annotations

from datetime import datetime, timezone

from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    QuestionSlot,
    SourceDocument,
)
from county_research_ai.evidence.ledger import EvidenceLedger, build_evidence_ledger
from county_research_ai.models import CountyInfo, ProcessedData, RawDoc


def _source(doc_id: str, url: str, text: str) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=f"来源 {doc_id}",
        url=url,
        canonical_url=url,
        content=text,
        content_hash=f"hash-{doc_id}",
        fetch_status="fetched",
        provider="fixture",
        source_type="government",
        document_timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        chunks=[
            EvidenceChunk(
                chunk_id=f"{doc_id}:chunk:1",
                source_id=doc_id,
                text=text,
                start_offset=0,
                end_offset=len(text),
                offset_status="exact",
            )
        ],
    )


def _claim(claim_id: str, source_id: str, chunk_id: str, *, version: str = "") -> AtomicClaim:
    return AtomicClaim(
        claim_id=claim_id,
        statement="德清县地区生产总值为722.5亿元",
        region="德清县",
        metric="地区生产总值",
        period="2024",
        scope="县域本级",
        unit="亿元",
        version=version,
        source_ids=[source_id],
        evidence_chunk_ids=[chunk_id],
    )


def test_contracts_round_trip_and_keep_unknown_offsets_explicit():
    source = _source("source-1", "https://example.gov.cn/1", "正文")
    source.chunks.append(
        EvidenceChunk(
            chunk_id="source-1:chunk:unknown",
            source_id="source-1",
            text="摘要",
            offset_status="unknown",
        )
    )

    restored = SourceDocument.model_validate_json(source.model_dump_json())

    assert restored == source
    assert restored.chunks[1].start_offset is None
    assert restored.chunks[1].offset_status == "unknown"


def test_ledger_links_claims_sources_and_same_source_reposts():
    ledger = EvidenceLedger()
    first = _source("source-1", "https://example.gov.cn/1", "GDP 722.5亿元")
    repost = first.model_copy(
        update={
            "doc_id": "source-2",
            "source_title": "转载来源",
            "chunks": [
                first.chunks[0].model_copy(
                    update={
                        "chunk_id": "source-2:chunk:1",
                        "document_id": "source-2",
                    }
                )
            ],
        }
    )
    ledger.add_source(first)
    ledger.add_source(repost)
    claim = _claim("claim-1", "source-1", "source-1:chunk:1", version="v1")
    ledger.add_claim(claim)
    ledger.set_verification_status("claim-1", "verified")

    assert ledger.source_relations("source-1") == [("same_source_repost", "source-2")]
    assert ledger.chunks_for_claim("claim-1")[0].source_id == "source-1"
    assert ledger.sources_for_claim("claim-1")[0].doc_id == "source-1"
    assert ledger.find_claims(metric="地区生产总值", version="v1")[0].claim_id == "claim-1"
    assert ledger.claims["claim-1"].verification_status == "verified"


def test_evidence_pack_selects_under_budget_and_marks_missing_requirements():
    ledger = EvidenceLedger()
    ledger.add_source(_source("source-1", "https://example.gov.cn/1", "地区生产总值 722.5亿元"))
    ledger.add_source(_source("source-2", "https://example.gov.cn/2", "产业链规划与风险"))
    ledger.add_claim(_claim("claim-1", "source-1", "source-1:chunk:1"))
    slot = QuestionSlot(
        slot_id="snapshot:economic",
        question="当前经济指标是什么？",
        required_metrics=["地区生产总值", "工业增加值"],
        budget_chars=30,
    )

    pack = ledger.select_evidence_pack(slot)

    assert pack.total_chars <= 30
    assert pack.status == "partial"
    assert "工业增加值" in pack.missing_requirements
    assert pack.claims[0].claim_id == "claim-1"


def test_evidence_pack_prefers_chunks_inside_requested_period():
    ledger = EvidenceLedger()
    ledger.add_source(SourceDocument(
        doc_id="timeline",
        canonical_url="https://example.gov.cn/timeline",
        source_title="县志",
        chunks=[
            EvidenceChunk(
                chunk_id="timeline:1956",
                document_id="timeline",
                text="1956年县办工业形成。",
                year_hints=["1956"],
            ),
            EvidenceChunk(
                chunk_id="timeline:2018",
                document_id="timeline",
                text="2018年县办工业升级。",
                year_hints=["2018"],
            ),
        ],
    ))
    slot = QuestionSlot(
        slot_id="history:state",
        research_question="计划经济时期工业发展",
        required_metrics=["县办工业"],
        time_period="1949-1978",
        budget_chars=len("1956年县办工业形成。"),
    )

    pack = ledger.select_evidence_pack(slot)

    assert [chunk.chunk_id for chunk in pack.selected_chunks] == ["timeline:1956"]
    assert pack.selected_evidence_reasons["timeline:1956"] == "period:1956;required_metric:县办工业"
    assert pack.excluded_evidence_reasons["timeline:2018"] == "outside_requested_period"


def test_evidence_pack_excludes_unmatched_chunks_when_relevant_evidence_exists():
    ledger = EvidenceLedger()
    ledger.add_source(SourceDocument(
        doc_id="source",
        canonical_url="https://example.gov.cn/source",
        chunks=[
            EvidenceChunk(chunk_id="source:match", document_id="source", text="工业产值增加。"),
            EvidenceChunk(chunk_id="source:noise", document_id="source", text="无关背景材料。"),
        ],
    ))

    pack = ledger.select_evidence_pack(QuestionSlot(
        slot_id="history:industry",
        research_question="工业发展",
        required_metrics=["工业"],
        budget_chars=100,
    ))

    assert [chunk.chunk_id for chunk in pack.selected_chunks] == ["source:match"]
    assert pack.excluded_evidence_reasons["source:noise"] == "unmatched_requirements"


def test_evidence_pack_retains_one_period_only_context_passage_per_source():
    ledger = EvidenceLedger()
    ledger.add_source(SourceDocument(
        doc_id="timeline",
        canonical_url="https://example.gov.cn/timeline",
        chunks=[
            EvidenceChunk(chunk_id="timeline:match", document_id="timeline", text="工业扩张"),
            EvidenceChunk(
                chunk_id="timeline:date-1",
                document_id="timeline",
                text="1956年设立县办企业。",
                year_hints=["1956"],
            ),
            EvidenceChunk(
                chunk_id="timeline:date-2",
                document_id="timeline",
                text="1965年调整企业布局。",
                year_hints=["1965"],
            ),
            EvidenceChunk(
                chunk_id="timeline:date-3",
                document_id="timeline",
                text="1975年再次调整企业布局。",
                year_hints=["1975"],
            ),
        ],
    ))

    pack = ledger.select_evidence_pack(QuestionSlot(
        slot_id="history:state",
        research_question="计划时期工业",
        required_metrics=["工业扩张"],
        time_period="1949-1978",
        budget_chars=100,
    ))

    assert {chunk.chunk_id for chunk in pack.selected_chunks} == {
        "timeline:match",
        "timeline:date-1",
        "timeline:date-3",
    }
    assert pack.selected_evidence_reasons["timeline:date-1"] == "period_only:1956"
    assert pack.excluded_evidence_reasons["timeline:date-2"] == "period_only_fallback"


def test_evidence_pack_prioritizes_years_explicitly_requested_by_task():
    ledger = EvidenceLedger()
    ledger.add_source(SourceDocument(
        doc_id="timeline",
        canonical_url="https://example.gov.cn/timeline",
        chunks=[
            EvidenceChunk(chunk_id="timeline:2010", document_id="timeline", text="2010年完成产业园区建设。", year_hints=["2010"]),
            EvidenceChunk(chunk_id="timeline:2020", document_id="timeline", text="2020年推进产业转型升级。", year_hints=["2020"]),
        ],
    ))

    pack = ledger.select_evidence_pack(QuestionSlot(
        slot_id="history:contemporary",
        research_question="新世纪发展重点，尤其核对2020年变化",
        time_period="2001-至今",
        budget_chars=len("2020年推进产业转型升级。"),
    ))

    assert [chunk.chunk_id for chunk in pack.selected_chunks] == ["timeline:2020"]
    assert pack.selected_evidence_reasons["timeline:2020"] == "period:2020;requested_year:2020"
    assert pack.excluded_evidence_reasons["timeline:2010"] == "budget_exceeded"


def test_legacy_adapter_extracts_year_hints_for_period_packs():
    processed = ProcessedData(
        county=CountyInfo.from_name("安吉县"),
        focus="历史",
        docs=[RawDoc(
            title="地方志",
            url="https://example.gov.cn/history",
            content="1956年设立国营林场。2018年发展现代产业。",
        )],
    )

    ledger = build_evidence_ledger(processed)

    years = {year for chunk in ledger.chunks.values() for year in chunk.year_hints}
    assert {"1956", "2018"}.issubset(years)


def test_ledger_keeps_versioned_values_as_distinct_claims_and_missing_evidence_visible():
    ledger = EvidenceLedger()
    ledger.add_source(_source("source-1", "https://example.gov.cn/1", "旧值"))
    ledger.add_claim(_claim("claim-v1", "source-1", "source-1:chunk:1", version="v1"))
    ledger.add_claim(
        AtomicClaim(
            **{
                **_claim("claim-v2", "source-1", "source-1:chunk:1", version="v2").model_dump(),
                "evidence_chunk_ids": [],
                "source_ids": [],
            }
        )
    )

    assert {claim.version for claim in ledger.find_claims(metric="地区生产总值")} == {"v1", "v2"}
    assert ledger.claims["claim-v2"].verification_status == "unverified"
    assert ledger.claims["claim-v2"].evidence_chunk_ids == []


def test_ledger_requires_evidence_for_verified_and_normalizes_supported_units():
    ledger = EvidenceLedger()
    source = _source("source-1", "https://example.gov.cn/1", "GDP 1亿元")
    ledger.add_source(source)
    ledger.add_claim(
        AtomicClaim(
            claim_id="claim-yuan",
            statement="地区生产总值为1亿元",
            region_id="德清县",
            metric_id="宏观GDP",
            value="1",
            unit="亿元",
            period="2024",
            administrative_scope="县域本级",
            statistical_caliber="宏观GDP",
            source_ids=[source.doc_id],
            evidence_chunk_ids=[source.chunks[0].chunk_id],
            verification_status="verified",
        )
    )
    ledger.add_claim(
        AtomicClaim(
            claim_id="claim-wan",
            statement="地区生产总值为10000万元",
            region_id="德清县",
            metric_id="宏观GDP",
            value="10000",
            unit="万元",
            period="2024",
            administrative_scope="县域本级",
            statistical_caliber="宏观GDP",
            source_ids=[],
            evidence_chunk_ids=[],
            verification_status="verified",
        )
    )

    assert ledger.claims["claim-wan"].verification_status == "unverified"
    assert ledger.claims["claim-wan"].verification_reason == "no_evidence_chunk"
    assert [claim.claim_id for claim in ledger.find_equivalent_claims(ledger.claims["claim-yuan"])] == ["claim-wan"]


def test_legacy_adapter_traces_claim_into_pack_and_llm_context():
    doc = RawDoc(
        title="德清县统计公报",
        url="https://example.gov.cn/deqing/2024",
        content="2024年德清县地区生产总值为722.5亿元。",
        source="government",
        domain_type="government",
        credibility_score=0.95,
    )
    processed = ProcessedData(
        county=CountyInfo.from_name("德清县"),
        focus="县域经济",
        docs=[doc],
    )

    ledger = build_evidence_ledger(processed)
    claim = ledger.find_claims(metric="宏观GDP")[0]
    pack = ledger.select_evidence_pack(
        QuestionSlot(
            slot_id="snapshot:gdp",
            research_question="德清县 GDP 是多少？",
            required_metrics=["宏观GDP"],
            budget_chars=2000,
        )
    )
    rendered = processed.model_copy(update={"evidence_pack": pack}).render_for_llm(2000)

    assert claim.source_ids == [next(iter(ledger.sources))]
    assert claim.evidence_chunk_ids
    assert pack.claims[0].claim_id == claim.claim_id
    assert pack.source_map[claim.source_ids[0]].canonical_url == doc.url
    assert "722.5" in rendered
    assert doc.url in rendered


def test_evidence_pack_renderer_groups_chunks_under_one_source_header():
    source = _source("source-1", "https://example.gov.cn/1", "第一段。第二段。")
    pack = EvidenceLedger()
    pack.add_source(source)
    selected = pack.select_evidence_pack(QuestionSlot(
        slot_id="history:overview",
        research_question="历史",
        budget_chars=100,
    ))
    selected = selected.model_copy(update={"selected_chunks": source.chunks})
    processed = ProcessedData(
        county=CountyInfo.from_name("德清县"),
        focus="历史",
        docs=[],
        evidence_pack=selected,
    )

    rendered = processed.render_for_llm(1000)

    assert rendered.count(source.canonical_url) == 1
    assert f"片段 {source.chunks[0].start_offset}-{source.chunks[0].end_offset}" in rendered
