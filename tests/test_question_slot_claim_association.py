"""One global Claim may serve several contract questions without becoming a fact for any."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from county_research_ai.api.contract_coverage import assess_contract_coverage
from county_research_ai.api.evidence_service import load_run_evidence, persist_run_evidence
from county_research_ai.api.jobs import JobRecord, JobStatus
from county_research_ai.api.projections.questions import contract_question_lines
from county_research_ai.domain.company_names import company_names
from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    ResearchContract,
    SourceDocument,
)
from county_research_ai.evidence.graph import EvidenceGraphStore
from county_research_ai.evidence.ledger import EvidenceLedger
from county_research_ai.search.query_engine import QueryEngine

TOTAL_QUESTION = "2024 年安吉县竹产业总产值是多少？"
ENTERPRISE_QUESTION = "安吉县有哪些竹产业龙头企业？"

SHARED_TEXT = "2024年安吉县竹产业总产值达到280亿元。浙江省湖州市安吉县梅溪镇峰晖竹木制品有限公司的生产车间里，数控机器开足马力。"
CASE_TEXTS = {
    "fengxu": "浙江省湖州市安吉县梅溪镇峰晖竹木制品有限公司的生产车间里，数控机器开足马力，竹制品订单充足，这是公开报道的经营场景。",
    "mingzhu": "竹产业绿色转型在安吉比比皆是：安吉鸣竹竹业科技有限公司通过数字化改革完成设备集约化升级，竹制品生产线用电量明显下降。",
    "shange": "安吉竹产业园里，浙江山哥新材料科技有限公司负责人聂忠平介绍，公司与研究院合作研发的竹筷刀叉勺设备已经正式投产。",
    "other": "无锡市博大竹木业有限公司出现在农业产业化国家重点龙头企业名单的附件之中，该名单为全国性公告，附件按省份排序登载。",
}


def _source(doc_id: str, text: str, *, score: float = 0.9) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=f"资料 {doc_id}",
        url=f"https://example.gov.cn/{doc_id}",
        content=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        fetch_status="fetched",
        provider="fixture",
        source_type="government",
        retrieved_at=datetime(2026, 11, 23, tzinfo=timezone.utc),
        metadata={"credibility_score": score},
        chunks=[EvidenceChunk(
            chunk_id=f"{doc_id}:chunk:1", source_id=doc_id, text=text,
            start_offset=0, end_offset=len(text), offset_status="exact",
            year_hints=["2024"] if doc_id == "shared" else [],
        )],
    )


def _claim(claim_id: str, statement: str, doc_id: str, *, region: str, period: str = "", **extra) -> AtomicClaim:
    return AtomicClaim(
        claim_id=claim_id, statement=statement, region_id=region, period=period,
        source_ids=[doc_id], evidence_chunk_ids=[f"{doc_id}:chunk:1"], **extra,
    )


def _ledger() -> EvidenceLedger:
    ledger = EvidenceLedger()
    ledger.add_source(_source("shared", SHARED_TEXT))
    for doc_id, text in CASE_TEXTS.items():
        ledger.add_source(_source(doc_id, text))
    ledger.add_claim(_claim(
        "shared-total", "2024年安吉县竹产业总产值达到280亿元", "shared", region="安吉县", period="2024",
        metric_id="产值与收入", value="280", unit="亿元", administrative_scope="县域本级",
    ))
    ledger.add_claim(_claim(
        "shared-fengxu", "浙江省湖州市安吉县梅溪镇峰晖竹木制品有限公司的生产车间里", "shared",
        region="安吉县", metric_id="骨干企业",
    ))
    ledger.add_claim(_claim(
        "case-fengxu", "浙江省湖州市安吉县梅溪镇峰晖竹木制品有限公司的生产车间里", "fengxu",
        region="安吉县", metric_id="骨干企业",
    ))
    ledger.add_claim(_claim(
        "case-mingzhu", "安吉鸣竹竹业科技有限公司通过数字化改革完成设备集约化升级", "mingzhu",
        region="全国", metric_id="骨干企业",
    ))
    ledger.add_claim(_claim(
        "case-shange", "浙江山哥新材料科技有限公司负责人聂忠平介绍", "shange",
        region="UNKNOWN", metric_id="骨干企业",
    ))
    ledger.add_claim(_claim(
        "case-other", "无锡市博大竹木业有限公司", "other", region="无锡市", metric_id="骨干企业",
    ))
    return ledger


def _contract() -> ResearchContract:
    return ResearchContract(
        objective="核验 2024 年竹产业总产值与龙头企业",
        regions=["安吉县"],
        research_focus="竹产业",
        date_window={"start": "2024-01-01", "end": "2024-12-31"},
        required_questions=[TOTAL_QUESTION, ENTERPRISE_QUESTION],
    )


def _persist(tmp_path, run_id: str = "run-1", graph: EvidenceGraphStore | None = None):
    ledger = _ledger()
    contract = _contract()
    slots = contract.to_research_spec().question_slots
    packs = [ledger.select_evidence_pack(slot) for slot in slots]
    graph = graph or EvidenceGraphStore(tmp_path / "evidence.sqlite")
    summary = persist_run_evidence(graph, ledger, packs, run_id=run_id, contract=contract)
    return graph, ledger, packs, summary, contract


def test_claim_selected_by_two_questions_keeps_both_slot_links(tmp_path):
    graph, _, packs, _, _ = _persist(tmp_path)

    shared_ids = set.intersection(*({claim.claim_id for claim in pack.selected_claims} for pack in packs))
    assert shared_ids, "fixture must select one Claim for both questions"
    findings = graph.list_findings("run-1")
    by_claim = {item.finding.claim_id: item for item in findings}
    assert len(by_claim) == len(findings), "a Claim is stored once per run, never once per question"
    for claim_id in shared_ids:
        assert by_claim[claim_id].finding.slot_ids == ["contract:0", "contract:1"]
    only_first = {c.claim_id for c in packs[0].selected_claims} - {c.claim_id for c in packs[1].selected_claims}
    for claim_id in only_first:
        assert by_claim[claim_id].finding.slot_ids == ["contract:0"]


def test_questions_select_their_own_evidence_on_their_own_terms(tmp_path):
    _, _, packs, _, _ = _persist(tmp_path)

    total_chunks = {chunk.chunk_id for chunk in packs[0].selected_chunks}
    enterprise_chunks = {chunk.chunk_id for chunk in packs[1].selected_chunks}
    assert "fengxu:chunk:1" in enterprise_chunks and "fengxu:chunk:1" not in total_chunks
    assert total_chunks < enterprise_chunks, "the enterprise pack adds company chunks to the shared one"
    assert packs[1].selected_evidence_reasons["fengxu:chunk:1"] == "named_company"
    assert not any("named_company" in reason for reason in packs[0].selected_evidence_reasons.values())
    # Selection is relevance only: no company chunk is promoted to a qualification answer.
    assert not any("contract_answer_candidate" in r for r in packs[1].selected_evidence_reasons.values())
    assert "case-other" not in {c.claim_id for pack in packs for c in pack.selected_claims}


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("在浙江省湖州市安吉县梅溪镇峰晖竹木制品有限公司的生产车间", ["峰晖竹木制品有限公司"]),
        ("走进位于梅溪镇的浙江峰晖竹木制品有限公司大厅", ["浙江峰晖竹木制品有限公司"]),
        ("农户的林权全部流转到安吉县两山生态资源资产经营有限公司", ["安吉县两山生态资源资产经营有限公司"]),
        ("林权全部流转到安吉县两山生态资源资产经营有限公司", ["安吉县两山生态资源资产经营有限公司"]),
        ("安吉鸣竹竹业科技有限公司通过数字化改革完成设备集约化升级", ["安吉鸣竹竹业科技有限公司"]),
        ("该公司没有任何注册名称", []),
    ],
)
def test_company_names_drop_leading_text_but_keep_the_registered_name(statement, expected):
    assert company_names(statement) == expected


def test_global_claim_rows_are_not_duplicated_by_second_question(tmp_path):
    graph, ledger, _, _, _ = _persist(tmp_path)

    with graph._connect() as connection:
        claims = connection.execute("SELECT COUNT(*) FROM run_claims WHERE run_id='run-1'").fetchone()[0]
        duplicated = connection.execute(
            "SELECT COUNT(*) FROM (SELECT claim_id FROM findings WHERE run_id='run-1'"
            " GROUP BY claim_id HAVING COUNT(*) > 1)"
        ).fetchone()[0]
    assert claims == len(ledger.claims)
    assert duplicated == 0


def test_each_question_is_assessed_independently(tmp_path):
    _, _, _, summary, _ = _persist(tmp_path)

    total, enterprise = summary["contract_questions"]
    assert (total["question_id"], enterprise["question_id"]) == ("contract:0", "contract:1")
    # The shared total-output Claim answers its own question and nothing else.
    assert total["status"] == "SUPPORTED" and total["claim_ids"] == ["shared-total"]
    assert enterprise["status"] == "INSUFFICIENT" and enterprise["claim_ids"] == []
    # The enterprise question evaluates the shared Claims against its own qualification target.
    shared = {item["claim_id"]: item for item in enterprise["candidates"]}
    assert shared["shared-total"]["status"] == "REJECTED"
    assert shared["shared-total"]["reason"] == "different_metric_or_qualification"
    assert summary["contract_evidence"]["supported_claims"] == 1


def test_enterprise_question_lists_named_leads_without_granting_qualification(tmp_path):
    _, _, _, summary, _ = _persist(tmp_path)

    total, enterprise = summary["contract_questions"]
    assert total["enterprise_leads"] == []
    leads = {lead["name"]: lead for lead in enterprise["enterprise_leads"]}
    names = " ".join(leads)
    for expected in ("峰晖竹木制品有限公司", "鸣竹竹业科技有限公司", "山哥新材料科技有限公司"):
        assert expected in names
    assert "博大竹木业" not in names, "an explicit other-region company is not an Anji lead"
    for lead in leads.values():
        assert lead["qualification_status"] == "insufficient_qualification_evidence"
        assert lead["tier"] in {"named_lead", "operating_activity"}
        assert lead["cases"]
    fengxu = next(lead for name, lead in leads.items() if "峰晖" in name)
    assert fengxu["tier"] == "operating_activity"
    assert {case["claim_id"] for case in fengxu["cases"]} == {"shared-fengxu", "case-fengxu"}
    assert all(case["snapshot_id"] and case["span_id"] for case in fengxu["cases"])
    assert enterprise["status"] == "INSUFFICIENT" and enterprise["claim_ids"] == []
    mingzhu = next(lead for name, lead in leads.items() if "鸣竹" in name)
    assert mingzhu["region_status"] == "unconfirmed"
    assert fengxu["region_status"] == "confirmed"


def test_enterprise_leads_survive_into_the_report_lines(tmp_path):
    graph, _, _, _, contract = _persist(tmp_path)
    now = datetime(2026, 11, 23, tzinfo=timezone.utc)
    job = JobRecord(
        job_id="run-1", status=JobStatus.SUCCEEDED, contract=contract, created_at=now, updated_at=now,
    )
    questions = load_run_evidence(graph, job).coverage.questions

    text = "\n".join(contract_question_lines(questions))
    for name in ("峰晖", "鸣竹", "山哥"):
        assert name in text
    assert "龙头资格证据不足" in text
    assert "经营活动" in text
    assert "博大竹木业" not in text


def test_leads_are_recomputed_from_the_requested_run_only(tmp_path):
    graph, ledger, packs, _, contract = _persist(tmp_path)
    other = EvidenceLedger()
    other.add_source(_source("shared", SHARED_TEXT))
    other.add_claim(_claim(
        "shared-total", "2024年安吉县竹产业总产值达到280亿元", "shared", region="安吉县", period="2024",
        metric_id="产值与收入", value="280", unit="亿元", administrative_scope="县域本级",
    ))
    slots = contract.to_research_spec().question_slots
    persist_run_evidence(
        graph, other, [other.select_evidence_pack(slot) for slot in slots], run_id="run-2", contract=contract,
    )

    first = assess_contract_coverage(contract, graph, graph.list_findings("run-1"), run_id="run-1")
    second = assess_contract_coverage(contract, graph, graph.list_findings("run-2"), run_id="run-2")
    assert first.questions[1].enterprise_leads
    assert second.questions[1].enterprise_leads == []
    assert {f.finding.claim_id for f in graph.list_findings("run-2")} == {"shared-total"}


def test_legacy_single_section_findings_still_map_to_their_slot(tmp_path):
    graph, _, _, _, _ = _persist(tmp_path)
    with graph._connect() as connection:
        connection.execute("DELETE FROM finding_slots")
    legacy = graph.list_findings("run-1")
    assert legacy and all(item.finding.slot_ids == [item.finding.section] for item in legacy)


def test_enterprise_and_total_questions_get_separate_retrieval_tasks():
    engine = QueryEngine()
    spec = _contract().to_research_spec()

    first = engine.generate_contract_queries(spec)
    supplemental = engine.generate_contract_queries(spec, supplemental=True)

    by_slot: dict[str, list[str]] = {}
    for query in first + supplemental:
        by_slot.setdefault(query.slot_id, []).append(query.query)
    assert set(by_slot) == {"contract:0", "contract:1"}
    assert all("龙头企业" not in text for text in by_slot["contract:0"])
    assert all("总产值" not in text for text in by_slot["contract:1"])
    enterprise = " ".join(by_slot["contract:1"])
    for needle in ("认定公布", "公示", "认定公告", "企业名录"):
        assert needle in enterprise
    assert len(set(by_slot["contract:1"])) == len(by_slot["contract:1"])
    ids = {(query.slot_id, query.gap_id) for query in supplemental}
    assert ids == {("contract:0", "gap:contract:0"), ("contract:1", "gap:contract:1")}
