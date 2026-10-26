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
    ClaimEvidenceEdgeRecord,
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
    title: str | None = None,
) -> SourceDocument:
    end_offset = end if end is not None else start + len(content)
    return SourceDocument(
        doc_id=doc_id,
        title=title or f"德清县统计公报 {doc_id}",
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


def test_value_prefix_does_not_match_a_larger_number(tmp_path):
    content = "德清县2024年地区生产总值为200亿元。"
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(
        _ledger(
            _source("snap-1", content=content),
            claims=[
                _claim(
                    "claim-20",
                    value="20",
                    statement="德清县2024年地区生产总值为20亿元",
                )
            ],
        )
    )

    record = store.verify_claim("claim-20")

    assert record.status is VerificationStatus.INSUFFICIENT
    assert record.deterministic_checks["value_present"] is False


def test_explicit_contradicting_edge_forces_review(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(_source("snap-1"), claims=[_claim("claim-1")]))
    store.add_edge(
        ClaimEvidenceEdgeRecord(
            claim_id="claim-1",
            span_id="snap-1:chunk:1",
            relation=EdgeRelation.CONTRADICTS,
            rationale="test_conflict",
        )
    )

    record = store.verify_claim("claim-1")

    assert record.status is VerificationStatus.NEEDS_REVIEW
    assert record.deterministic_checks["contradicting_edges"] == 1


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


def test_value_with_wrong_unit_is_not_supported(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(
        _ledger(
            _source("snap-1", content="德清县2024年常住人口为722.5万人。"),
            claims=[
                _claim(
                    "claim-unit",
                    value="722.5",
                    unit="亿元",
                    metric="",
                    statement="",
                )
            ],
        )
    )

    record = store.verify_claim("claim-unit")

    assert record.status is VerificationStatus.INSUFFICIENT
    assert record.deterministic_checks["value_present"] is False


def test_value_cannot_match_a_longer_number(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(
        _ledger(
            _source("snap-1", content="德清县2024年地区生产总值为7000亿元。"),
            claims=[
                _claim(
                    "claim-700",
                    value="700",
                    statement="德清县2024年地区生产总值为700亿元",
                )
            ],
        )
    )

    record = store.verify_claim("claim-700")

    assert record.status is VerificationStatus.INSUFFICIENT
    assert record.deterministic_checks["value_present"] is False


def test_wrong_region_in_quote_is_not_supported(tmp_path):
    source = _source(
        "snap-1",
        content="长兴县2024年地区生产总值为722.5亿元。",
        title="长兴县统计公报",
    )
    source = source.model_copy(update={"canonical_url": "https://cx.gov.cn/1"})
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(source, claims=[_claim("claim-1")]))

    record = store.verify_claim("claim-1")

    assert record.status is VerificationStatus.INSUFFICIENT
    assert record.deterministic_checks["region_present"] is False


def test_wrong_year_in_quote_is_not_supported(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(
        _ledger(
            _source("snap-1", content="德清县2023年地区生产总值为722.5亿元。"),
            claims=[_claim("claim-1")],
        )
    )

    record = store.verify_claim("claim-1")

    assert record.status is VerificationStatus.INSUFFICIENT
    assert record.deterministic_checks["period_present"] is False


def test_metric_and_value_from_different_spans_do_not_compose(tmp_path):
    text_a = "德清县2024年地区生产总值情况。"
    text_b = "安吉县2024年财政收入900亿元。"
    content = text_a + text_b
    source = SourceDocument(
        doc_id="snap-1",
        title="德清县资料",
        url="https://dq.gov.cn/1",
        content=content,
        content_hash=_hash(content),
        chunks=[
            EvidenceChunk(
                chunk_id="snap-1:chunk:1",
                source_id="snap-1",
                text=text_a,
                start_offset=0,
                end_offset=len(text_a),
                offset_status="exact",
                content_hash=_hash(text_a),
            ),
            EvidenceChunk(
                chunk_id="snap-1:chunk:2",
                source_id="snap-1",
                text=text_b,
                start_offset=len(text_a),
                end_offset=len(content),
                offset_status="exact",
                content_hash=_hash(text_b),
            ),
        ],
    )
    claim = _claim(
        "claim-split",
        value="900",
        statement="德清县2024年地区生产总值900亿元",
    ).model_copy(
        update={"evidence_chunk_ids": ["snap-1:chunk:1", "snap-1:chunk:2"]}
    )
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(source, claims=[claim]))

    record = store.verify_claim("claim-split")

    assert record.status is VerificationStatus.INSUFFICIENT
    assert record.deterministic_checks["value_present"] is True


def test_clear_run_removes_findings_and_run_sources(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(_source("snap-1"), claims=[_claim("claim-1")]), run_id="run-1")
    store.save_findings(
        "run-1",
        [
            FindingRecord(
                finding_id="run-1:claim-1",
                run_id="run-1",
                claim_id="claim-1",
                text="结论",
            )
        ],
    )

    store.clear_run("run-1")

    assert store.list_findings("run-1") == []
    assert store.list_run_snapshots("run-1") == []


def test_verification_is_scoped_to_the_run(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    ledger = _ledger(_source("snap-1"), claims=[_claim("claim-1")])
    store.save_ledger(
        ledger,
        run_id="run-2024",
        window=(date(2024, 1, 1), date(2024, 12, 31)),
    )
    store.save_ledger(
        ledger,
        run_id="run-2025",
        window=(date(2025, 1, 1), date(2025, 12, 31)),
    )
    store.save_findings(
        "run-2024",
        [
            FindingRecord(
                finding_id="run-2024:claim-1",
                run_id="run-2024",
                claim_id="claim-1",
                text="2024 结论",
                status=VerificationStatus.SUPPORTED,
            )
        ],
    )

    old_chain = store.get_chain("claim-1", run_id="run-2024")
    new_chain = store.get_chain("claim-1", run_id="run-2025")
    finding = store.list_findings("run-2024")[0]

    assert old_chain.verification.status is VerificationStatus.SUPPORTED
    assert old_chain.claim.verification_status == "supported"
    assert new_chain.verification.status is VerificationStatus.NOT_COMPARABLE
    assert finding.finding.status is VerificationStatus.SUPPORTED
    assert finding.chain.verification.status is VerificationStatus.SUPPORTED


def test_unsupported_superseder_does_not_mark_older_claim_outdated(tmp_path):
    old = _source(
        "snap-old",
        url="https://old.gov.cn",
        retrieved_at=datetime(2023, 6, 1, tzinfo=timezone.utc),
    )
    new = _source(
        "snap-new",
        url="https://new.gov.cn",
        retrieved_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
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
                    value="999",
                    statement="德清县2024年地区生产总值为999亿元",
                ),
            ],
        )
    )

    assert store.get_chain("claim-old").verification.status is VerificationStatus.SUPPORTED
    assert (
        store.get_chain("claim-new").verification.status
        is VerificationStatus.INSUFFICIENT
    )


def test_month_level_window_rejects_out_of_window_date(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    window = (date(2026, 10, 1), date(2026, 12, 31))
    claim = _claim("claim-month", period="2026-01-15")
    store.save_ledger(
        _ledger(_source("snap-1"), claims=[claim]),
        run_id="run-month",
        window=window,
    )

    record = store.verify_claim("claim-month", run_id="run-month", window=window)

    assert record.status is VerificationStatus.NOT_COMPARABLE
    assert store.get_claim("claim-month").verification_reason == (
        "outside_requested_window:2026-01-15"
    )


def test_old_claim_relations_schema_is_rebuilt_with_run_id(tmp_path):
    import sqlite3

    path = tmp_path / "graph.sqlite"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE claim_relations (
                from_claim_id TEXT NOT NULL,
                to_claim_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                PRIMARY KEY (from_claim_id, to_claim_id, relation)
            );
            INSERT INTO claim_relations
                (from_claim_id, to_claim_id, relation, rationale, created_at)
            VALUES ('a', 'b', 'related', 'old', 'now');
            """
        )
        connection.commit()
    finally:
        connection.close()

    store = EvidenceGraphStore(path)
    with store._connect() as reopened:
        columns = {
            row[1] for row in reopened.execute("PRAGMA table_info(claim_relations)")
        }
        row = reopened.execute("SELECT * FROM claim_relations").fetchone()

    assert "run_id" in columns
    assert row["run_id"] == ""
