"""证据库与事实核验测试。"""
from __future__ import annotations

from county_research_ai.evidence.store import EvidenceStore
from county_research_ai.evidence.verifier import FactVerifier
from county_research_ai.models import QuestionTree, RawDoc, ResearchQuestion


def test_evidence_store_extracts_numerical_facts():
    store = EvidenceStore()
    doc = RawDoc(
        title="2023年安吉县国民经济和社会发展统计公报",
        url="https://anji.gov.cn/tjgb2023",
        snippet="安吉县竹产业全产业链总产值突破280亿元，全县竹林面积稳定在101.1万亩。",
        content="2023年，全县规模以上工业产值实现较快增长，竹林面积达101.1万亩，全产业链产值超过280亿元。",
        domain_type="government",
        credibility_score=0.95,
    )
    items = store.ingest_documents([doc], county="安吉县", focus="竹产业")
    assert len(items) >= 2

    # 验证按主题分类与口径
    economic_items = store.get_by_topic("economic")
    assert len(economic_items) >= 2
    claims = " ".join(it.claim for it in economic_items)
    assert "280亿元" in claims or "280" in claims
    assert "101.1万亩" in claims or "101.1" in claims


def test_evidence_store_detects_conflicts_and_explains_reasons():
    store = EvidenceStore()
    doc1 = RawDoc(
        title="2022年安吉县统计公报",
        url="https://anji.gov.cn/tjgb2022",
        snippet="2022年安吉县竹产业总产值达250亿元。",
        domain_type="government",
        credibility_score=0.9,
    )
    doc2 = RawDoc(
        title="2023年安吉县统计公报",
        url="https://anji.gov.cn/tjgb2023",
        snippet="2023年安吉县竹产业总产值达280亿元。",
        domain_type="government",
        credibility_score=0.95,
    )
    store.ingest_documents([doc1, doc2], county="安吉县", focus="竹产业")
    conflicts = store.detect_conflicts()
    assert len(conflicts) >= 1
    c = conflicts[0]
    assert c.conflict_type == "year_discrepancy"
    assert "年份" in c.description or "增长" in c.description


def test_evidence_store_assesses_question_tree_coverage():
    store = EvidenceStore()
    doc = RawDoc(
        title="安吉县竹林面积统计",
        url="https://anji.gov.cn/stat",
        snippet="全县竹林面积达101万亩，竹产业总产值超280亿元。",
        domain_type="government",
        credibility_score=0.95,
    )
    store.ingest_documents([doc], county="安吉县")

    qtree = QuestionTree(
        county="安吉县",
        focus="竹产业",
        questions=[
            ResearchQuestion(
                id="q1",
                title="产业规模与产值",
                category="economic",
                required_indicators=["产值", "面积"],
            ),
            ResearchQuestion(
                id="q2",
                title="重点园区与招商",
                category="industry",
                required_indicators=["招商引资", "园区"],
            ),
        ],
    )
    coverage, gaps = store.assess_question_tree_coverage(qtree)
    assert coverage == 0.5  # 2 个问题中 1 个满足
    assert len(gaps) == 1
    assert gaps[0].question_id == "q2"


def test_fact_verifier_attaches_badges_and_uncertainty_notes():
    store = EvidenceStore()
    doc = RawDoc(
        title="安吉县统计局发布会",
        url="https://anji.gov.cn/news",
        snippet="安吉县竹产业总产值达到280亿元。",
        domain_type="government",
        credibility_score=0.95,
    )
    store.ingest_documents([doc], county="安吉县")

    verifier = FactVerifier(store)
    analysis_text = (
        "安吉县竹产业发展势头强劲，全县总产值达到280亿元。\n"
        "同时据某传闻，全县计划建设500个大型深加工园区。"
    )
    annotated, report = verifier.verify_text_content(analysis_text, county="安吉县")
    assert "官方/权威验证" in annotated
    assert "该数值需官方统计公报进一步核实" in annotated
    assert report.verified_claims_count >= 1
    assert report.unverified_claims_count >= 1
