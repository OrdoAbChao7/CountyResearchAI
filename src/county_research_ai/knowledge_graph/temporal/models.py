"""时序产业知识图谱(Star C)数据模型与 as-of 查询接口。

当前阶段只实现基于关系 ``valid_from`` / ``valid_to`` / ``observed_at``
的时点查询与差异比较；未来可无缝替换为 Graphiti / 双时态存储。
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from ...domain.intelligence import VerificationStatus
from ..graph_store.base import GraphStore, Subgraph
from ..ontology.entities import KGEntity
from ..ontology.relations import KGRelation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChangeType(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    INVALIDATED = "invalidated"
    OBSERVED = "observed"


class EntityVersion(BaseModel):
    entity_id: str
    entity: KGEntity
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    observed_at: datetime = Field(default_factory=_utcnow)
    change_type: ChangeType = ChangeType.OBSERVED


class RelationVersion(BaseModel):
    relation_id: str
    relation: KGRelation
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    observed_at: datetime = Field(default_factory=_utcnow)
    change_type: ChangeType = ChangeType.OBSERVED


class TemporalSnapshot(BaseModel):
    as_of: datetime
    entities: list[KGEntity] = Field(default_factory=list)
    relations: list[KGRelation] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    def to_subgraph(self) -> Subgraph:
        return Subgraph(
            entities=self.entities,
            relations=self.relations,
            evidence_ids=self.evidence_ids,
        )


class TemporalDiff(BaseModel):
    before: datetime
    after: datetime
    added_relations: list[KGRelation] = Field(default_factory=list)
    removed_relations: list[KGRelation] = Field(default_factory=list)
    changed_relations: list[KGRelation] = Field(default_factory=list)
    added_entities: list[KGEntity] = Field(default_factory=list)
    removed_entities: list[KGEntity] = Field(default_factory=list)


class TemporalQuery:
    """基于当前图存储的时点查询。

    说明：InMemoryGraphStore 只保留每个关系的最新版本；若关系带有
    ``valid_from/valid_to``，可正确回答「某时点是否成立」。完整的历史
    版本链需要 Neo4j 版本节点或 Graphiti，接口已在 ``RelationVersion`` 中预留。
    """

    def __init__(self, graph: GraphStore) -> None:
        self._graph = graph

    def relations_as_of(
        self,
        as_of: datetime,
        *,
        county: str = "",
        include_inferred: bool = False,
    ) -> list[KGRelation]:
        relations = self._graph.get_relations(
            include_inferred=include_inferred,
            include_pending=False,
            include_unverified=False,
            as_of=as_of,
            limit=5000,
        )
        if not county:
            return relations
        county_entity_ids = {
            e.id
            for e in self._graph.find_entities(county=county, limit=5000)
        } | {
            e.id
            for e in self._graph.find_entities(name=county, limit=50)
        }
        return [
            r
            for r in relations
            if r.source_entity_id in county_entity_ids or r.target_entity_id in county_entity_ids
        ]

    def snapshot_as_of(self, as_of: datetime, *, county: str = "") -> TemporalSnapshot:
        relations = self.relations_as_of(as_of, county=county)
        entity_ids = {
            rid for rel in relations for rid in (rel.source_entity_id, rel.target_entity_id)
        }
        entities = [e for e in (self._graph.get_entity(eid) for eid in entity_ids) if e]
        evidence: list[str] = []
        for entity in entities:
            evidence.extend(entity.evidence_ids)
        for relation in relations:
            evidence.extend(relation.evidence_refs())
        return TemporalSnapshot(
            as_of=as_of,
            entities=entities,
            relations=relations,
            evidence_ids=list(dict.fromkeys(i for i in evidence if i)),
        )

    def diff(self, before: datetime, after: datetime, *, county: str = "") -> TemporalDiff:
        old = {r.id: r for r in self.relations_as_of(before, county=county)}
        new = {r.id: r for r in self.relations_as_of(after, county=county)}
        added = [new[rid] for rid in new.keys() - old.keys()]
        removed = [old[rid] for rid in old.keys() - new.keys()]
        changed = [
            new[rid]
            for rid in new.keys() & old.keys()
            if new[rid].model_dump(exclude={"observed_at"}) != old[rid].model_dump(exclude={"observed_at"})
        ]
        old_entities = {
            e.id: e for e in self.snapshot_as_of(before, county=county).entities
        }
        new_entities = {
            e.id: e for e in self.snapshot_as_of(after, county=county).entities
        }
        return TemporalDiff(
            before=before,
            after=after,
            added_relations=added,
            removed_relations=removed,
            changed_relations=changed,
            added_entities=[new_entities[i] for i in new_entities.keys() - old_entities.keys()],
            removed_entities=[old_entities[i] for i in old_entities.keys() - new_entities.keys()],
        )

    def entity_history(self, entity_id: str) -> list[RelationVersion]:
        relations = self._graph.get_relations(
            source_id=entity_id,
            include_inferred=True,
            include_pending=True,
            include_unverified=True,
            limit=5000,
        ) + self._graph.get_relations(
            target_id=entity_id,
            include_inferred=True,
            include_pending=True,
            include_unverified=True,
            limit=5000,
        )
        return [
            RelationVersion(
                relation_id=r.id,
                relation=r,
                valid_from=r.valid_from,
                valid_to=r.valid_to,
                observed_at=r.observed_at,
                change_type=(
                    ChangeType.INVALIDATED
                    if r.valid_to and r.valid_to <= datetime.now(timezone.utc)
                    else ChangeType.OBSERVED
                ),
            )
            for r in relations
        ]

    def verified_relation_count(self, as_of: datetime) -> int:
        return sum(
            1
            for r in self.relations_as_of(as_of)
            if r.verification_status == VerificationStatus.VERIFIED
        )


__all__ = [
    "ChangeType",
    "EntityVersion",
    "RelationVersion",
    "TemporalDiff",
    "TemporalQuery",
    "TemporalSnapshot",
]
