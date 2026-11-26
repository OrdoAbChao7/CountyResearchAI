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
    VerificationRecord,
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


@pytest.mark.parametrize("new_series_version", ["", "revised"], ids=["conflict", "supersession"])
def test_weak_quote_cannot_override_credible_evidence(tmp_path, new_series_version):
    weak = _source(
        "snap-weak", content="德清县2024年地区生产总值为700亿元。", url="https://example.com/estimate",
        retrieved_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    ).model_copy(update={"metadata": {"credibility_score": 0.5}})
    strong = _source("snap-1").model_copy(update={"metadata": {"credibility_score": 0.9}})
    claim = _claim(
        "claim-weak", source_id="snap-weak", chunk_id="snap-weak:chunk:1", value="700",
        statement="德清县2024年地区生产总值为700亿元", version=new_series_version,
    )
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(strong, weak, claims=[_claim("claim-strong"), claim]), run_id="run")

    current = store.get_chain("claim-strong", run_id="run").verification
    assert current.status is VerificationStatus.SUPPORTED
    assert not current.deterministic_checks["contradicting_supported_claims"]
    assert store.verify_claim("claim-strong", run_id="run").status is VerificationStatus.SUPPORTED
    candidate = store.get_chain("claim-weak", run_id="run")
    assert candidate.verification.status is VerificationStatus.INSUFFICIENT
    assert candidate.verification.reason == "insufficient_source_credibility"
    assert [link.span.quote for link in store.intact_links(candidate)] == [weak.content]
    assert list(store.supporting_links(candidate)) == []


def test_a_low_credibility_contradiction_edge_does_not_dispute_a_fact(tmp_path):
    main = _source("snap-1")
    weak = _source("weak", url="https://example.com/estimate").model_copy(
        update={"metadata": {"credibility_score": 0.5}},
    )
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(main, weak, claims=[_claim("claim-1")]))
    store.add_edge(ClaimEvidenceEdgeRecord(
        claim_id="claim-1", span_id="weak:chunk:1", relation=EdgeRelation.CONTRADICTS,
    ))

    record = store.verify_claim("claim-1")

    assert record.status is VerificationStatus.SUPPORTED
    assert record.deterministic_checks["contradicting_edges"] == 0


@pytest.mark.parametrize(
    ("counter_score", "offset", "expected_status", "expected_reason"),
    [
        (0.95, 0, VerificationStatus.CONTRADICTED, "contradicting_evidence"),
        (0.5, 0, VerificationStatus.INSUFFICIENT, "insufficient_source_credibility"),
        (0.95, 1, VerificationStatus.INSUFFICIENT, "insufficient_source_credibility"),
    ],
    ids=["credible-counter", "weak-counter", "broken-counter"],
)
def test_weak_matching_quote_cannot_mask_an_eligible_counter_edge(
    tmp_path, counter_score, offset, expected_status, expected_reason,
):
    weak = _source("snap-1").model_copy(update={"metadata": {"credibility_score": 0.5}})
    counter = _source(
        "snap-counter", content="德清县2024年地区生产总值为700亿元。",
        url="https://example.gov.cn/revision", start=offset,
    ).model_copy(update={"metadata": {"credibility_score": counter_score}})
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(weak, counter, claims=[_claim("claim-1")]))
    store.add_edge(ClaimEvidenceEdgeRecord(
        claim_id="claim-1", span_id="snap-counter:chunk:1", relation=EdgeRelation.CONTRADICTS,
    ))

    record = store.verify_claim("claim-1")

    assert record.status is expected_status
    assert record.reason == expected_reason


def test_an_intact_credible_counter_edge_is_evidence_without_a_supporting_quote(tmp_path):
    counter = _source(
        "snap-counter", content="德清县2024年地区生产总值为700亿元。",
    ).model_copy(update={"metadata": {"credibility_score": 0.95}})
    claim = _claim("claim-1").model_copy(update={"source_ids": [], "evidence_chunk_ids": []})
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(counter, claims=[claim]))
    store.add_edge(ClaimEvidenceEdgeRecord(
        claim_id="claim-1", span_id="snap-counter:chunk:1", relation=EdgeRelation.CONTRADICTS,
    ))

    assert store.verify_claim("claim-1").status is VerificationStatus.CONTRADICTED


def test_an_unscored_snapshot_does_not_authorize_a_later_low_credibility_import(tmp_path):
    source = _source("snap-1")
    claim = _claim("claim-1")
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(source, claims=[claim]), run_id="unscored")
    weak = source.model_copy(update={"metadata": {"credibility_score": 0.5}})
    store.save_ledger(_ledger(weak, claims=[claim]), run_id="scored")

    assert store.get_chain(claim.claim_id, run_id="unscored").verification.status is VerificationStatus.SUPPORTED
    later = store.get_chain(claim.claim_id, run_id="scored")
    assert later.verification.status is VerificationStatus.INSUFFICIENT
    assert later.verification.reason == "insufficient_source_credibility"
    assert list(store.supporting_links(later)) == []


def test_conflict_check_uses_the_persisted_source_rating(tmp_path):
    weak = _source(
        "snap-weak", content="德清县2024年地区生产总值为700亿元。", url="https://example.com/estimate",
    ).model_copy(update={"metadata": {"credibility_score": 0.5}})
    strong = _source("snap-1").model_copy(update={"metadata": {"credibility_score": 0.9}})
    claim = _claim(
        "claim-weak", source_id="snap-weak", chunk_id="snap-weak:chunk:1", value="700",
        statement="德清县2024年地区生产总值为700亿元",
    )
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(weak), run_id="earlier")
    rerated = weak.model_copy(update={"metadata": {"credibility_score": 0.9}})

    store.save_ledger(_ledger(strong, rerated, claims=[_claim("claim-strong"), claim]), run_id="later")

    record = store.get_chain("claim-strong", run_id="later").verification
    assert record.status is VerificationStatus.SUPPORTED
    assert record.deterministic_checks["contradicting_supported_claims"] == []


def test_missing_evidence_takes_precedence_over_low_source_credibility(tmp_path):
    source = _source("snap-1").model_copy(update={"metadata": {"credibility_score": 0.5}})
    claim = _claim("claim-unbound").model_copy(update={"evidence_chunk_ids": []})
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    store.save_ledger(_ledger(source, claims=[claim]), run_id="run")

    record = store.get_chain("claim-unbound", run_id="run").verification
    assert record.status is VerificationStatus.INSUFFICIENT
    assert record.reason == "no_evidence"


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
    ("repost_score", "repost_value", "offset", "archived_at"),
    [
        pytest.param(0.5, "130", 0, None, id="weak-quote"),
        pytest.param(0.95, "131", 0, None, id="nonmatching-quote"),
        pytest.param(0.95, "130", 1, None, id="broken-quote"),
        pytest.param(0.95, "130", 0, datetime(2025, 1, 15, tzinfo=timezone.utc), id="refetched-quote"),
    ],
)
def test_only_intact_eligible_matching_quotes_date_a_series_revision(
    tmp_path, repost_score, repost_value, offset, archived_at,
):
    january = _source(
        "january", content="德清县2024年地区生产总值为130亿元。",
        retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    ).model_copy(update={"metadata": {"credibility_score": 0.95}})
    march = _source(
        "march", content="德清县2024年地区生产总值为120亿元。",
        retrieved_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
    ).model_copy(update={"metadata": {"credibility_score": 0.9}})
    repost = _source(
        "repost", content=f"德清县2024年地区生产总值为{repost_value}亿元。",
        url="https://example.com/repost", start=offset,
        retrieved_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
    ).model_copy(update={"metadata": {"credibility_score": repost_score}})
    older = _claim(
        "older", value="130", statement="德清县2024年地区生产总值为130亿元", version="v1",
    ).model_copy(update={
        "source_ids": ["january", "repost"],
        "evidence_chunk_ids": ["january:chunk:1", "repost:chunk:1"],
    })
    newer = _claim(
        "newer", source_id="march", chunk_id="march:chunk:1", value="120",
        statement="德清县2024年地区生产总值为120亿元", version="v2",
    )
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    if archived_at is not None:
        earlier = repost.model_copy(update={"retrieved_at": archived_at})
        store.save_ledger(_ledger(earlier), run_id="previous-run")
    store.save_ledger(_ledger(january, march, repost, claims=[older, newer]), run_id="run")

    assert store.get_snapshot(repost.doc_id).observed_at == (archived_at or repost.retrieved_at)
    current = store.get_chain(newer.claim_id, run_id="run")
    assert current.verification.status is VerificationStatus.SUPPORTED
    assert store.get_chain(older.claim_id, run_id="run").verification.status is VerificationStatus.OUTDATED
    relation, = [relation for relation in current.relations if relation.relation is ClaimRelationKind.SUPERSEDES]
    assert (relation.from_claim_id, relation.to_claim_id) == (newer.claim_id, older.claim_id)


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


def test_multi_year_claim_is_not_a_single_target_year_fact(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    window = (date(2024, 1, 1), date(2024, 12, 31))
    content = "德清县2024-2025年地区生产总值为722.5亿元。"
    store.save_ledger(
        _ledger(
            _source("snap-1", content=content),
            claims=[
                _claim(
                    "claim-span",
                    period="2024-2025",
                    statement="德清县2024-2025年地区生产总值为722.5亿元",
                )
            ],
        ),
        window=window,
    )

    record = store.verify_claim("claim-span", window=window)

    assert record.status is VerificationStatus.NOT_COMPARABLE
    assert store.get_claim("claim-span").verification_reason == (
        "outside_requested_window:2025"
    )


def test_adjacent_year_claims_stay_outside_the_2024_window(tmp_path):
    store = EvidenceGraphStore(tmp_path / "graph.sqlite")
    window = (date(2024, 1, 1), date(2024, 12, 31))
    store.save_ledger(
        _ledger(
            _source("snap-1"),
            claims=[
                _claim("claim-2023", period="2023"),
                _claim("claim-2025", period="2025"),
            ],
        ),
        window=window,
    )

    previous = store.verify_claim("claim-2023", window=window)
    following = store.verify_claim("claim-2025", window=window)

    assert previous.status is VerificationStatus.NOT_COMPARABLE
    assert following.status is VerificationStatus.NOT_COMPARABLE
    assert store.get_claim("claim-2023").verification_reason == (
        "outside_requested_window:2023"
    )
    assert store.get_claim("claim-2025").verification_reason == (
        "outside_requested_window:2025"
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_later_run_cannot_replace_an_earlier_claim_version(tmp_path, legacy):
    path = tmp_path / "graph.sqlite"
    store = EvidenceGraphStore(path)
    first = _source("old-z")
    old_claim = _claim("shared", source_id=first.doc_id, chunk_id=first.chunks[0].chunk_id)
    store.save_ledger(_ledger(first, claims=[old_claim]), run_id="" if legacy else "earlier")
    store.save_findings("earlier", [FindingRecord(
        finding_id="earlier:shared", run_id="earlier", claim_id="shared",
        text=old_claim.statement, status=VerificationStatus.SUPPORTED,
    )])

    second = _source("new-a", content=CONTENT.replace("2024", "2023"))
    new_claim = _claim(
        "shared", source_id=second.doc_id, chunk_id=second.chunks[0].chunk_id,
        period="2023", statement=old_claim.statement.replace("2024", "2023"),
    )
    # The later run collected both sources. Only the new one belongs to its claim.
    store.save_ledger(_ledger(first, second, claims=[new_claim]), run_id="later")
    reopened = EvidenceGraphStore(path)

    old_chain = reopened.list_findings("earlier")[0].chain
    assert old_chain.claim.period == "2024"
    assert old_chain.claim.source_ids == ["old-z"]
    assert [link.span.span_id for link in old_chain.links] == ["old-z:chunk:1"]
    assert reopened.list_claims(run_id="earlier")[0].period == "2024"
    assert reopened.list_run_claims("earlier")[0].period == "2024"
    assert old_chain.verification.status is VerificationStatus.SUPPORTED
    new_chain = reopened.get_chain("shared", run_id="later")
    assert new_chain.claim.period == "2023"
    assert [link.span.span_id for link in new_chain.links] == ["new-a:chunk:1"]

    reopened.clear_run("later")
    with pytest.raises(KeyError):
        reopened.get_chain("shared", run_id="later")
    assert reopened.get_chain("shared", run_id="earlier") == old_chain


@pytest.mark.parametrize("old_scope", ["unscoped", "mapped", "shared-snapshots"])
def test_v2_migration_withholds_overwritten_claims(tmp_path, old_scope):
    import sqlite3

    path = tmp_path / "graph.sqlite"
    store = EvidenceGraphStore(path)
    first = _source("old-source")
    old = _claim("shared", source_id=first.doc_id, chunk_id=first.chunks[0].chunk_id)
    second = _source("new-source", content=CONTENT.replace("2024", "2023"))
    new = _claim("shared", source_id=second.doc_id, chunk_id=second.chunks[0].chunk_id,
                 period="2023", statement=old.statement.replace("2024", "2023"))
    if old_scope == "shared-snapshots":
        # The wrong edge predates old-run and its source was collected by old-run.
        store.save_ledger(_ledger(second, claims=[new]), run_id="seed-run")
        sources = (first, second)
    else:
        sources = (first,)
    store.save_ledger(_ledger(*sources, claims=[old]), run_id="" if old_scope == "unscoped" else "old-run")
    store.save_findings("old-run", [FindingRecord(
        finding_id="old-run:shared", run_id="old-run", claim_id="shared",
        text=old.statement, status=VerificationStatus.SUPPORTED,
    )])
    store.save_ledger(_ledger(first, second, claims=[new]), run_id="new-run")
    connection = sqlite3.connect(path)
    try:
        connection.executescript("DROP TABLE run_claims; PRAGMA user_version = 2;")
    finally:
        connection.close()

    migrated = EvidenceGraphStore(path)

    finding, = migrated.list_findings("old-run")
    assert finding.finding.status is VerificationStatus.INSUFFICIENT
    assert finding.chain.claim.statement == old.statement
    assert finding.chain.claim.verification_reason == "run_evidence_unavailable"
    assert not finding.chain.links
    if old_scope != "shared-snapshots":
        assert "new-source" not in {source.snapshot_id for source in migrated.list_run_snapshots("old-run")}
    current = migrated.get_chain("shared", run_id="new-run")
    assert current.claim.period == "2023"
    assert [link.snapshot.snapshot_id for link in current.links] == ["new-source"]


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


def test_findings_persist_every_linked_slot_and_fall_back_to_section(tmp_path):
    path = tmp_path / "graph.sqlite"
    store = EvidenceGraphStore(path)
    store.save_ledger(_ledger(_source("snap-1"), claims=[_claim("claim-1")]), run_id="run-1")
    store.save_findings(
        "run-1",
        [
            FindingRecord(
                finding_id="finding-shared",
                run_id="run-1",
                claim_id="claim-1",
                section="contract:0",
                slot_ids=["contract:0", "contract:1"],
                text="2024年地区生产总值722.5亿元",
                status=VerificationStatus.SUPPORTED,
            )
        ],
    )

    reopened = EvidenceGraphStore(path)
    shared = reopened.list_findings("run-1")[0].finding
    assert shared.slot_ids == ["contract:0", "contract:1"]
    assert shared.linked_slot_ids() == ["contract:0", "contract:1"]

    store.save_ledger(_ledger(_source("snap-1"), claims=[_claim("claim-1")]), run_id="run-2")
    store.save_findings(
        "run-2",
        [
            FindingRecord(
                finding_id="finding-legacy",
                run_id="run-2",
                claim_id="claim-1",
                section="经济概况",
                text="旧记录",
                status=VerificationStatus.SUPPORTED,
            )
        ],
    )
    legacy = store.list_findings("run-2")[0].finding
    assert legacy.linked_slot_ids() == ["经济概况"]
    assert FindingRecord(
        finding_id="in-memory", run_id="run-3", claim_id="claim-1", section="经济概况"
    ).linked_slot_ids() == ["经济概况"]


def test_clear_run_removes_slot_links(tmp_path):
    import sqlite3

    path = tmp_path / "graph.sqlite"
    store = EvidenceGraphStore(path)
    store.save_ledger(_ledger(_source("snap-1"), claims=[_claim("claim-1")]), run_id="run-1")
    store.save_findings(
        "run-1",
        [
            FindingRecord(
                finding_id="finding-shared",
                run_id="run-1",
                claim_id="claim-1",
                section="contract:0",
                slot_ids=["contract:0", "contract:1"],
            )
        ],
    )

    store.clear_run("run-1")

    with sqlite3.connect(path) as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM finding_slots WHERE run_id = 'run-1'"
        ).fetchone()[0]
    assert remaining == 0


def test_v2_database_gains_the_slot_table_on_reopen(tmp_path):
    import sqlite3

    path = tmp_path / "graph.sqlite"
    store = EvidenceGraphStore(path)
    store.save_ledger(_ledger(_source("snap-1"), claims=[_claim("claim-1")]), run_id="run-1")
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE finding_slots")
        connection.execute("PRAGMA user_version = 2")

    reopened = EvidenceGraphStore(path)
    reopened.save_findings(
        "run-1",
        [
            FindingRecord(
                finding_id="finding-shared",
                run_id="run-1",
                claim_id="claim-1",
                section="contract:0",
                slot_ids=["contract:0", "contract:1"],
            )
        ],
    )

    assert reopened.list_findings("run-1")[0].finding.slot_ids == ["contract:0", "contract:1"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3


def test_run_verdict_is_persisted_without_changing_the_global_claim(tmp_path):
    path = tmp_path / "graph.sqlite"
    store = EvidenceGraphStore(path)
    store.save_ledger(_ledger(_source("snap-1"), claims=[_claim("claim-1")]), run_id="run-1")
    before = store.get_claim("claim-1").verification_status

    verdict = VerificationRecord(
        record_id="verdict-run-1",
        claim_id="claim-1",
        status=VerificationStatus.NEEDS_REVIEW,
        deterministic_checks={"contradicting_supported_claims": ["other"]},
        run_id="run-1",
        reason="conflicting_contract_evidence",
    )
    store.save_findings(
        "run-1",
        [
            FindingRecord(
                finding_id="finding-shared",
                run_id="run-1",
                claim_id="claim-1",
                section="contract:0",
                slot_ids=["contract:0"],
                status=VerificationStatus.INSUFFICIENT,
            )
        ],
        verifications=[verdict],
    )

    finding = store.list_findings("run-1")[0]
    assert finding.finding.status is VerificationStatus.INSUFFICIENT
    assert finding.chain.verification is not None
    assert finding.chain.verification.status is VerificationStatus.NEEDS_REVIEW
    assert finding.chain.verification.reason == "conflicting_contract_evidence"
    assert store.get_claim("claim-1").verification_status == before
