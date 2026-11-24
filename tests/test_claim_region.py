"""Claim-level region attribution and cross-region isolation regressions."""
from __future__ import annotations

import hashlib

import pytest

from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    QuestionSlot,
    SourceDocument,
)
from county_research_ai.evidence.claim_region import classify_claim_region
from county_research_ai.evidence.graph import EvidenceGraphStore, VerificationStatus
from county_research_ai.evidence.ledger import EvidenceLedger, build_evidence_ledger
from county_research_ai.evidence.store import EvidenceStore
from county_research_ai.models import CountyInfo, ProcessedData, RawDoc


def _processed(county: str, *docs: RawDoc) -> ProcessedData:
    return ProcessedData(
        county=CountyInfo.from_name(county),
        focus="竹产业",
        docs=list(docs),
    )


def _claim_for(ledger: EvidenceLedger, needle: str) -> AtomicClaim:
    return next(claim for claim in ledger.claims.values() if needle in claim.statement)


def _graph_ledger(
    content: str,
    claim: AtomicClaim,
    *,
    title: str,
    url: str = "https://example.gov.cn/article",
) -> EvidenceLedger:
    ledger = EvidenceLedger()
    ledger.add_source(
        SourceDocument(
            doc_id="snap-1",
            title=title,
            url=url,
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
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
    )
    ledger.add_claim(
        claim.model_copy(
            update={
                "source_ids": ["snap-1"],
                "evidence_chunk_ids": ["snap-1:chunk:1"],
            }
        )
    )
    return ledger


def test_county_statistical_claim_is_attributed_to_the_county():
    doc = RawDoc(
        title="安吉县2024年国民经济和社会发展统计公报",
        url="https://anji.gov.cn/tjgb2024",
        snippet="安吉县竹产业全产业链总产值达到280亿元。",
        content="2024年，安吉县竹产业全产业链总产值达到280亿元。",
        domain_type="government",
        credibility_score=0.95,
    )
    store = EvidenceStore()
    items = store.ingest_documents([doc], county="安吉县", focus="竹产业")
    assert items
    assert all(item.region_id == "安吉县" for item in items)

    ledger = build_evidence_ledger(_processed("安吉县", doc))
    claim = _claim_for(ledger, "280亿元")
    assert claim.region_id == "安吉县"
    assert claim.region_source in {"claim", "document"}

    pack = ledger.select_evidence_pack(
        QuestionSlot(
            slot_id="slot:county",
            research_question="安吉县竹产业产值",
            region="安吉县",
            budget_chars=2000,
        )
    )
    assert claim.claim_id in {item.claim_id for item in pack.selected_claims}


def test_guizhou_plan_claim_is_not_attributed_to_the_county():
    doc = RawDoc(
        title="贵州省“十五五”竹产业发展规划",
        url="https://guizhou.gov.cn/plan",
        snippet="到2025年，贵州省竹产业总产值达到500亿元。",
        content="到2025年，贵州省竹产业总产值达到500亿元。",
        domain_type="government",
        credibility_score=0.95,
    )
    store = EvidenceStore()
    items = store.ingest_documents([doc], county="安吉县", focus="竹产业")
    assert items
    assert all(item.region_id != "安吉县" for item in items)
    assert any(item.region_id == "贵州省" for item in items)

    ledger = build_evidence_ledger(_processed("安吉县", doc))
    claim = _claim_for(ledger, "500亿元")
    assert claim.region_id == "贵州省"
    assert claim.region_source == "claim"

    pack = ledger.select_evidence_pack(
        QuestionSlot(
            slot_id="slot:county",
            research_question="安吉县竹产业产值",
            region="安吉县",
            budget_chars=2000,
        )
    )
    assert claim.claim_id not in {item.claim_id for item in pack.selected_claims}


def test_one_article_can_yield_different_claim_regions():
    doc = RawDoc(
        title="安吉县与贵州省竹产业对比",
        url="https://example.com/compare",
        snippet="安吉县竹产业总产值为280亿元。贵州省竹产业总产值为500亿元。",
        content="安吉县竹产业总产值为280亿元。贵州省竹产业总产值为500亿元。",
        domain_type="news",
        credibility_score=0.8,
    )
    ledger = build_evidence_ledger(_processed("安吉县", doc))
    by_value = {claim.statement: claim for claim in ledger.claims.values() if "亿元" in claim.statement}
    assert {claim.region_id for claim in by_value.values()} == {"安吉县", "贵州省"}
    assert next(claim for statement, claim in by_value.items() if "280" in statement).region_id == "安吉县"
    assert next(claim for statement, claim in by_value.items() if "500" in statement).region_id == "贵州省"


@pytest.mark.parametrize(("reference", "subject"), [("安吉县", "德清县"), ("德清县", "安吉县")])
def test_comparison_reference_does_not_own_the_numbers(reference, subject):
    content = f"与{reference}相比，2024年{subject}竹产业总产值为120亿元。"
    doc = RawDoc(title="安吉县竹产业比较材料", url="https://example.gov.cn/compare", content=content)

    ledger = build_evidence_ledger(_processed("安吉县", doc))

    claim = _claim_for(ledger, "120亿元")
    assert claim.region_id == subject
    assert claim.region_source == "claim"


@pytest.mark.parametrize("reference", [
    "占全国竹资源重要地位",
    "占全省竹资源重要地位",
    "占全市竹资源重要地位",
    "与全国平均水平相比",
])
def test_scope_reference_does_not_relabel_the_county_total(reference):
    report = RawDoc(
        title="小蜂观察：浙江省安吉县竹产业转型路径与百亿绿色经济的启示-农小蜂",
        url="https://example.com/anji-bamboo",
        content=f"安吉县竹林面积达100万亩，{reference}，2024年竹产业总产值达192亿元。",
    )
    ledger = build_evidence_ledger(_processed("安吉县", report))

    claim = _claim_for(ledger, "192亿元")
    assert claim.statement == "2024年竹产业总产值达192亿元"
    assert claim.region_id == "安吉县"
    assert claim.administrative_scope == "县域本级"
    assert claim.period == "2024"
    assert any(report.content in chunk.text for chunk in ledger.chunks_for_claim(claim.claim_id))


def test_scope_reference_inside_a_quantity_clause_is_not_the_subject():
    report = RawDoc(
        title="安吉县竹产业资料",
        url="https://example.com/anji-bamboo",
        content="2024年竹产业总产值达192亿元（约占全国产值的10%）。",
    )
    ledger = build_evidence_ledger(_processed("安吉县", report))

    claim = _claim_for(ledger, "192亿元")
    assert claim.region_id == "安吉县"
    assert claim.administrative_scope == "县域本级"


def test_scope_reference_does_not_promote_an_unattributed_total():
    report = RawDoc(
        title="竹产业观察",
        url="https://example.com/bamboo",
        content="安吉县竹林面积达100万亩，占全国竹资源重要地位，2024年竹产业总产值达192亿元。",
    )
    ledger = build_evidence_ledger(_processed("安吉县", report))

    assert _claim_for(ledger, "192亿元").region_id == "UNKNOWN"


@pytest.mark.parametrize(("scope_word", "region", "scope"), [
    ("全国", "全国", "全国范围"),
    ("全省", "浙江省", "全省范围"),
    ("全市", "湖州市", "全市范围"),
])
def test_totals_and_growth_under_explicit_wider_scope_stay_out_of_county_evidence(
    scope_word, region, scope,
):
    report = RawDoc(
        title="安吉县竹产业对照材料",
        url="https://example.com/industry-context",
        content=f"2024年{scope_word}竹产业总产值达800亿元，同比增长5.1%。",
    )
    store = EvidenceStore()
    facts = store.ingest_documents([report], county="安吉县", focus="竹产业")

    assert {fact.claim for fact in facts} == {
        f"2024年{scope_word}竹产业总产值达800亿元", "同比增长5.1%",
    }
    assert {(fact.region_id, fact.administrative_scope) for fact in facts} == {(region, scope)}
    assert store.get_target_items() == []


@pytest.mark.parametrize(("scope_word", "region", "scope"), [
    ("全国", "全国", "全国范围"),
    ("全省", "浙江省", "全省范围"),
    ("全市", "湖州市", "全市范围"),
])
def test_absolute_comparison_denominator_retains_its_scope(scope_word, region, scope):
    report = RawDoc(
        title="安吉县竹产业对照材料",
        url="https://example.com/industry-comparison",
        content=f"2024年安吉县竹产业总产值192亿元，约占{scope_word}竹产业总产值320亿元的60%。",
    )
    ledger = build_evidence_ledger(_processed("安吉县", report))

    total = _claim_for(ledger, "192亿元")
    denominator = _claim_for(ledger, "320亿元")
    assert (total.region_id, total.administrative_scope) == ("安吉县", "县域本级")
    assert (denominator.region_id, denominator.administrative_scope) == (region, scope)


@pytest.mark.parametrize(("scope_word", "region", "scope"), [
    ("全国", "全国", "全国范围"),
    ("全省", "浙江省", "全省范围"),
    ("全市", "湖州市", "全市范围"),
])
def test_year_over_year_parenthetical_preserves_the_upper_level_subject(scope_word, region, scope):
    report = RawDoc(
        title="安吉县竹产业对照材料",
        url="https://example.com/industry-comparison",
        content=f"同时{scope_word}竹产业总产值达800亿元（与上年相比增长5%）。",
    )
    store = EvidenceStore()

    facts = store.ingest_documents([report], county="安吉县")

    assert facts and {(fact.region_id, fact.administrative_scope) for fact in facts} == {(region, scope)}
    assert store.get_target_items() == []


def test_unnamed_total_does_not_switch_from_another_county_to_the_title_county():
    report = RawDoc(
        title="安吉县竹产业对照材料",
        url="https://example.com/industry-comparison",
        content="德清县竹林面积达100万亩，占全国竹资源重要地位，2024年竹产业总产值达192亿元。",
    )
    ledger = build_evidence_ledger(_processed("安吉县", report))

    assert _claim_for(ledger, "192亿元").region_id == "德清县"


@pytest.mark.parametrize(("snippet", "content", "region"), [
    ("", "2024年竹产业总产值达192亿元，以上为全国数据。", "全国"),
    ("2024年竹产业总产值达192亿元。", "德清县竹林面积达100万亩，2024年竹产业总产值达192亿元。", "德清县"),
    ("", "德清县竹产业值得借鉴，2024年本县竹产业总产值达192亿元。", "安吉县"),
    ("", "德清县竹产业值得借鉴！2024年竹产业总产值达192亿元。", "安吉县"),
    ("", "与德清县和长兴县相比全县竹产业总产值达192亿元。", "安吉县"),
    ("", "德清县竹产业值得借鉴，2024年全县竹产业总产值达192亿元。", "安吉县"),
], ids=["scope-after-total", "body-over-snippet", "explicit-local-scope", "sentence-break", "joint-reference", "countywide-scope"])
def test_numeric_scope_uses_the_fact_context_not_the_title_alone(snippet, content, region):
    doc = RawDoc(title="安吉县竹产业统计", url="https://example.com/anji", snippet=snippet, content=content)
    ledger = build_evidence_ledger(_processed("安吉县", doc))
    totals = [claim for claim in ledger.claims.values() if claim.value == "192" and claim.unit == "亿元"]
    assert totals and {claim.region_id for claim in totals} == {region}


@pytest.mark.parametrize("content", [
    "2024年竹产业总产值达192亿元（约占全国竹产业总产值320亿元的60%）。",
    "2024年安吉县竹产业总产值达192亿元，约占全国竹产业总产值320亿元的60%。",
])
def test_a_county_total_and_national_denominator_keep_separate_value_bindings(content):
    doc = RawDoc(title="安吉县竹产业统计", url="https://example.com/anji", content=content)
    ledger = build_evidence_ledger(_processed("安吉县", doc))
    assert {(claim.value, claim.region_id) for claim in ledger.claims.values() if claim.unit == "亿元"} == {
        ("192", "安吉县"), ("320", "全国"),
    }


@pytest.mark.parametrize(("denominator", "region", "scope"), [
    ("全国", "全国", "全国范围"),
    ("浙江省", "浙江省", "全省范围"),
    ("湖州市", "湖州市", "全市范围"),
])
def test_a_value_in_only_a_denominator_is_not_a_county_amount(denominator, region, scope):
    doc = RawDoc(
        title="安吉县竹产业统计", url="https://example.com/anji",
        content=f"2024年安吉县竹产业总产值仅为{denominator}竹产业总产值800亿元的6%。",
    )
    ledger = build_evidence_ledger(_processed("安吉县", doc))
    claim = _claim_for(ledger, "800亿元")
    assert (claim.value, claim.region_id, claim.administrative_scope) == ("800", region, scope)


def test_same_clause_can_report_the_same_value_for_different_counties(tmp_path):
    local_sentence = "安吉县竹产业发展稳健，2024年竹产业总产值为192亿元。"
    doc = RawDoc(
        title="安吉县竹产业统计", url="https://example.gov.cn/anji", credibility_score=0.95,
        content="德清县竹产业发展稳健，2024年竹产业总产值为192亿元。" + local_sentence,
    )
    ledger = build_evidence_ledger(_processed("安吉县", doc))
    totals = {claim.region_id: claim for claim in ledger.claims.values() if claim.value == "192"}
    assert set(totals) == {"安吉县", "德清县"}
    local = totals["安吉县"]
    graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")
    graph.save_ledger(ledger, run_id="county", target_region="安吉县")

    chain = graph.get_chain(local.claim_id, run_id="county")
    assert chain.verification.status is VerificationStatus.SUPPORTED
    assert any(local_sentence in link.span.quote for link in graph.supporting_links(chain))


def test_synonymous_quarters_are_comparable_in_the_graph(tmp_path):
    docs = [
        RawDoc(title="安吉县竹产业统计", url=f"https://example.gov.cn/anji/{index}", credibility_score=0.95,
               content=f"2024年{quarter}，安吉县竹产业总产值达{value}亿元。")
        for index, (quarter, value) in enumerate((("一季度", 9), ("第一季度", 10)))
    ]
    ledger = build_evidence_ledger(_processed("安吉县", *docs))
    graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")
    graph.save_ledger(ledger, run_id="quarter", target_region="安吉县")

    assert len(ledger.claims) == 2
    assert len({claim.period for claim in ledger.claims.values()}) == 1
    assert {graph.get_chain(claim_id, run_id="quarter").verification.status for claim_id in ledger.claims} == {
        VerificationStatus.NEEDS_REVIEW,
    }


def test_an_unnamed_total_in_a_mixed_scope_document_stays_out_of_county_evidence():
    report = RawDoc(
        title="安吉县与全国竹产业对比",
        url="https://example.com/industry-comparison",
        content="2024年竹产业总产值达800亿元。",
    )
    store = EvidenceStore()

    facts = store.ingest_documents([report], county="安吉县", focus="竹产业")

    assert len(facts) == 1
    assert store.get_target_items() == []


def test_legacy_region_assignment_must_match_the_claim_subject(tmp_path):
    statement = "2024年德清县竹产业总产值为120亿元"
    content = f"与安吉县相比，{statement}。"
    claim = AtomicClaim(
        claim_id="claim-comparison", statement=statement, region_id="安吉县", region_source="claim",
        metric_id="产值与收入", value="120", unit="亿元", period="2024",
    )
    ledger = _graph_ledger(content, claim, title="安吉县竹产业比较材料")
    graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")
    graph.save_ledger(ledger, run_id="comparison", target_region="安吉县")
    chain = graph.get_chain("claim-comparison", run_id="comparison")

    assert chain.verification.status is VerificationStatus.INSUFFICIENT
    assert list(graph.supporting_links(chain)) == []


@pytest.mark.parametrize("content", [
    "2024年竹产业总产值为120亿元，以上为全国数据。",
    "德清县竹林面积达100万亩，2024年竹产业总产值为120亿元。",
])
def test_a_legacy_county_claim_requires_the_value_to_belong_to_that_county(tmp_path, content):
    claim = AtomicClaim(
        claim_id="claim-county", statement="2024年竹产业总产值为120亿元", region_id="安吉县",
        region_source="document", metric_id="产值与收入", value="120", unit="亿元", period="2024",
    )
    ledger = _graph_ledger(content, claim, title="安吉县竹产业统计")
    graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")
    graph.save_ledger(ledger, run_id="county", target_region="安吉县")

    chain = graph.get_chain(claim.claim_id, run_id="county")
    assert chain.verification.status is VerificationStatus.INSUFFICIENT
    assert list(graph.supporting_links(chain)) == []


def test_unknown_claim_is_not_promoted_even_when_the_body_mentions_the_county(tmp_path):
    doc = RawDoc(
        title="竹产业观察",
        url="https://example.com/bamboo",
        snippet="全县竹产业总产值100亿元。",
        content="安吉县是著名竹乡。全县竹产业总产值100亿元。",
        domain_type="news",
        credibility_score=0.8,
    )
    store = EvidenceStore()
    items = store.ingest_documents([doc], county="安吉县", focus="竹产业")
    assert items
    assert all(item.region_id == "UNKNOWN" for item in items)

    ledger = build_evidence_ledger(_processed("安吉县", doc))
    claim = _claim_for(ledger, "100亿元")
    assert claim.region_id == "UNKNOWN"
    assert claim.region_source == "unknown"

    graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")
    graph.save_ledger(ledger, target_region="安吉县")
    record = graph.verify_claim(claim.claim_id, target_region="安吉县")
    assert record.status is VerificationStatus.INSUFFICIENT
    assert record.reason == "claim_region_unknown"
    assert record.deterministic_checks["region_present"] is False


def test_cross_region_claim_is_not_comparable_to_the_target(tmp_path):
    content = "贵州省竹产业总产值为500亿元。"
    claim = AtomicClaim(
        claim_id="claim-guizhou",
        statement="贵州省竹产业总产值为500亿元",
        region_id="贵州省",
        region_source="claim",
        metric_id="总产值",
        value="500",
        unit="亿元",
        period="2025",
    )
    ledger = _graph_ledger(content, claim, title="贵州省竹产业规划")
    graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")
    graph.save_ledger(ledger, target_region="安吉县")
    record = graph.verify_claim("claim-guizhou", target_region="安吉县")
    assert record.status is VerificationStatus.NOT_COMPARABLE
    assert record.reason == "claim_region_not_target:贵州省"


def test_region_present_false_blocks_support(tmp_path):
    content = "德清县竹产业总产值为280亿元。"
    claim = AtomicClaim(
        claim_id="claim-no-region-in-evidence",
        statement="安吉县竹产业总产值为280亿元",
        region_id="安吉县",
        region_source="claim",
        metric_id="总产值",
        value="280",
        unit="亿元",
        period="2024",
    )
    ledger = _graph_ledger(content, claim, title="德清县产业报道")
    graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")
    graph.save_ledger(ledger, target_region="安吉县")
    record = graph.verify_claim(
        "claim-no-region-in-evidence", target_region="安吉县"
    )
    assert record.status is VerificationStatus.INSUFFICIENT
    assert record.reason == "claim_region_not_in_evidence"
    assert record.deterministic_checks["region_present"] is False


def test_cross_region_claims_do_not_participate_in_target_conflicts():
    county_doc = RawDoc(
        title="安吉县统计公报",
        url="https://anji.gov.cn/tjgb",
        snippet="安吉县竹产业全产业链总产值达到280亿元。",
        content="安吉县竹产业全产业链总产值达到280亿元。",
        domain_type="government",
        credibility_score=0.95,
    )
    other_doc = RawDoc(
        title="贵州省竹产业规划",
        url="https://guizhou.gov.cn/plan",
        snippet="贵州省竹产业全产业链总产值达到500亿元。",
        content="贵州省竹产业全产业链总产值达到500亿元。",
        domain_type="government",
        credibility_score=0.95,
    )
    store = EvidenceStore()
    items = store.ingest_documents([county_doc, other_doc], county="安吉县", focus="竹产业")
    assert {item.region_id for item in items} == {"安吉县", "贵州省"}
    assert {item.region_id for item in store.get_target_items()} == {"安吉县"}

    conflicts = store.detect_conflicts()
    assert all(
        "500亿元" not in str(conflict.claims)
        for conflict in conflicts
    )


def test_scope_is_not_enough_to_authorise_the_county():
    decision = classify_claim_region(
        "安吉县",
        title="竹产业观察",
        url="https://example.com/a",
        statement="竹产业总产值为100亿元",
        quote="竹产业总产值为100亿元",
        scope="县域本级",
    )
    assert decision.region_id == "UNKNOWN"
    assert decision.source == "unknown"
    assert decision.is_unknown


def test_document_title_with_multiple_regions_keeps_unnamed_claim_unknown():
    decision = classify_claim_region(
        "安吉县",
        title="安吉县与贵州省竹产业对比",
        url="https://example.com/compare",
        statement="竹产业总产值为100亿元",
        quote="竹产业总产值为100亿元",
    )
    assert decision.region_id == "UNKNOWN"
    assert decision.reason == "document_names_multiple_regions"


def test_year_prefixed_county_scope_uses_document_fallback():
    decision = classify_claim_region(
        "安吉县",
        title="(湖州市)2025年安吉县国民经济和社会发展统计公报",
        url="https://tjgb.hongheiku.com/xjtjgb/xj2020/69856.html",
        statement="2023年全县竹产业总产值达到180.28亿元",
        quote="2023年全县竹产业总产值达到180.28亿元",
    )
    assert decision.region_id == "安吉县"
    assert decision.source == "document"
    assert decision.reason == "document_names_county"


def test_share_of_county_scope_is_not_another_region():
    decision = classify_claim_region(
        "安吉县",
        title="安吉县2025年国民经济和社会发展统计公报",
        url="https://anji.gov.cn/tjgb2025",
        statement="占全县规上工业增加值比重为25.6%",
        quote="占全县规上工业增加值比重为25.6%",
    )
    assert decision.region_id == "安吉县"
    assert decision.source == "document"
    assert decision.reason == "document_names_county"


def test_year_end_scope_in_quote_uses_document_region():
    doc = RawDoc(
        title="(湖州市)2024年安吉县国民经济和社会发展统计公报-红黑统计公报库",
        url="https://tjgb.hongheiku.com/xjtjgb/xj2020/59737.html",
        content="2024年末全县机动车保有量达到 22.43万辆，比上年增加 0.79万辆，同比增长3.64%",
    )
    ledger = build_evidence_ledger(_processed("安吉县", doc))
    claim = _claim_for(ledger, "同比增长3.64%")
    assert claim.region_id == "安吉县"
    assert claim.region_source == "document"
    assert claim.period == "2024"


def test_countywide_planning_target_uses_document_region():
    doc = RawDoc(
        title="安吉县政府工作报告 - 浙江生态文明研究院",
        url="https://zeca.ac.cn/h-nd-299.html",
        content=(
            "综合考虑各方面因素，建议今年全县经济社会发展的**主要预期目标是**："
            "地区生产总值增长6%以上，一般公共预算收入与经济增长基本同步，"
            "城乡居民人均可支配收入增速快于地区生产总值增速，节能减排降碳完成省市下达目标任务"
        ),
    )
    ledger = build_evidence_ledger(_processed("安吉县", doc))
    claim = _claim_for(ledger, "地区生产总值增长6%以上")
    assert claim.region_id == "安吉县"
    assert claim.region_source == "document"
    assert claim.period == ""


def test_year_end_scope_without_document_region_stays_unknown():
    decision = classify_claim_region(
        "安吉县",
        title="机动车保有量统计",
        url="https://example.com/vehicles",
        statement="同比增长3.64%",
        quote="2024年末全县机动车保有量达到 22.43万辆，比上年增加 0.79万辆，同比增长3.64%",
    )
    assert decision.region_id == "UNKNOWN"
    assert decision.source == "unknown"


def test_county_scope_filter_preserves_an_explicit_other_county():
    decision = classify_claim_region(
        "安吉县",
        title="安吉县统计公报",
        url="https://example.com/roads",
        statement="天全县公路建设情况",
        quote="2024年末全县公路建设情况",
    )
    assert decision.region_id == "天全县"
    assert decision.source == "claim"
    assert decision.excluded_from_target


def test_generic_county_scope_does_not_block_other_region_fallback():
    decision = classify_claim_region(
        "安吉县",
        title="贵州省竹产业发展规划",
        url="https://guizhou.gov.cn/plan",
        statement="2023年全县竹产业总产值达到180.28亿元",
        quote="2023年全县竹产业总产值达到180.28亿元",
    )
    assert decision.region_id == "贵州省"
    assert decision.source == "document"
    assert decision.reason == "document_names_other_region"


def test_generic_county_scope_without_document_signal_stays_unknown():
    decision = classify_claim_region(
        "安吉县",
        title="竹产业观察",
        url="https://example.com/bamboo",
        statement="2023年全县竹产业总产值达到180.28亿元",
        quote="2023年全县竹产业总产值达到180.28亿元",
    )
    assert decision.region_id == "UNKNOWN"
    assert decision.source == "unknown"
    assert decision.reason == "no_region_signal"


def test_national_source_with_generic_county_scope_is_not_promoted():
    decision = classify_claim_region(
        "安吉县",
        title="【传统竹产业有了绿色新路径】-国家发展和改革委员会",
        url="https://ndrc.gov.cn/xwdt/ztzl/slwrzlzxd/202401/t20240108_1363146.html",
        statement="2022年全县竹产业总产值约166亿元",
        quote="2022年全县竹产业总产值约166亿元",
    )
    assert decision.region_id == "全国"
    assert decision.source == "document"
    assert decision.reason == "document_is_national"


def test_short_name_inside_company_name_is_not_promoted():
    decision = classify_claim_region(
        "安吉县",
        title="竹产业观察",
        url="https://example.com/bamboo",
        statement="安吉精铸公司2023年实现产值10亿元",
        quote="安吉精铸公司2023年实现产值10亿元",
    )
    assert decision.region_id == "UNKNOWN"
    assert decision.is_unknown


def test_county_scope_claim_is_attributed_to_county_in_ledger():
    doc = RawDoc(
        title="安吉县统计公报",
        url="https://anji.gov.cn/tjgb",
        snippet="2023年全县竹产业总产值达到180.28亿元。",
        content="2023年全县竹产业总产值达到180.28亿元。",
        domain_type="government",
        credibility_score=0.95,
    )
    ledger = build_evidence_ledger(_processed("安吉县", doc))
    claim = _claim_for(ledger, "180.28")
    assert claim.region_id == "安吉县"
    assert claim.region_source in {"claim", "document"}
