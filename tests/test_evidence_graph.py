from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

import pytest

from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    SourceDocument,
)
from county_research_ai.evidence.graph import (
    ClaimRelationKind,
    EdgeRelation,
    EvidenceGraphStore,
    FindingRecord,
    VerificationStatus,
    classify_claim_relation,
)
from county_research_ai.evidence.ledger import EvidenceLedger

CONTENT = "德清县2024年地区生产总值为722.5亿元，同比增长5.8%。"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source(
    doc_id: str,
    *,
    content: str = CONTENT,
    url: str = "https://example.gov.cn/1",
    retrieved_at: datetime | None = None,
    content_hash: str | None = None,
    start: int = 0,
    end: int | None = None,
) -> SourceDocument:
    end_offset = end if end is not None else start + len(content)
    return SourceDocument(
        doc_id=doc_id,
        title=f"德清县统计公报 {doc_id}",
        url=url,
        content=content,
        content_hash=content_hash if content_hash is not None else _hash(content),
        fetch_status="fetched",
        provider="fixture",
        source_type="government",
        retrieved_at=retrieved_at or datetime(2024, 6, 1, tzinfo=timezone.utc),
        chunks=[
            EvidenceChunk(
                chunk_id=f"{doc_id}:chunk:1",
                source_id=doc_id,
                text=content,
                start_offset=start,
                end_offset=end_offset,
                offset_status="exact",
                content_hash=_hash(content),
            )
        ],
    )


def _claim(
    claim_id: str,
    *,
    source_id: str = "snap-1",
    chunk_id: str = "snap-1:chunk:1",
    value: str = "722.5",
    unit: str = "亿元",
    period: str = "2024",
    scope: str = "县域本级",
    caliber: str = "",
    version: str = "",
    metric: str = "地区生产总值",
    statement: str = "德清县2024年地区生产总值为722.5亿元",
) -> AtomicClaim:
    return AtomicClaim(
        claim_id=claim_id,
        statement=statement,
        region_id="德清县",
        metric_id=metric,
        value=value,
        unit=unit,
        period=period,
        administrative_scope=scope,
        statistical_caliber=caliber,
        series_version=version,
        source_ids=[source_id],
        evidence_chunk_ids=[chunk_id],
    )


def _ledger(*sources: SourceDocument, claims: list[AtomicClaim] | None = None) -> EvidenceLedger:
    ledger = EvidenceLedger()
    for source in sources:
        ledger.add_source(source)
    for claim in claims or []:
        ledger.add_claim(claim)
    return ledger


def test_round_trip_preserves_sources_chunks_and_claims(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    source = _source("snap-1")
    claim = _claim("claim-1")
    store.save_ledger(_ledger(source, claims=[claim]))

    reloaded = EvidenceGraphStore(tmp_path / "graph.sqlite").load_ledger()

    assert reloaded.sources["snap-1"] == source
    assert reloaded.chunks["snap-1:chunk:1"].text == CONTENT
    restored = reloaded.claims["claim-1"]
    assert restored.statement == claim.statement
    assert restored.evidence_chunk_ids == ["snap-1:chunk:1"]
    assert restored.verification_status == "supported"


def test_chain_navigates_claim_span_and_snapshot(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(_source("snap-1"), claims=[_claim("claim-1")]))

    chain = store.get_chain("claim-1")
    link = chain.links[0]

    assert link.edge.relation is EdgeRelation.CONTEXT
    assert link.span.quote == CONTENT
    assert link.span.start_offset == 0
    assert link.span.end_offset == len(CONTENT)
    assert link.snapshot.content[link.span.start_offset : link.span.end_offset] == CONTENT
    assert link.snapshot.canonical_url == "https://example.gov.cn/1"


def test_supported_claim_requires_value_in_quote(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(
        _ledger(
            _source("snap-1"),
            claims=[
                _claim("claim-good", value="722.5"),
                _claim(
                    "claim-bad",
                    value="700",
                    statement="德清县2024年地区生产总值为700亿元",
                ),
            ],
        )
    )

    good = store.verify_claim("claim-good")
    bad = store.verify_claim("claim-bad")

    assert good.status is VerificationStatus.SUPPORTED
    assert good.deterministic_checks["value_present"] is True
    assert good.deterministic_checks["independent_support"] == 1
    assert bad.status is VerificationStatus.INSUFFICIENT
    assert bad.deterministic_checks["value_present"] is False


def test_false_offset_reference_is_rejected(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(
        _ledger(_source("snap-1", start=1, end=len(CONTENT)), claims=[_claim("claim-1")])
    )

    record = store.verify_claim("claim-1")
    issues = store.integrity_report()

    assert record.status is VerificationStatus.INSUFFICIENT
    assert record.deterministic_checks["span_integrity_failures"] == [
        "snap-1:chunk:1:offset_quote_mismatch"
    ]
    assert [issue.issue for issue in issues] == ["offset_quote_mismatch"]


def test_snapshot_hash_mismatch_blocks_support(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(
        _ledger(
            _source("snap-1", content_hash="0" * 64),
            claims=[_claim("claim-1")],
        )
    )

    record = store.verify_claim("claim-1")

    assert record.status is VerificationStatus.INSUFFICIENT
    assert record.deterministic_checks["span_integrity_failures"] == [
        "snap-1:chunk:1:snapshot_hash_mismatch"
    ]


def test_append_only_snapshot_rejects_changed_content(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(_source("snap-1")))

    conflicting = _source("snap-1", content="完全不同的正文 1234")
    with pytest.raises(ValueError, match="snapshot id collision"):
        store.save_ledger(_ledger(conflicting))


def test_baseless_contradiction_does_not_override_supported_claim(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(
        _ledger(
            _source("snap-1"),
            claims=[
                _claim("claim-good"),
                _claim(
                    "claim-bad",
                    value="700",
                    statement="德清县2024年地区生产总值为700亿元",
                ),
            ],
        )
    )

    good = store.verify_claim("claim-good")

    assert good.status is VerificationStatus.SUPPORTED
    assert good.deterministic_checks["contradicting_supported_claims"] == []


def test_two_supported_conflicting_claims_need_review(tmp_path):
    content_a = "德清县2024年地区生产总值为722.5亿元。"
    content_b = "德清县2024年地区生产总值为700亿元。"
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(
        _ledger(
            _source("snap-a", content=content_a, url="https://a.gov.cn/1"),
            _source("snap-b", content=content_b, url="https://b.gov.cn/1"),
            claims=[
                _claim(
                    "claim-a",
                    source_id="snap-a",
                    chunk_id="snap-a:chunk:1",
                    value="722.5",
                    statement="德清县2024年地区生产总值为722.5亿元",
                ),
                _claim(
                    "claim-b",
                    source_id="snap-b",
                    chunk_id="snap-b:chunk:1",
                    value="700",
                    statement="德清县2024年地区生产总值为700亿元",
                ),
            ],
        )
    )

    record_a = store.verify_claim("claim-a")
    record_b = store.verify_claim("claim-b")
    relations = store.relations_for("claim-a")

    assert record_a.status is VerificationStatus.NEEDS_REVIEW
    assert record_a.deterministic_checks["contradicting_supported_claims"] == ["claim-b"]
    assert record_b.status is VerificationStatus.NEEDS_REVIEW
    assert any(
        relation.relation is ClaimRelationKind.CONTRADICTS for relation in relations
    )


def test_newer_series_version_supersedes_older(tmp_path):
    old = _source(
        "snap-old", url="https://old.gov.cn", retrieved_at=datetime(2023, 6, 1, tzinfo=timezone.utc)
    )
    new = _source(
        "snap-new", url="https://new.gov.cn", retrieved_at=datetime(2024, 6, 1, tzinfo=timezone.utc)
    )
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(
        _ledger(
            old,
            new,
            claims=[
                _claim(
                    "claim-old",
                    source_id="snap-old",
                    chunk_id="snap-old:chunk:1",
                    version="v1",
                ),
                _claim(
                    "claim-new",
                    source_id="snap-new",
                    chunk_id="snap-new:chunk:1",
                    version="v2",
                ),
            ],
        )
    )

    assert store.get_chain("claim-old").verification.status is VerificationStatus.OUTDATED
    assert store.get_chain("claim-new").verification.status is VerificationStatus.SUPPORTED
    supersedes = [
        relation
        for relation in store.relations_for("claim-old")
        if relation.relation is ClaimRelationKind.SUPERSEDES
    ]
    assert supersedes[0].from_claim_id == "claim-new"


@pytest.mark.parametrize(
    ("left_kwargs", "right_kwargs", "expected"),
    [
        ({"value": "722.5", "unit": "亿元"}, {"value": "7225000", "unit": "万元"}, ClaimRelationKind.SAME_FACT),
        ({"value": "722.5"}, {"value": "700"}, ClaimRelationKind.CONTRADICTS),
        ({"period": "2024"}, {"period": "2023"}, ClaimRelationKind.NOT_COMPARABLE),
        ({"scope": "县域本级"}, {"scope": "全国范围"}, ClaimRelationKind.NOT_COMPARABLE),
        ({"caliber": "现价"}, {"caliber": "不变价"}, ClaimRelationKind.NOT_COMPARABLE),
        ({"unit": "亿元"}, {"unit": "%"}, ClaimRelationKind.NOT_COMPARABLE),
    ],
)
def test_claim_relation_classification(left_kwargs, right_kwargs, expected):
    left = _claim("left", **left_kwargs)
    right = _claim("right", **right_kwargs)

    relation = classify_claim_relation(left, right)

    assert relation is not None
    assert relation.relation is expected


def test_different_metric_is_not_related():
    left = _claim("left", metric="地区生产总值")
    right = _claim("right", metric="规上工业增加值")

    assert classify_claim_relation(left, right) is None


def test_requested_window_excludes_out_of_period_and_missing_period(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    window = (date(2024, 1, 1), date(2024, 12, 31))
    store.save_ledger(
        _ledger(
            _source("snap-1"),
            claims=[
                _claim("claim-2027", period="2027"),
                _claim("claim-nodate", period=""),
            ],
        ),
        window=window,
    )

    out_of_period = store.verify_claim("claim-2027", window=window)
    missing_period = store.verify_claim("claim-nodate", window=window)

    assert out_of_period.status is VerificationStatus.NOT_COMPARABLE
    assert out_of_period.deterministic_checks["requested_window"] == [
        "2024-01-01",
        "2024-12-31",
    ]
    assert missing_period.status is VerificationStatus.NOT_COMPARABLE
    assert store.get_claim("claim-2027").verification_reason == (
        "outside_requested_window:2027"
    )


def test_numeric_claim_without_unit_is_not_comparable(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(
        _ledger(_source("snap-1"), claims=[_claim("claim-1", unit="")])
    )

    record = store.verify_claim("claim-1")

    assert record.status is VerificationStatus.NOT_COMPARABLE
    assert record.deterministic_checks["value_present"] is True


def test_findings_persist_with_full_chain(tmp_path):
    path = tmp_path / "graph.sqlite"
    store = EvidenceGraphStore(path)
    store.save_ledger(_ledger(_source("snap-1"), claims=[_claim("claim-1")]))
    store.save_findings(
        "run-1",
        [
            FindingRecord(
                finding_id="finding-1",
                run_id="run-1",
                claim_id="claim-1",
                section="经济概况",
                text="2024年地区生产总值722.5亿元",
                status=VerificationStatus.SUPPORTED,
            )
        ],
    )

    reopened = EvidenceGraphStore(path)
    findings = reopened.list_findings("run-1")

    assert len(findings) == 1
    assert findings[0].finding.section == "经济概况"
    assert findings[0].chain.claim.claim_id == "claim-1"
    assert findings[0].chain.links[0].span.quote == CONTENT
    assert reopened.list_claims(run_id="run-1")[0].claim_id == "claim-1"
