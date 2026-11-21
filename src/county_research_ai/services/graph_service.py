"""Knowledge Graph 服务：Agent 工具与 API 的图谱访问入口。"""
from __future__ import annotations

import threading
from typing import Any

from ..knowledge_graph.graph_rag.query_engine import GraphQueryResult, GraphRAGQueryEngine
from ..knowledge_graph.graph_store.base import GraphStore, Subgraph
from ..knowledge_graph.ontology.entities import EntityType, KGEntity


class ThreadLocalEvidenceLookup:
    """按线程绑定当前运行的证据库。

    GraphRAG 查询引擎是跨运行共享的，但证据库是每次研究独立的；
    Agent 在自己的工作线程里调用 ``bind``，图谱答案即可回填当前运行的证据。
    """

    def __init__(self) -> None:
        self._local = threading.local()

    def bind(self, evidence: Any) -> None:
        self._local.evidence = evidence

    def _current(self) -> Any:
        return getattr(self._local, "evidence", None)

    def by_ids(self, ids: list[str]) -> list[Any]:
        evidence = self._current()
        if evidence is None:
            return []
        return evidence.by_ids(ids)

    def search(
        self, keywords: list[str], *, topic: str = "", limit: int = 10
    ) -> list[Any]:
        evidence = self._current()
        if evidence is None:
            return []
        return evidence.search(keywords, topic=topic, limit=limit)


class GraphService:
    """把 GraphRAG 查询引擎暴露为稳定的服务接口。"""

    def __init__(self, graph: GraphStore, query_engine: GraphRAGQueryEngine) -> None:
        self._graph = graph
        self.query_engine = query_engine

    @property
    def store(self) -> GraphStore:
        return self._graph

    # ---- 元信息 ----

    def stats(self) -> dict[str, int]:
        return self._graph.stats()

    def county_graph(self, county: str, *, industry: str = "", limit: int = 200) -> dict[str, Any]:
        subgraph = self._graph.county_subgraph(county, industry=industry, limit=limit)
        return {
            "county": county,
            "industry": industry,
            "entities": [_entity_brief(e) for e in subgraph.entities],
            "relations": [_relation_brief(r) for r in subgraph.relations],
            "evidence_ids": subgraph.evidence_ids,
            "truncated": subgraph.truncated,
            "stats": self._graph.stats(),
        }

    def entities(
        self, *, county: str = "", entity_type: str = "", name: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        parsed_type: EntityType | None = None
        if entity_type:
            try:
                parsed_type = EntityType(entity_type)
            except ValueError:
                parsed_type = None
        entities = self._graph.find_entities(
            entity_type=parsed_type, name=name or None, county=county or None, limit=limit
        )
        return [_entity_brief(e) for e in entities]

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        entity = self._graph.get_entity(entity_id)
        return _entity_brief(entity) if entity else None

    # ---- GraphRAG ----

    def query(self, question: str, *, county: str = "", focus: str = "") -> GraphQueryResult:
        return self.query_engine.answer(question, county=county, focus=focus)

    def enterprise_relations(self, enterprise: str, *, county: str = "") -> GraphQueryResult:
        return self.query_engine.enterprise_relations(enterprise, county=county)

    def supply_chain(
        self, industry: str, *, county: str = "", direction: str = "both", depth: int = 2
    ) -> GraphQueryResult:
        return self.query_engine.supply_chain(
            industry, county=county, direction=direction, depth=depth
        )

    def chain_paths(self, source: str, target: str, *, county: str = "") -> GraphQueryResult:
        return self.query_engine.chain_paths(source, target, county=county)

    def clusters(self, county: str, *, industry: str = "") -> GraphQueryResult:
        return self.query_engine.clusters(county, industry=industry)

    def park_enterprises(self, park: str, *, county: str = "") -> GraphQueryResult:
        return self.query_engine.park_enterprises(park, county=county)

    def policy_industry_links(self, industry: str, *, county: str = "") -> GraphQueryResult:
        return self.query_engine.policy_industry_links(industry, county=county)

    def evidence_trace(self, *, entity_id: str = "", relation_id: str = "") -> GraphQueryResult:
        return self.query_engine.evidence_trace(entity_id=entity_id, relation_id=relation_id)

    def multi_hop(self, entity: str, *, county: str = "", depth: int = 3) -> GraphQueryResult:
        return self.query_engine.multi_hop(entity, county=county, depth=depth)


def _entity_brief(entity: KGEntity) -> dict[str, Any]:
    return {
        "id": entity.id,
        "type": entity.type.value,
        "name": entity.name,
        "aliases": entity.aliases,
        "county": entity.county,
        "confidence": entity.confidence,
        "verification_status": entity.verification_status.value,
        "evidence_ids": entity.evidence_ids,
        "properties": entity.properties,
    }


def _relation_brief(relation: Any) -> dict[str, Any]:
    return {
        "id": relation.id,
        "source_entity_id": relation.source_entity_id,
        "target_entity_id": relation.target_entity_id,
        "type": relation.relationship_type.value,
        "confidence": relation.confidence,
        "verification_status": relation.verification_status.value,
        "evidence_ids": relation.evidence_refs(),
        "quote": relation.quote,
        "valid_from": relation.valid_from.isoformat() if relation.valid_from else "",
        "valid_to": relation.valid_to.isoformat() if relation.valid_to else "",
    }


__all__ = ["GraphService", "Subgraph", "ThreadLocalEvidenceLookup"]
