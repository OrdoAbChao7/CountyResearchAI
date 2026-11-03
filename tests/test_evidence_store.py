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


def test_fact_verifier_single_digit_and_unit_mismatch():
    from county_research_ai.models import EvidenceItem

    store = EvidenceStore()
    store.add_evidence(
        EvidenceItem(
            id="e1",
            claim="安吉县竹林开采量为5万吨",
            snippet="开采量为5万吨",
            url="https://anji.gov.cn/tjgb",
            title="统计公报",
            credibility_score=0.95,
            topic="economic",
        )
    )
    store.add_evidence(
        EvidenceItem(
            id="e2",
            claim="全县下辖10个乡镇街道",
            snippet="全县下辖10个乡镇街道",
            url="https://anji.gov.cn/intro",
            title="县情介绍",
            credibility_score=0.9,
            topic="economic",
        )
    )
    store.add_evidence(
        EvidenceItem(
            id="e3",
            claim="出台政策规划文件《加快“以竹代塑”发展三年行动计划》",
            snippet="通知出台",
            url="https://ndrc.gov.cn/doc",
            title="发改委通知",
            credibility_score=0.95,
            topic="policy",
        )
    )
    verifier = FactVerifier(store)

    # 1. 单数字统计正确核验（不能因长度为 1 而漏判）
    out1, rep1 = verifier.verify_text_content("全县竹林年开采量达到5万吨", "安吉县")
    assert rep1.verified_claims_count == 1
    assert rep1.unverified_claims_count == 0
    assert "官方/权威验证" in out1

    # 2. 统计单位不匹配时不能误判核验（10亿元 不能被 10个乡镇街道 错误支持）
    out2, rep2 = verifier.verify_text_content("产业年产值达到10亿元", "安吉县")
    assert rep2.verified_claims_count == 0
    assert rep2.unverified_claims_count == 1
    assert "该数值需官方统计公报进一步核实" in out2

    # 3. 政策文件正确核验
    out3, rep3 = verifier.verify_text_content("贯彻落实《加快“以竹代塑”发展三年行动计划》", "安吉县")
    assert rep3.verified_claims_count == 1
    assert "官方/权威验证" in out3


def test_evidence_store_macro_gdp_and_cross_caliber_conflicts():
    store = EvidenceStore()
    doc1 = RawDoc(
        title="2023年统计公报",
        url="https://anji.gov.cn/tjgb",
        snippet="实现地区生产总值350亿元，规上工业产值120亿元，常住人口达到58万人。",
        content="2023年全县地区生产总值350亿元，规上工业产值120亿元，常住人口58万人。",
        domain_type="government",
        credibility_score=0.95,
    )
    doc2 = RawDoc(
        title="产业专班报道",
        url="https://news.example.com/bamboo",
        snippet="竹产业全产业链总产值突破280亿元。",
        content="竹产业全产业链总产值突破280亿元。",
        domain_type="news",
        credibility_score=0.85,
    )
    items = store.ingest_documents([doc1, doc2], county="安吉县", focus="竹产业")
    calibers = {it.indicator_caliber for it in items}
    assert any("宏观GDP" in c for c in calibers)
    assert any("人口" in c for c in calibers)

    # 检查口径冲突发现（规上工业产值 120亿 vs 全产业链总产值 280亿）
    conflicts = store.detect_conflicts()
    assert len(conflicts) >= 1
    c = conflicts[0]
    assert c.conflict_type in {"caliber_discrepancy", "year_discrepancy"}
    assert "产值" in c.indicator

