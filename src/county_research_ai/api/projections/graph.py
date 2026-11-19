"""Deterministic graph projection from run-scoped claims, questions and sources."""
from __future__ import annotations

from typing import Any

from ...evidence.graph import EvidenceGraphStore
from ..jobs import JobRecord
from .common import (
    dedupe,
    deep_projection,
    find_item,
    item_index,
    normalize_url,
    question_ids_by_item,
    sha,
    source_credibility,
    status_weight,
    truncate,
)
from .models import GraphEdge, GraphMeta, GraphNode, GraphView

_TYPE_ORDER = {
    "conflict": 0,
    "gap": 1,
    "question": 2,
    "county": 3,
    "evidence": 4,
    "topic": 5,
    "source": 6,
}


def build_graph_view(  # noqa: C901
    *,
    job: JobRecord,
    graph: EvidenceGraphStore,
    max_nodes: int = 400,
    max_edges: int = 800,
    include_sources: bool = True,
    topics: set[str] | None = None,
) -> GraphView:
    max_nodes = min(1000, max(50, max_nodes))
    max_edges = min(4000, max(1, max_edges))
    deep = deep_projection(job)
    question_tree = deep.get("question_tree") or {}
    items = deep.get("items") or []
    conflicts = deep.get("conflicts") or []
    gaps = deep.get("gaps") or []
    findings = graph.list_findings(job.job_id)
    snapshots = graph.list_run_snapshots(job.job_id)
    snapshot_by_id = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
    item_lookup = item_index(items)
    item_questions = question_ids_by_item(question_tree)

    county_name = job.county or (job.contract.regions[0] if job.contract.regions else "")
    county_id = f"county:{sha(county_name, 8)}"
    nodes: dict[str, GraphNode] = {
        county_id: GraphNode(
            id=county_id,
            type="county",
            label=county_name or "县域",
            sublabel=job.mode,
            data={
                "mode": job.mode,
                "objective": job.contract.objective,
                "coverage_rate": deep.get("coverage_rate"),
            },
        )
    }
    edges: list[GraphEdge] = []
    edge_ids: set[str] = set()
    dropped_self_loops = 0

    def add_edge(
        source: str,
        target: str,
        edge_type: str,
        *,
        label: str = "",
        directed: bool = True,
        weight: float = 1.0,
        data: dict[str, Any] | None = None,
    ) -> None:
        nonlocal dropped_self_loops
        if source == target:
            dropped_self_loops += 1
            return
        base = f"{edge_type}:{source}->{target}"
        edge_id = base
        suffix = 2
        while edge_id in edge_ids:
            edge_id = f"{base}:p{suffix}"
            suffix += 1
        edge_ids.add(edge_id)
        edges.append(
            GraphEdge(
                id=edge_id,
                source=source,
                target=target,
                type=edge_type,  # type: ignore[arg-type]
                label=label,
                directed=directed,
                weight=weight,
                data=data or {},
            )
        )

    question_ids: set[str] = set()
    for question in question_tree.get("questions", []) or []:
        question_key = str(question.get("id", ""))
        if not question_key:
            continue
        node_id = f"q:{question_key}"
        question_ids.add(node_id)
        evidence_ids = [str(value) for value in question.get("evidence_ids", []) or []]
        nodes[node_id] = GraphNode(
            id=node_id,
            type="question",
            label=str(question.get("title", question_key)),
            sublabel=str(question.get("category", "")),
            weight=1.0 + len(evidence_ids) / 5.0,
            data={
                "question_id": question_key,
                "category": question.get("category", ""),
                "description": question.get("description", ""),
                "required_indicators": list(question.get("required_indicators", []) or []),
                "evidence_ids": evidence_ids,
                "is_satisfied": bool(question.get("is_satisfied")),
            },
        )
        add_edge(county_id, node_id, "has_question", weight=1.0)

    evidence_nodes: dict[str, GraphNode] = {}
    item_to_claims: dict[str, list[str]] = {}
    url_to_evidence: dict[str, list[str]] = {}
    for finding in findings:
        chain = finding.chain
        claim = chain.claim
        node_id = f"ev:{claim.claim_id}"
        urls = [
            link.snapshot.canonical_url
            for link in chain.links
            if link.snapshot.canonical_url
        ]
        item = find_item(item_lookup, claim.statement, urls)
        item_id = str(item.get("id", "")) if item is not None else ""
        if item_id:
            item_to_claims.setdefault(item_id, []).append(claim.claim_id)
        metric = claim.metric_id or claim.measure_id
        topic = str(item.get("topic", "")) if item is not None else ""
        credibility = (
            float(item.get("credibility_score", 0.5))
            if item is not None
            else status_weight(finding.finding.status.value)
        )
        label = str(item.get("claim", "")) if item is not None else claim.statement
        sublabel = (
            str(item.get("title", "")) if item is not None else metric
        )
        link_data = [
            {
                "relation": link.edge.relation.value,
                "span_id": link.span.span_id,
                "snapshot_id": link.snapshot.snapshot_id,
                "url": link.snapshot.canonical_url,
                "title": link.snapshot.title,
                "quote": truncate(link.span.quote, 240),
            }
            for link in chain.links
        ]
        node = GraphNode(
            id=node_id,
            type="evidence",
            label=truncate(label, 80),
            sublabel=truncate(sublabel, 50),
            weight=max(0.05, credibility),
            data={
                "claim_id": claim.claim_id,
                "statement": claim.statement,
                "metric": metric,
                "value": claim.value,
                "unit": claim.unit,
                "period": claim.period,
                "scope": claim.administrative_scope,
                "caliber": claim.statistical_caliber,
                "series_version": claim.series_version,
                "status": finding.finding.status.value,
                "reason": chain.verification.reason if chain.verification else "",
                "evidence_item_id": item_id,
                "topic": topic,
                "year": item.get("year") if item is not None else None,
                "credibility": credibility,
                "url": urls[0] if urls else "",
                "title": str(item.get("title", "")) if item is not None else "",
                "snippet": str(item.get("snippet", "")) if item is not None else "",
                "question_ids": item_questions.get(item_id, []),
                "links": link_data,
                "independent_support": (
                    chain.verification.deterministic_checks.get("independent_support")
                    if chain.verification
                    else None
                ),
            },
        )
        nodes[node_id] = node
        evidence_nodes[node_id] = node
        for url in urls:
            url_to_evidence.setdefault(normalize_url(url), []).append(node_id)

    # question -> evidence, only where a persisted EvidenceStore item maps to a
    # verified claim. Unmatched question evidence ids stay visible in data.
    for question in question_tree.get("questions", []) or []:
        question_node = f"q:{question.get('id', '')}"
        for item_id in question.get("evidence_ids", []) or []:
            for claim_id in item_to_claims.get(str(item_id), []):
                evidence_node = f"ev:{claim_id}"
                if evidence_node in nodes:
                    add_edge(question_node, evidence_node, "supported_by")

    source_nodes: dict[str, GraphNode] = {}
    for evidence_node in evidence_nodes.values():
        for link in evidence_node.data.get("links", []):
            if link["relation"] == "contradicts":
                continue
            url = link["url"]
            snapshot = snapshot_by_id.get(link["snapshot_id"])
            normalized = normalize_url(url)
            if normalized:
                source_id = f"src:{sha(normalized, 12)}"
            else:
                source_id = f"src:snapshot:{link['snapshot_id']}"
            existing = source_nodes.get(source_id)
            if existing is None:
                existing = GraphNode(
                    id=source_id,
                    type="source",
                    label=truncate(
                        link["title"] or (snapshot.title if snapshot else "") or url,
                        50,
                    ),
                    sublabel=(
                        snapshot.source_type if snapshot is not None else "unknown"
                    ),
                    weight=source_credibility(snapshot) if snapshot else 0.5,
                    data={
                        "url": url,
                        "normalized_url": normalized,
                        "snapshot_ids": [link["snapshot_id"]],
                        "title": link["title"],
                        "source_type": (
                            snapshot.source_type if snapshot is not None else "unknown"
                        ),
                        "fetch_status": (
                            snapshot.fetch_status if snapshot is not None else "unknown"
                        ),
                        "credibility": (
                            source_credibility(snapshot) if snapshot else 0.5
                        ),
                        "observed_at": (
                            snapshot.observed_at.isoformat()
                            if snapshot is not None and snapshot.observed_at
                            else None
                        ),
                        "published_at": (
                            snapshot.published_at.isoformat()
                            if snapshot is not None and snapshot.published_at
                            else None
                        ),
                        "citation_count": 0,
                    },
                )
                source_nodes[source_id] = existing
            if link["snapshot_id"] not in existing.data["snapshot_ids"]:
                existing.data["snapshot_ids"].append(link["snapshot_id"])
            existing.data["citation_count"] += 1
            add_edge(
                evidence_node.id,
                source_id,
                "cited_from",
                weight=1.0,
                data={
                    "span_id": link["span_id"],
                    "relation": link["relation"],
                },
            )
    nodes.update(source_nodes)

    topic_nodes: dict[str, GraphNode] = {}
    for evidence_node in evidence_nodes.values():
        metric = evidence_node.data.get("metric") or ""
        if not metric:
            continue
        topic_id = f"topic:{sha(metric, 8)}"
        topic_node = topic_nodes.get(topic_id)
        if topic_node is None:
            topic_node = GraphNode(
                id=topic_id,
                type="topic",
                label=metric,
                sublabel="指标",
                weight=1.0,
                data={"metric": metric, "evidence_count": 0},
            )
            topic_nodes[topic_id] = topic_node
        topic_node.data["evidence_count"] += 1
        topic_node.weight += 1.0
        add_edge(evidence_node.id, topic_id, "belongs_to")

    gap_nodes: dict[str, GraphNode] = {}
    for gap in gaps:
        question_key = str(gap.get("question_id", ""))
        missing = str(gap.get("missing_aspect", ""))
        gap_id = f"gap:{question_key}:{missing}"
        severity = str(gap.get("severity", "medium"))
        gap_nodes[gap_id] = GraphNode(
            id=gap_id,
            type="gap",
            label=truncate(str(gap.get("description", "")), 60) or missing,
            sublabel=severity,
            weight={"high": 3.0, "medium": 2.0, "low": 1.0}.get(severity, 2.0),
            data=dict(gap),
        )
        question_node = f"q:{question_key}"
        if question_node in nodes:
            add_edge(question_node, gap_id, "has_gap")
    nodes.update(gap_nodes)

    unmatched_conflicts = 0
    for conflict in conflicts:
        signature = "|".join(
            [
                str(conflict.get("indicator", "")),
                str(conflict.get("conflict_type", "")),
                *[
                    f"{claim.get('value', '')}@{claim.get('year', '')}"
                    for claim in conflict.get("claims", []) or []
                ],
            ]
        )
        conflict_id = f"conflict:{sha(signature, 10)}"
        matched: dict[str, None] = {}
        unmatched_claims: list[dict[str, Any]] = []
        for claim in conflict.get("claims", []) or []:
            evidence_ids = url_to_evidence.get(normalize_url(str(claim.get("url", ""))), [])
            if not evidence_ids:
                unmatched_claims.append(dict(claim))
                continue
            for evidence_id in evidence_ids:
                matched[evidence_id] = None
        nodes[conflict_id] = GraphNode(
            id=conflict_id,
            type="conflict",
            label=str(conflict.get("indicator", "")) or "冲突",
            sublabel=str(conflict.get("conflict_type", "")),
            weight=float(len(conflict.get("claims", []) or [])),
            data={
                **dict(conflict),
                "matched_evidence_ids": list(matched),
                "unmatched_claims": unmatched_claims,
            },
        )
        if len(matched) >= 2:
            for evidence_id in matched:
                add_edge(
                    conflict_id,
                    evidence_id,
                    "conflicts_with",
                    directed=False,
                    weight=1.0,
                )
        else:
            unmatched_conflicts += 1

    nodes.update(topic_nodes)
    full_node_count = len(nodes)
    full_counts: dict[str, int] = {}
    for node in nodes.values():
        full_counts[node.type] = full_counts.get(node.type, 0) + 1
    full_edge_count = len(edges)

    allowed_topics = {topic.strip() for topic in topics or set() if topic.strip()}
    optional_evidence = [
        node
        for node in evidence_nodes.values()
        if not allowed_topics or str(node.data.get("metric", "")) in allowed_topics
    ]
    optional_topics = [
        node
        for node in topic_nodes.values()
        if not allowed_topics or str(node.data.get("metric", "")) in allowed_topics
    ]
    if include_sources:
        selected_evidence_ids = {node.id for node in optional_evidence}
        optional_sources = [
            node
            for node in source_nodes.values()
            if any(
                edge.target == node.id and edge.source in selected_evidence_ids
                for edge in edges
                if edge.type == "cited_from"
            )
        ]
    else:
        # Counts still include sources; the returned graph does not.
        optional_sources = []

    degree: dict[str, int] = {}
    for edge in edges:
        degree[edge.source] = degree.get(edge.source, 0) + 1
        degree[edge.target] = degree.get(edge.target, 0) + 1

    required_ids = dedupe(
        [county_id, *sorted(question_ids), *gap_nodes.keys(), *nodes_of_type(nodes, "conflict")]
    )
    required = [nodes[node_id] for node_id in required_ids if node_id in nodes]

    def optional_priority(node: GraphNode) -> tuple[float, float, str]:
        if node.type == "evidence":
            return (
                node.weight * (1.0 + degree.get(node.id, 0)),
                degree.get(node.id, 0),
                node.id,
            )
        if node.type == "source":
            return (
                float(node.data.get("citation_count", 0)) * (1.0 + degree.get(node.id, 0)),
                node.weight,
                node.id,
            )
        return (
            float(node.data.get("evidence_count", 0)),
            degree.get(node.id, 0),
            node.id,
        )

    optional = sorted(
        [*optional_evidence, *optional_topics, *optional_sources],
        key=optional_priority,
        reverse=True,
    )
    room = max(0, max_nodes - len(required))
    selected = {node.id: node for node in required}
    optional_by_id = {node.id: node for node in optional}
    selected_ids = set(selected)

    neighbours: dict[str, list[str]] = {}
    for edge in edges:
        neighbours.setdefault(edge.source, []).append(edge.target)
        neighbours.setdefault(edge.target, []).append(edge.source)

    # Truncation must keep a useful, connected graph: accept an evidence node
    # together with its topic/source neighbours instead of returning hundreds
    # of isolated evidence points after their endpoints were cut.
    evidence_candidates = sorted(optional_evidence, key=optional_priority, reverse=True)
    for candidate in evidence_candidates:
        if room <= 0:
            break
        if candidate.id in selected:
            continue
        group = [candidate]
        for neighbour_id in sorted(neighbours.get(candidate.id, [])):
            if neighbour_id in selected or neighbour_id not in optional_by_id:
                continue
            group.append(optional_by_id[neighbour_id])
        if len(group) > room:
            continue
        for node in group:
            selected[node.id] = node
            selected_ids.add(node.id)
        room -= len(group)

    # Use any remaining capacity on optional nodes that connect to the current
    # selection, then on the remaining highest-priority nodes.
    for node in optional:
        if room <= 0:
            break
        if node.id in selected:
            continue
        if any(neighbour_id in selected_ids for neighbour_id in neighbours.get(node.id, [])):
            selected[node.id] = node
            selected_ids.add(node.id)
            room -= 1
    for node in optional:
        if room <= 0:
            break
        if node.id in selected:
            continue
        selected[node.id] = node
        selected_ids.add(node.id)
        room -= 1

    selected_nodes = list(selected.values())
    selected_nodes.sort(key=lambda node: (_TYPE_ORDER.get(node.type, 9), node.id))

    kept_edges = [
        edge for edge in edges if edge.source in selected and edge.target in selected
    ]
    kept_edges.sort(
        key=lambda edge: (
            -(
                int(edge.source in required_ids)
                + int(edge.target in required_ids)
            ),
            -edge.weight,
            edge.id,
        )
    )
    if len(kept_edges) > max_edges:
        kept_edges = kept_edges[:max_edges]
    kept_edges.sort(key=lambda edge: edge.id)

    returned_counts: dict[str, int] = {}
    for node in selected_nodes:
        returned_counts[node.type] = returned_counts.get(node.type, 0) + 1

    return GraphView(
        run_id=job.job_id,
        nodes=selected_nodes,
        edges=kept_edges,
        meta=GraphMeta(
            total_nodes=full_node_count,
            returned_nodes=len(selected_nodes),
            total_edges=full_edge_count,
            returned_edges=len(kept_edges),
            truncated=(
                full_node_count > len(selected_nodes)
                or full_edge_count > len(kept_edges)
            ),
            coverage_rate=deep.get("coverage_rate"),
            counts=full_counts,
            returned_counts=returned_counts,
            dropped_self_loops=dropped_self_loops,
            unmatched_conflicts=unmatched_conflicts,
        ),
    )


def nodes_of_type(nodes: dict[str, GraphNode], node_type: str) -> list[str]:
    return [node_id for node_id, node in nodes.items() if node.type == node_type]


__all__ = ["build_graph_view"]
