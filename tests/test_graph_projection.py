from __future__ import annotations

from county_research_ai.api.projections import build_graph_view
from tests.projection_helpers import (
    RUN_ID,
    deep_result,
    make_claim,
    make_item,
    make_job,
    make_source,
    seed_graph,
)


def _two_source_graph(tmp_path):
    source_a = make_source(
        "snap-a",
        url="https://Example.GOV.cn/stats/?utm_source=news#top",
        content="安吉县2024年竹产业产值为120亿元。",
        extra_chunks=("全县竹林面积80万亩。",),
    )
    source_b = make_source(
        "snap-b",
        url="https://example.gov.cn/stats",
        content="安吉县2024年竹产业产值为130亿元。",
    )
    claim_a = make_claim(
        "claim-a",
        source_id="snap-a",
        chunk_ids=["snap-a:chunk:1", "snap-a:chunk:2"],
        value="120",
    )
    claim_b = make_claim("claim-b", source_id="snap-b", value="130")
    graph = seed_graph(
        tmp_path / "graph.sqlite",
        RUN_ID,
        sources=[source_a, source_b],
        claims=[claim_a, claim_b],
    )
    return graph, source_a, source_b, claim_a, claim_b


def test_graph_projection_is_stable_and_dedupes_normalized_urls(tmp_path):
    graph, _, _, _, _ = _two_source_graph(tmp_path)
    job = make_job(result=deep_result())

    first = build_graph_view(job=job, graph=graph)
    second = build_graph_view(job=job, graph=graph)

    assert [node.id for node in first.nodes] == [node.id for node in second.nodes]
    assert [edge.id for edge in first.edges] == [edge.id for edge in second.edges]

    sources = [node for node in first.nodes if node.type == "source"]
    assert len(sources) == 1
    assert sources[0].data["citation_count"] == 3
    assert len(sources[0].data["snapshot_ids"]) == 2

    cited = [edge for edge in first.edges if edge.type == "cited_from"]
    assert len(cited) == 3
    assert len({edge.id for edge in cited}) == 3
    assert any(edge.id.endswith(":p2") for edge in cited)
    assert all(edge.source != edge.target for edge in first.edges)
    assert first.meta.truncated is False
    assert first.meta.returned_nodes == first.meta.total_nodes
    assert first.meta.returned_edges == first.meta.total_edges


def test_graph_question_edges_require_a_persisted_evidence_item(tmp_path):
    graph, source_a, _, claim_a, _ = _two_source_graph(tmp_path)
    question = {
        "id": "q-output",
        "title": "竹产业产值是多少？",
        "category": "产业",
        "evidence_ids": ["item-1", "item-unknown"],
        "is_satisfied": True,
    }
    job = make_job(
        result=deep_result(
            questions=[question],
            items=[make_item("item-1", claim_a, source_a)],
        )
    )

    view = build_graph_view(job=job, graph=graph)

    supported = [edge for edge in view.edges if edge.type == "supported_by"]
    assert len(supported) == 1
    assert supported[0].source == "q:q-output"
    assert supported[0].target == "ev:claim-a"
    question_node = next(node for node in view.nodes if node.id == "q:q-output")
    assert question_node.data["evidence_ids"] == ["item-1", "item-unknown"]
    assert question_node.data["is_satisfied"] is True


def test_graph_matches_conflicts_only_when_two_evidence_nodes_match(tmp_path):
    graph, source_a, source_b, _, _ = _two_source_graph(tmp_path)
    conflict = {
        "indicator": "竹产业产值",
        "conflict_type": "value_discrepancy",
        "description": "两个来源的 2024 年产值不一致",
        "claims": [
            {"value": "120", "year": "2024", "url": source_a.canonical_url},
            {"value": "130", "year": "2024", "url": source_b.canonical_url},
        ],
    }
    job = make_job(result=deep_result(conflicts=[conflict]))

    view = build_graph_view(job=job, graph=graph)

    conflict_node = next(node for node in view.nodes if node.type == "conflict")
    assert len(conflict_node.data["matched_evidence_ids"]) == 2
    assert conflict_node.data["unmatched_claims"] == []
    conflict_edges = [edge for edge in view.edges if edge.type == "conflicts_with"]
    assert len(conflict_edges) == 2
    assert all(edge.directed is False for edge in conflict_edges)
    assert view.meta.unmatched_conflicts == 0


def test_graph_keeps_unmatched_conflict_visible_without_fabricated_edges(tmp_path):
    graph, _, _, _, _ = _two_source_graph(tmp_path)
    conflict = {
        "indicator": "竹产业产值",
        "conflict_type": "value_discrepancy",
        "description": "来源 URL 未进入本次证据图",
        "claims": [
            {"value": "120", "year": "2024", "url": "https://unknown.example/1"},
            {"value": "130", "year": "2024", "url": "https://unknown.example/2"},
        ],
    }
    job = make_job(result=deep_result(conflicts=[conflict]))

    view = build_graph_view(job=job, graph=graph)

    conflict_node = next(node for node in view.nodes if node.type == "conflict")
    assert conflict_node.data["matched_evidence_ids"] == []
    assert len(conflict_node.data["unmatched_claims"]) == 2
    assert not [edge for edge in view.edges if edge.type == "conflicts_with"]
    assert view.meta.unmatched_conflicts == 1


def test_graph_truncates_optional_nodes_but_keeps_truthful_counts(tmp_path):
    sources = []
    claims = []
    for index in range(60):
        source = make_source(
            f"snap-{index}",
            url=f"https://example.gov.cn/item/{index}",
            content=f"安吉县2024年指标{index}为{index + 1}亿元。",
        )
        sources.append(source)
        claims.append(
            make_claim(
                f"claim-{index}",
                source_id=f"snap-{index}",
                value=str(index + 1),
                metric=f"指标{index}",
            )
        )
    graph = seed_graph(
        tmp_path / "graph.sqlite",
        RUN_ID,
        sources=sources,
        claims=claims,
    )
    job = make_job(result=deep_result())

    view = build_graph_view(
        job=job,
        graph=graph,
        max_nodes=50,
        max_edges=80,
        include_sources=False,
    )

    assert len(view.nodes) == 50
    assert view.meta.truncated is True
    assert view.meta.total_nodes == 181
    assert view.meta.counts["source"] == 60
    assert view.meta.returned_counts.get("source", 0) == 0
    selected = {node.id for node in view.nodes}
    assert all(edge.source in selected and edge.target in selected for edge in view.edges)
    assert len(view.edges) <= 80


def test_graph_projection_reports_missing_deep_research(tmp_path):
    from county_research_ai.api.projections import ProjectionUnavailable

    graph = seed_graph(
        tmp_path / "graph.sqlite",
        RUN_ID,
        sources=[],
        claims=[],
    )
    job = make_job(result={})

    try:
        build_graph_view(job=job, graph=graph)
    except ProjectionUnavailable as exc:
        assert exc.reason == "deep_research_disabled"
    else:  # pragma: no cover - explicit failure message
        raise AssertionError("expected ProjectionUnavailable")
