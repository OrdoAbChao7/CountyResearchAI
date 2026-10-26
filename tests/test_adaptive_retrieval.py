from __future__ import annotations

from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    EvidencePack,
    SourceDocument,
)
from county_research_ai.models import RawDoc
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
