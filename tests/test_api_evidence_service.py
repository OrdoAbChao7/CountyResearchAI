from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from county_research_ai.api.brief import render_decision_brief
from county_research_ai.api.evidence_service import (
    persist_run_evidence,
    thresholds_met,
)
from county_research_ai.domain.outcomes import ResearchOutcome
from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    QuestionSlot,
    ResearchContract,
    SourceDocument,
)
from county_research_ai.evidence.graph import EvidenceGraphStore
from county_research_ai.evidence.ledger import EvidenceLedger

CONTENT = "德清县2024年地区生产总值为722.5亿元，同比增长5.8%。"


def _ledger() -> EvidenceLedger:
    ledger = EvidenceLedger()
    ledger.add_source(
        SourceDocument(
            doc_id="snap-1",
            title="德清县统计公报",
            url="https://dq.gov.cn/tjgb",
            content=CONTENT,
            content_hash=hashlib.sha256(CONTENT.encode()).hexdigest(),
            fetch_status="fetched",
            provider="fixture",
            source_type="government",
            retrieved_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            chunks=[
                EvidenceChunk(
                    chunk_id="snap-1:chunk:1",
                    source_id="snap-1",
                    text=CONTENT,
                    start_offset=0,
                    end_offset=len(CONTENT),
                    offset_status="exact",
                )
            ],
        )
    )
    ledger.add_claim(
        AtomicClaim(
            claim_id="claim-good",
            statement="德清县2024年地区生产总值为722.5亿元",
            region_id="德清县",
            metric_id="地区生产总值",
            value="722.5",
            unit="亿元",
            period="2024",
            administrative_scope="县域本级",
            source_ids=["snap-1"],
            evidence_chunk_ids=["snap-1:chunk:1"],
        )
    )
    ledger.add_claim(
        AtomicClaim(
            claim_id="claim-bad",
            statement="德清县2024年地区生产总值为700亿元",
            region_id="德清县",
            metric_id="地区生产总值",
            value="700",
            unit="亿元",
            period="2024",
            administrative_scope="县域本级",
            source_ids=["snap-1"],
            evidence_chunk_ids=["snap-1:chunk:1"],
        )
    )
    return ledger


def _slot() -> QuestionSlot:
    return QuestionSlot(
        slot_id="slot:gdp",
        research_question="2024年地区生产总值是多少？",
        required_metrics=["地区生产总值"],
        budget_chars=2000,
    )


def test_persist_run_evidence_links_findings_to_verified_claims(tmp_path):
    ledger = _ledger()
    pack = ledger.select_evidence_pack(_slot())
    graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")

    summary = persist_run_evidence(graph, ledger, [pack], run_id="run-1")

    assert summary["claims"] == 2
    assert summary["supported_claims"] == 1
    assert summary["status_counts"] == {"INSUFFICIENT": 1, "SUPPORTED": 1}
    findings = graph.list_findings("run-1")
    by_id = {item.chain.claim.claim_id: item for item in findings}
    assert by_id["claim-good"].finding.status.value == "SUPPORTED"
    assert by_id["claim-good"].chain.links[0].span.quote == CONTENT
    assert by_id["claim-bad"].finding.status.value == "INSUFFICIENT"
    assert graph.list_run_snapshots("run-1")[0].snapshot_id == "snap-1"


def test_claims_outside_requested_window_are_not_comparable(tmp_path):
    ledger = _ledger()
    ledger.add_claim(
        AtomicClaim(
            claim_id="claim-2027",
            statement="到2027年实现产值200亿元",
            region_id="德清县",
            metric_id="地区生产总值",
            value="200",
            unit="亿元",
            period="2027",
            administrative_scope="县域本级",
            source_ids=["snap-1"],
            evidence_chunk_ids=["snap-1:chunk:1"],
        )
    )
    pack = ledger.select_evidence_pack(_slot())
    graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")
    contract = ResearchContract(
        objective="2024 年评估",
        regions=["德清县"],
        date_window={"start": "2024-01-01", "end": "2024-12-31"},
    )

    persist_run_evidence(graph, ledger, [pack], run_id="run-1", contract=contract)

    findings = {
        item.chain.claim.claim_id: item for item in graph.list_findings("run-1")
    }
    assert findings["claim-good"].finding.status.value == "SUPPORTED"
    assert findings["claim-2027"].finding.status.value == "NOT_COMPARABLE"
    assert findings["claim-2027"].chain.verification is not None
    assert findings["claim-2027"].chain.verification.deterministic_checks[
        "requested_window"
    ] == ["2024-01-01", "2024-12-31"]


def test_thresholds_report_exact_failures():
    contract = ResearchContract(
        objective="测试",
        regions=["德清县"],
        evidence_thresholds={
            "min_independent_sources": 2,
            "min_supported_claims": 3,
            "min_supported_ratio": 0.8,
        },
    )
    summary = {
        "independent_sources": 1,
        "supported_claims": 1,
        "supported_ratio": 0.5,
    }

    met, failures = thresholds_met(contract, summary)

    assert met is False
    assert failures == [
        "min_independent_sources:1<2",
        "min_supported_claims:1<3",
        "min_supported_ratio:0.5<0.8",
    ]


def test_brief_sections_and_withholding(tmp_path):
    ledger = _ledger()
    pack = ledger.select_evidence_pack(_slot())
    graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")
    persist_run_evidence(graph, ledger, [pack], run_id="run-1")

    markdown = render_decision_brief(
        job_id="run-1",
        contract=ResearchContract(objective="德清县经济评估", regions=["德清县"]),
        outcome=ResearchOutcome.NEEDS_HUMAN_REVIEW,
        outcome_reason="min_supported_ratio:0.5<0.8",
        mode_label="MOCK",
        findings=graph.list_findings("run-1"),
        sources=graph.list_run_snapshots("run-1"),
    )

    assert "# 德清县经济评估 — 决策简报" in markdown
    assert "已支持结论（1）" in markdown
    assert "`claim-good`" in markdown
    assert "https://dq.gov.cn/tjgb" in markdown
    assert "MOCK" in markdown
    assert "已隐去的无支持结论（1）" in markdown
    assert "德清县2024年地区生产总值为700亿元" not in markdown
    assert "不是语义蕴含证明" in markdown


def test_claim_selected_by_two_slots_keeps_one_finding_and_both_links(tmp_path):
    ledger = _ledger()
    graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")
    slots = [
        QuestionSlot(
            slot_id=f"contract:{index}",
            research_question="2024年地区生产总值是多少？",
            required_metrics=["地区生产总值"],
            budget_chars=2000,
        )
        for index in range(2)
    ]
    packs = [ledger.select_evidence_pack(slot) for slot in slots]

    persist_run_evidence(graph, ledger, packs, run_id="run-1")

    findings = graph.list_findings("run-1")
    good = [item for item in findings if item.finding.claim_id == "claim-good"]
    assert len(good) == 1
    assert set(good[0].finding.slot_ids) == {"contract:0", "contract:1"}

