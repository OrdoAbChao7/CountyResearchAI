from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from county_research_ai.application.verified_answer import build_verified_answer
from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    SourceDocument,
)
from county_research_ai.evidence.graph import EvidenceGraphStore
from county_research_ai.evidence.ledger import EvidenceLedger

CONTENT = (
    "德清县2024年第一产业增加值31.4亿元，同比增长3.8%；"
    "第二产业增加值378.1亿元，同比增长7.1%。"
)


def _source() -> SourceDocument:
    return SourceDocument(
        doc_id="snap-1",
        title="德清县统计公报",
        url="https://dq.gov.cn/1",
        content=CONTENT,
        content_hash=hashlib.sha256(CONTENT.encode()).hexdigest(),
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


def _claim(claim_id: str, *, measure: str, value: str, statement: str) -> AtomicClaim:
    return AtomicClaim(
        claim_id=claim_id,
        statement=statement,
        region_id="德清县",
        metric_id="产值与收入",
        measure_id=measure,
        value=value,
        unit="亿元",
        period="2024",
        administrative_scope="县域本级",
        statistical_caliber="产值与收入",
        source_ids=["snap-1"],
        evidence_chunk_ids=["snap-1:chunk:1"],
    )


def test_verified_answer_contains_each_supported_measure(tmp_path):
    ledger = EvidenceLedger()
    ledger.add_source(_source())
    ledger.add_claim(
        _claim(
            "claim-primary",
            measure="第一产业增加值",
            value="31.4",
            statement="第一产业增加值31.4亿元",
        )
    )
    ledger.add_claim(
        _claim(
            "claim-secondary",
            measure="第二产业增加值",
            value="378.1",
            statement="第二产业增加值378.1亿元",
        )
    )
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(ledger, run_id="run-1")

    answer = build_verified_answer(store, "run-1")

    assert answer["supported_count"] == 2
    assert "第一产业增加值" in answer["text"]
    assert "第二产业增加值" in answer["text"]
    assert "31.4" in answer["text"]
    assert "378.1" in answer["text"]
    assert "https://dq.gov.cn/1" in answer["text"]
    assert answer["status_counts"] == {"SUPPORTED": 2}


def test_verified_answer_excludes_unsupported_claims(tmp_path):
    ledger = EvidenceLedger()
    ledger.add_source(_source())
    ledger.add_claim(
        _claim(
            "claim-bad",
            measure="第一产业增加值",
            value="999",
            statement="第一产业增加值999亿元",
        )
    )
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(ledger, run_id="run-1")

    answer = build_verified_answer(store, "run-1")

    assert answer["supported_count"] == 0
    assert "999" not in answer["text"]
    assert "没有通过确定性校验" in answer["text"]
