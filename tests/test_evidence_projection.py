from __future__ import annotations

from county_research_ai.api.projections import build_evidence_list
from tests.projection_helpers import (
    RUN_ID,
    deep_result,
    make_claim,
    make_item,
    make_job,
    make_source,
    seed_graph,
)


def _evidence_fixture(tmp_path):
    supported_source = make_source(
        "snap-supported",
        url="https://example.gov.cn/supported",
        content="安吉县2024年竹产业产值为120亿元。",
    )
    missing_source = make_source(
        "snap-missing",
        url="https://example.gov.cn/missing",
        content="安吉县2024年竹林面积为80万亩。",
    )
    supported = make_claim(
        "claim-supported",
        source_id="snap-supported",
        value="120",
        metric="竹产业产值",
    )
    missing = make_claim(
        "claim-missing",
        source_id="snap-missing",
        value="999",
        metric="竹加工产值",
        statement="安吉县2024年竹加工产值为999亿元",
    )
    graph = seed_graph(
        tmp_path / "graph.sqlite",
        RUN_ID,
        sources=[supported_source, missing_source],
        claims=[supported, missing],
    )
    questions = [
        {
            "id": "q-output",
            "title": "竹产业产值是多少？",
            "evidence_ids": ["item-supported"],
        }
    ]
    items = [
        make_item("item-supported", supported, supported_source),
        make_item(
            "item-missing",
            missing,
            missing_source,
            topic="竹加工",
            credibility=0.3,
        ),
    ]
    job = make_job(result=deep_result(questions=questions, items=items))
    return graph, job


def test_evidence_list_is_status_sorted_and_numbered(tmp_path):
    graph, job = _evidence_fixture(tmp_path)

    result = build_evidence_list(job=job, graph=graph)

    assert result.total == 2
    assert [item.claim_id for item in result.items] == [
        "claim-supported",
        "claim-missing",
    ]
    first = result.items[0]
    assert first.status == "SUPPORTED"
    assert first.citation_number == 1
    assert first.value == "120"
    assert first.unit == "亿元"
    assert first.period == "2024"
    assert first.topic == "竹产业"
    assert first.question_ids == ["q-output"]
    assert first.links
    assert first.links[0].snapshot_id == "snap-supported"
    assert "120" in first.links[0].quote
    second = result.items[1]
    assert second.status == "INSUFFICIENT"
    assert second.credibility == 0.3
    assert second.question_ids == []


def test_evidence_list_filters_query_status_topic_and_credibility(tmp_path):
    graph, job = _evidence_fixture(tmp_path)

    assert build_evidence_list(job=job, graph=graph, query="竹加工").total == 1
    assert build_evidence_list(job=job, graph=graph, status="SUPPORTED").total == 1
    assert build_evidence_list(job=job, graph=graph, topic="竹加工").total == 1
    assert build_evidence_list(job=job, graph=graph, min_credibility=0.5).total == 1

    page = build_evidence_list(job=job, graph=graph, limit=1, offset=1)
    assert page.total == 2
    assert len(page.items) == 1
    assert page.items[0].claim_id == "claim-missing"
    assert page.limit == 1
    assert page.offset == 1


def test_evidence_list_without_deep_projection_still_returns_claims(tmp_path):
    source = make_source(
        "snap-only",
        url="https://example.gov.cn/only",
        content="安吉县2024年竹产业产值为120亿元。",
    )
    claim = make_claim("claim-only", source_id="snap-only", value="120")
    graph = seed_graph(
        tmp_path / "graph.sqlite",
        RUN_ID,
        sources=[source],
        claims=[claim],
    )
    job = make_job(result={})

    result = build_evidence_list(job=job, graph=graph)

    assert result.total == 1
    assert result.items[0].claim_id == "claim-only"
    assert result.items[0].question_ids == []
