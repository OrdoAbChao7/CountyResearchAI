"""Claim-level region attribution and cross-region isolation regressions."""
from __future__ import annotations

import hashlib

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
