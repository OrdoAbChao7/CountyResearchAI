"""内存图存储（默认适配器）。

开发与测试不依赖 Neo4j；接口与 ``Neo4jGraphStore`` 完全一致。
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from datetime import datetime

from ...domain.intelligence import VerificationStatus
from ..ontology.entities import EntityType, KGEntity
from ..ontology.relations import KGRelation, RelationshipType
from .base import GraphStore, GraphStoreError, GraphWritePolicy, Subgraph

_STATUS_STRENGTH = {
    VerificationStatus.UNVERIFIED: 0,
    VerificationStatus.INFERRED: 1,
    VerificationStatus.PENDING: 2,
    VerificationStatus.VERIFIED: 3,
}


class InMemoryGraphStore(GraphStore):
    """线程安全的内存图数据库。"""

    name = "memory"

    def __init__(self, policy: GraphWritePolicy | None = None) -> None:
        super().__init__(policy)
        self._entities: dict[str, KGEntity] = {}
        self._relations: dict[str, KGRelation] = {}
        self._out_edges: dict[str, set[str]] = {}
        self._in_edges: dict[str, set[str]] = {}

    # ---- 写入 ----

    def upsert_entity(self, entity: KGEntity) -> KGEntity:
        self.policy.check_entity(entity)
        with self._lock:
            existing = self._entities.get(entity.id)
            if existing is None:
                self._entities[entity.id] = entity.model_copy(deep=True)
                return self._entities[entity.id]
            merged = self._merge_entity(existing, entity)
            self._entities[entity.id] = merged
            return merged.model_copy(deep=True)

    def _merge_entity(self, existing: KGEntity, incoming: KGEntity) -> KGEntity:
        aliases = list(dict.fromkeys(existing.aliases + incoming.aliases))
        evidence = list(dict.fromkeys(existing.evidence_ids + incoming.evidence_ids))
        properties = {**existing.properties, **incoming.properties}
        status = (
            incoming.verification_status
            if _STATUS_STRENGTH[incoming.verification_status] > _STATUS_STRENGTH[existing.verification_status]
            else existing.verification_status
        )
        if status == VerificationStatus.VERIFIED and not evidence:
            raise GraphStoreError("cannot upgrade entity to verified without evidence")
        valid_from = min(
            [d for d in (existing.valid_from, incoming.valid_from) if d],
            default=None,
        )
        valid_to = max(
            [d for d in (existing.valid_to, incoming.valid_to) if d],
            default=None,
        )
        return existing.model_copy(
            update={
                "aliases": aliases,
                "evidence_ids": evidence,
                "properties": properties,
                "confidence": max(existing.confidence, incoming.confidence),
                "verification_status": status,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "county": existing.county or incoming.county,
            }
        )

    def upsert_relation(self, relation: KGRelation) -> KGRelation:
        source = self._entities.get(relation.source_entity_id)
        target = self._entities.get(relation.target_entity_id)
        if source is None or target is None:
            raise GraphStoreError(
                "relation endpoints must exist before upsert: "
                f"{relation.source_entity_id} / {relation.target_entity_id}"
            )
        self.policy.check_relation(relation, source, target)
        with self._lock:
            existing = self._relations.get(relation.id)
            if existing is not None:
                relation = self._merge_relation(existing, relation)
            self._relations[relation.id] = relation.model_copy(deep=True)
            self._out_edges.setdefault(relation.source_entity_id, set()).add(relation.id)
            self._in_edges.setdefault(relation.target_entity_id, set()).add(relation.id)
            return relation.model_copy(deep=True)

    def _merge_relation(self, existing: KGRelation, incoming: KGRelation) -> KGRelation:
        evidence = list(
            dict.fromkeys(existing.evidence_refs() + incoming.evidence_refs())
        )
        status = (
            incoming.verification_status
            if _STATUS_STRENGTH[incoming.verification_status] > _STATUS_STRENGTH[existing.verification_status]
            else existing.verification_status
        )
        if status == VerificationStatus.VERIFIED and not evidence:
            raise GraphStoreError("cannot upgrade relation to verified without evidence")
        return existing.model_copy(
            update={
                "evidence_ids": evidence,
                "source_evidence_id": existing.source_evidence_id or incoming.source_evidence_id,
                "properties": {**existing.properties, **incoming.properties},
                "confidence": max(existing.confidence, incoming.confidence),
                "verification_status": status,
                "valid_from": min(
                    [d for d in (existing.valid_from, incoming.valid_from) if d],
                    default=None,
                ),
                "valid_to": max(
                    [d for d in (existing.valid_to, incoming.valid_to) if d],
                    default=None,
                ),
                "quote": existing.quote or incoming.quote,
            }
        )

    # ---- 读取 ----

    def get_entity(self, entity_id: str) -> KGEntity | None:
        with self._lock:
            entity = self._entities.get(entity_id)
            return entity.model_copy(deep=True) if entity else None

    def find_entities(
        self,
        *,
        entity_type: EntityType | None = None,
        name: str | None = None,
        county: str | None = None,
        limit: int = 100,
    ) -> list[KGEntity]:
        needle = (name or "").strip()
        with self._lock:
            results: list[KGEntity] = []
            for entity in self._entities.values():
                if entity_type and entity.type != entity_type:
                    continue
                if county and entity.county != county:
                    continue
                if needle and not (
                    needle in entity.name
                    or any(needle in alias for alias in entity.aliases)
                ):
                    continue
                results.append(entity.model_copy(deep=True))
        results.sort(key=lambda e: (-e.confidence, e.name))
        return results[:limit]

    def get_relations(
        self,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        relationship_type: RelationshipType | None = None,
        include_inferred: bool = False,
        include_pending: bool = False,
        include_unverified: bool = False,
        as_of: datetime | None = None,
        limit: int = 1000,
    ) -> list[KGRelation]:
        statuses = self._visible_statuses(
            include_inferred=include_inferred,
            include_pending=include_pending,
            include_unverified=include_unverified,
        )
        with self._lock:
            if source_id:
                candidates = [
                    self._relations[rid] for rid in self._out_edges.get(source_id, set())
                ]
            elif target_id:
                candidates = [
                    self._relations[rid] for rid in self._in_edges.get(target_id, set())
                ]
            else:
                candidates = list(self._relations.values())
            results = [
                rel.model_copy(deep=True)
                for rel in candidates
                if rel.verification_status in statuses
                and (relationship_type is None or rel.relationship_type == relationship_type)
                and (source_id is None or rel.source_entity_id == source_id)
                and (target_id is None or rel.target_entity_id == target_id)
                # 与 Neo4j 适配器保持一致：只有显式传入 as_of 才做时点过滤。
                # 否则历史关系（valid_to 已过）仍可被读取，供时序查询使用。
                and (as_of is None or rel.is_active(as_of))
            ]
        results.sort(key=lambda r: (-r.confidence, r.relationship_type.value))
        return results[:limit]

    def neighbors(
        self,
        entity_id: str,
        *,
        depth: int = 1,
        relationship_types: Iterable[RelationshipType] | None = None,
        include_inferred: bool = False,
        limit: int = 200,
    ) -> Subgraph:
        depth = max(0, min(depth, 4))
        allowed_types = set(relationship_types) if relationship_types else None
        statuses = self._visible_statuses(
            include_inferred=include_inferred,
            include_pending=False,
            include_unverified=False,
        )
        with self._lock:
            if entity_id not in self._entities:
                return Subgraph()
            visited_entities = {entity_id}
            visited_relations: dict[str, KGRelation] = {}
            queue: deque[tuple[str, int]] = deque([(entity_id, 0)])
            truncated = False
            while queue:
                current, current_depth = queue.popleft()
                if current_depth >= depth:
                    continue
                rel_ids = set(self._out_edges.get(current, set())) | set(
                    self._in_edges.get(current, set())
                )
                for rel_id in rel_ids:
                    rel = self._relations.get(rel_id)
                    if rel is None or rel.verification_status not in statuses:
                        continue
                    if allowed_types and rel.relationship_type not in allowed_types:
                        continue
                    if len(visited_relations) >= limit:
                        truncated = True
                        break
                    visited_relations[rel.id] = rel
                    other = (
                        rel.target_entity_id
                        if rel.source_entity_id == current
                        else rel.source_entity_id
                    )
                    if other not in visited_entities:
                        visited_entities.add(other)
                        queue.append((other, current_depth + 1))
            entities = [
                self._entities[eid].model_copy(deep=True)
                for eid in visited_entities
                if eid in self._entities
            ]
            relations = [r.model_copy(deep=True) for r in visited_relations.values()]
        return Subgraph(
            entities=entities,
            relations=relations,
            evidence_ids=self._collect_evidence(entities, relations),
            truncated=truncated,
        )

    def shortest_path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 6,
        include_inferred: bool = False,
    ) -> list[KGRelation]:
        statuses = self._visible_statuses(
            include_inferred=include_inferred,
            include_pending=False,
            include_unverified=False,
        )
        with self._lock:
            if source_id not in self._entities or target_id not in self._entities:
                return []
            if source_id == target_id:
                return []
            queue: deque[tuple[str, list[KGRelation]]] = deque([(source_id, [])])
            visited = {source_id}
            while queue:
                current, path = queue.popleft()
                if len(path) >= max_depth:
                    continue
                for rel_id in self._out_edges.get(current, set()):
                    rel = self._relations.get(rel_id)
                    if rel is None or rel.verification_status not in statuses:
                        continue
                    if rel.target_entity_id == target_id:
                        return [r.model_copy(deep=True) for r in path + [rel]]
                    if rel.target_entity_id not in visited:
                        visited.add(rel.target_entity_id)
                        queue.append((rel.target_entity_id, path + [rel]))
            return []

    def county_subgraph(self, county: str, *, industry: str = "", limit: int = 200) -> Subgraph:
        with self._lock:
            seeds: list[str] = []
            for entity in self._entities.values():
                if entity.county == county:
                    seeds.append(entity.id)
                elif (
                    entity.type == EntityType.COUNTY
                    and (entity.name == county or county in entity.name)
                ):
                    seeds.append(entity.id)
            if industry:
                for entity in self._entities.values():
                    if entity.type in {
                        EntityType.INDUSTRY,
                        EntityType.INDUSTRY_SEGMENT,
                    } and (industry in entity.name or entity.name in industry):
                        seeds.append(entity.id)

            merged = Subgraph()
            if not seeds:
                return merged
            for seed in dict.fromkeys(seeds):
                merged = merged.merge(self.neighbors(seed, depth=2, limit=limit))
                if len(merged.entities) >= limit:
                    merged.truncated = True
                    break
            # 补齐关系端点，保证子图自洽
            by_id = {e.id: e for e in merged.entities}
            for relation in merged.relations:
                for endpoint in (relation.source_entity_id, relation.target_entity_id):
                    if endpoint not in by_id and endpoint in self._entities:
                        by_id[endpoint] = self._entities[endpoint].model_copy(deep=True)
            entities = list(by_id.values())[:limit]
            return Subgraph(
                entities=entities,
                relations=merged.relations,
                evidence_ids=self._collect_evidence(entities, merged.relations),
                truncated=merged.truncated or len(entities) >= limit,
            )

    def stats(self) -> dict[str, int]:
        with self._lock:
            by_type: dict[str, int] = {}
            for entity in self._entities.values():
                by_type[entity.type.value] = by_type.get(entity.type.value, 0) + 1
            verified = sum(
                1
                for r in self._relations.values()
                if r.verification_status == VerificationStatus.VERIFIED
            )
            return {
                "entities": len(self._entities),
                "relations": len(self._relations),
                "verified_relations": verified,
                **{f"type_{k}": v for k, v in by_type.items()},
            }

    def clear(self) -> None:
        with self._lock:
            self._entities.clear()
            self._relations.clear()
            self._out_edges.clear()
            self._in_edges.clear()


__all__ = ["InMemoryGraphStore"]
