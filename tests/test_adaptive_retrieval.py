from __future__ import annotations

import pytest

from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    EvidencePack,
    ResearchContract,
    SourceDocument,
)
from county_research_ai.evidence.ledger import build_evidence_ledger
from county_research_ai.models import CountyInfo, ProcessedData, RawDoc
from county_research_ai.search.adaptive_retrieval import (
    AdaptiveRetrievalController,
    RetrievalBudget,
    RetrievalStopReason,
    assess_evidence_pack_coverage,
    build_adaptive_query_plan,
    rank_documents_for_slot,
)
from county_research_ai.search.query_engine import QueryEngine


def _pack(slot, *, metric: str, url: str, text: str) -> EvidencePack:
    source = SourceDocument(
        doc_id=url.rsplit("/", 1)[-1],
        canonical_url=url,
        source_title="政府材料",
        chunks=[
            EvidenceChunk(
                chunk_id=f"{slot.slot_id}:chunk",
                document_id=url.rsplit("/", 1)[-1],
                text=text,
                start_offset=0,
                end_offset=len(text),
                offset_status="exact",
            )
        ],
    )
    chunk = source.chunks[0]
    claim = AtomicClaim(
        claim_id=f"{slot.slot_id}:claim",
        statement=text,
        region_id=slot.region,
        metric_id=metric,
        period=slot.time_period,
        source_ids=[source.doc_id],
        evidence_chunk_ids=[chunk.chunk_id],
    )
    return EvidencePack(
        research_slot=slot,
        selected_claims=[claim],
        selected_chunks=[chunk],
        source_map={source.doc_id: source},
        token_budget=1000,
        total_chars=len(text),
        status="complete",
    )


def test_weak_candidate_stays_selected_but_keeps_contract_retrieval_open():
    spec = ResearchContract(
        objective="核验年度竹产业总产值", regions=["安吉县"],
        required_questions=["2024年安吉县竹产业总产值是多少？"],
    ).to_research_spec()
    slot, = spec.question_slots
    doc = RawDoc(
        title="安吉县竹产业资料", url="https://example.com/bamboo", credibility_score=0.5,
        content="2024年安吉县竹产业总产值为192亿元。",
    )
    ledger = build_evidence_ledger(ProcessedData(county=CountyInfo.from_name("安吉县"), focus="竹产业", docs=[doc]))
    pack = ledger.select_evidence_pack(slot)

    coverage = assess_evidence_pack_coverage(spec, [pack])

    assert [claim.value for claim in pack.selected_claims] == ["192"]
    result, = coverage.slots
    assert result.status == "partial"
    assert result.missing_metrics == ("竹产业总产值",)


@pytest.mark.parametrize(("same_text", "groups"), [(True, 1), (False, 2)], ids=["mirror", "distinct-text"])
def test_adaptive_candidate_sources_group_reprints(same_text, groups):
    spec = ResearchContract(
        objective="核验年度竹产业总产值", regions=["安吉县"],
        required_questions=["2024年安吉县竹产业总产值是多少？"],
    ).to_research_spec()
    statement = "2024年安吉县竹产业总产值为280亿元。"
    documents = [
        RawDoc(title="安吉县竹产业统计", url="https://example.gov.cn/statistics", credibility_score=0.9,
               content=statement + "该统计覆盖全县生产与加工。"),
        RawDoc(title="安吉县竹产业资料", url="https://example.org/data", credibility_score=0.7,
               content=statement + ("该统计覆盖全县生产与加工。" if same_text else "资料汇总了县内企业报送的年度数据。")),
    ]
    ledger = build_evidence_ledger(ProcessedData(county=CountyInfo.from_name("安吉县"), focus="竹产业", docs=documents))
    pack = ledger.select_evidence_pack(spec.question_slots[0])

    coverage = assess_evidence_pack_coverage(spec, [pack])

    assert coverage.quality_met and len(pack.source_map) == 2
    assert coverage.independent_source_count == groups


def test_contract_stop_distinguishes_unavailable_route():
    spec = ResearchContract(
        objective="核验年度竹产业总产值", regions=["安吉县"],
        required_questions=["2024年安吉县竹产业总产值是多少？"],
    ).to_research_spec()
    controller = AdaptiveRetrievalController(spec, request_keys=lambda query: None)

    decision = controller.next_round([], round_number=1)

    assert decision.stop_reason == "search_source_unavailable"
    assert not decision.queries and controller.budget.used_queries == 0


def test_mode_specific_plans_have_different_question_slots():
    engine = QueryEngine()
    specs = {
        mode: engine.generate_research_spec("安吉县", "竹产业", mode)
        for mode in ("snapshot", "rise-fall", "long-history")
    }
    plans = {mode: build_adaptive_query_plan(spec) for mode, spec in specs.items()}

    assert specs["snapshot"].question_slots != specs["rise-fall"].question_slots
    assert specs["long-history"].question_slots[0].slot_id.endswith("administration")
    assert {query.slot_id for query in plans["snapshot"].queries}
    assert {query.slot_id for query in plans["snapshot"].queries} != {
        query.slot_id for query in plans["long-history"].queries
    }


def test_ranking_prioritizes_local_metric_and_reliability_over_national_context():
    slot = QueryEngine().generate_question_slots("安吉县", "竹产业", "snapshot")[0]
    docs = [
        RawDoc(
            title="全国统计数据",
            url="https://stats.gov.cn/national",
            content="2024年全国地区生产总值增长，宏观经济运行稳定。",
            domain_type="government",
            credibility_score=0.98,
        ),
        RawDoc(
            title="安吉县统计公报",
            url="https://anji.gov.cn/2024",
            content="2024年安吉县地区生产总值为722.5亿元，竹产业总产值增长。",
            domain_type="government",
            credibility_score=0.95,
        ),
        RawDoc(
            title="竹产业随笔",
            url="https://blog.example/1",
            content="竹子很好，缺少统计数据。",
            credibility_score=0.4,
        ),
    ]

    ranked = rank_documents_for_slot(docs, slot, query="安吉县 2024 地区生产总值")

    assert ranked[0].document.url == "https://anji.gov.cn/2024"
    assert ranked[0].components["region_match"] > ranked[1].components["region_match"]
    assert ranked[0].components["metric_coverage"] == 0.5


def test_ranking_deduplicates_same_source_reposts():
    slot = QueryEngine().generate_question_slots("安吉县", "竹产业", "snapshot")[0]
    text = "2024年安吉县地区生产总值为722.5亿元，竹产业总产值增长。该统计公报还说明县域经济发展及工业增加值情况。"
    docs = [
        RawDoc(title="转载一", url="https://news.example/1", content=text, credibility_score=0.7),
        RawDoc(title="转载二", url="https://news.example/2", content=text, credibility_score=0.8),
    ]

    ranked = rank_documents_for_slot(docs, slot)

    assert len(ranked) == 1
    assert ranked[0].document.url == "https://news.example/2"


def test_coverage_feedback_links_followups_and_stops_on_quality_budget_or_zero_gain():
    engine = QueryEngine()
    spec = engine.generate_research_spec("安吉县", "竹产业", "snapshot")
    core_slots = [slot for slot in spec.question_slots if slot.slot_id.endswith((
        "economic_scale", "industry_structure", "origin", "growth",
        "administration", "geography", "traditional",
    ))]
    packs = [
        _pack(
            slot,
            metric=slot.required_metrics[0],
            url=f"https://anji.gov.cn/{slot.slot_id.rsplit(':', 1)[-1]}",
            text=" ".join(slot.required_metrics),
        )
        for slot in core_slots
    ]
    coverage = assess_evidence_pack_coverage(spec, packs)
    assert coverage.quality_met is True
    assert coverage.independent_source_count == 2

    quality_controller = AdaptiveRetrievalController(spec, budget=RetrievalBudget(max_queries=4))
    quality_decision = quality_controller.next_round(packs, round_number=1)
    assert quality_decision.stop_reason == RetrievalStopReason.QUALITY_MET

    gap_controller = AdaptiveRetrievalController(spec, budget=RetrievalBudget(max_queries=4))
    gap_decision = gap_controller.next_round([], round_number=1)
    assert gap_decision.queries
    empty_coverage = assess_evidence_pack_coverage(spec, [])
    assert all(query.slot_id in empty_coverage.missing_slot_ids for query in gap_decision.queries)
    assert all(query.gap_id.startswith("gap:") for query in gap_decision.queries)


def test_fetch_usage_records_actual_over_budget_and_exhausts_remaining():
    spec = QueryEngine().generate_research_spec("安吉县", "竹产业", "snapshot")
    budget = RetrievalBudget(max_fetches=3)

    assert budget.record_fetches(5) == 5
    assert budget.used_fetches == 5
    assert budget.remaining_fetches == 0

    exhausted = AdaptiveRetrievalController(spec, budget=RetrievalBudget(max_queries=0))
    assert exhausted.next_round([], round_number=1).stop_reason == RetrievalStopReason.BUDGET_EXHAUSTED

    zero_gain = AdaptiveRetrievalController(spec, budget=RetrievalBudget(max_queries=4))
    zero_decision = zero_gain.next_round([], round_number=2, previous_new_evidence=0)
    assert zero_decision.stop_reason == RetrievalStopReason.ZERO_MARGINAL_EVIDENCE


def test_initial_plan_respects_explicit_zero_query_limit():
    spec = QueryEngine().generate_research_spec("安吉县", "竹产业", "snapshot")
    controller = AdaptiveRetrievalController(spec, budget=RetrievalBudget(max_queries=4))

    plan = controller.initial_plan(max_queries=0)

    assert plan.queries == ()
    assert controller.budget.used_queries == 0


_CORE_SUFFIXES = (
    "economic_scale", "industry_structure", "origin", "growth",
    "administration", "geography", "traditional",
)


def _core_packs(spec, *, period: str):
    slots = [
        slot
        for slot in spec.question_slots
        if slot.slot_id.rsplit(":", 1)[-1] in _CORE_SUFFIXES
    ]
    packs = [
        _pack(
            slot,
            metric=slot.required_metrics[0],
            url=f"https://anji.gov.cn/{slot.slot_id.rsplit(':', 1)[-1]}",
            text=" ".join(slot.required_metrics),
        )
        for slot in slots
    ]
    return [
        pack.model_copy(
            update={
                "selected_claims": [
                    claim.model_copy(update={"period": period})
                    for claim in pack.selected_claims
                ]
            }
        )
        for pack in packs
    ]


def test_quality_not_met_without_in_window_claim():
    spec = QueryEngine().generate_research_spec(
        "安吉县", "竹产业", "snapshot", target_years=["2024"]
    )
    packs = _core_packs(spec, period="2023")

    coverage = assess_evidence_pack_coverage(spec, packs)

    assert coverage.topic_coverage_met is True
    assert coverage.period_coverage_met is False
    assert coverage.in_window_claim_count == 0
    assert coverage.quality_met is False


def test_in_window_claim_satisfies_period_coverage():
    spec = QueryEngine().generate_research_spec(
        "安吉县", "竹产业", "snapshot", target_years=["2024"]
    )
    packs = _core_packs(spec, period="2024")

    coverage = assess_evidence_pack_coverage(spec, packs)

    assert coverage.in_window_claim_count == len(packs)
    assert coverage.period_coverage_met is True
    assert coverage.quality_met is True


def test_period_gap_generates_year_query_and_records_text():
    spec = QueryEngine().generate_research_spec(
        "安吉县", "竹产业", "snapshot", target_years=["2024"]
    )
    packs = _core_packs(spec, period="2023")
    controller = AdaptiveRetrievalController(spec, budget=RetrievalBudget(max_queries=4))

    decision = controller.next_round(packs, round_number=1)

    texts = [query.query for query in decision.queries]
    assert decision.stop_reason is None
    assert decision.coverage.period_gap is True
    assert any("2024年" in text for text in texts), texts


def test_multi_year_span_is_not_a_single_year_claim():
    spec = QueryEngine().generate_research_spec(
        "安吉县", "竹产业", "snapshot", target_years=["2024"]
    )
    packs = _core_packs(spec, period="2024-2025")

    coverage = assess_evidence_pack_coverage(spec, packs)

    assert coverage.in_window_claim_count == 0
    assert coverage.period_coverage_met is False
    assert coverage.quality_met is False
