"""图存储端口与写入策略。

所有图数据库适配器（Neo4j / InMemory）实现同一 ``GraphStore`` 接口。
写入策略在存储层统一执行，保证「无证据不得标记为已验证」。
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel, Field

from ...domain.intelligence import VerificationStatus
from ..ontology.entities import EntityType, KGEntity
from ..ontology.relations import KGRelation, RelationshipType
from ..ontology.schema import OntologySchema, default_schema


class GraphStoreError(RuntimeError):
    """图存储不可用或查询失败。"""


class GraphWriteError(ValueError):
    """关系/实体违反证据或本体约束。"""


class Subgraph(BaseModel):
    """子图查询结果。"""

    entities: list[KGEntity] = Field(default_factory=list)
    relations: list[KGRelation] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    truncated: bool = False

    def entity(self, entity_id: str) -> KGEntity | None:
        return next((e for e in self.entities if e.id == entity_id), None)

    def merge(self, other: Subgraph) -> Subgraph:
        entities = {e.id: e for e in self.entities}
        for entity in other.entities:
            entities.setdefault(entity.id, entity)
        relations = {r.id: r for r in self.relations}
        for relation in other.relations:
            relations.setdefault(relation.id, relation)
        evidence = list(dict.fromkeys(self.evidence_ids + other.evidence_ids))
        return Subgraph(
            entities=list(entities.values()),
            relations=list(relations.values()),
            evidence_ids=evidence,
            truncated=self.truncated or other.truncated,
        )


class GraphWritePolicy:
    """图谱写入的硬约束。

    - VERIFIED 关系必须绑定证据（模型层已校验，这里再兜底）
    - 默认拒绝写入 INFERRED / UNVERIFIED 关系，除非显式 ``allow_inferred``
    - 实体同样禁止无证据却标记 VERIFIED
    """

    def __init__(
        self,
        schema: OntologySchema | None = None,
        *,
        allow_inferred: bool = False,
    ) -> None:
        self.schema = schema or default_schema()
        self.allow_inferred = allow_inferred

    def check_entity(self, entity: KGEntity) -> None:
        if entity.verification_status == VerificationStatus.VERIFIED and not entity.evidence_ids:
            raise GraphWriteError("verified entity requires evidence_ids")
        if (
            entity.verification_status in {VerificationStatus.INFERRED, VerificationStatus.UNVERIFIED}
            and not self.allow_inferred
        ):
            raise GraphWriteError(
                f"refusing to persist {entity.verification_status.value} entity "
                f"'{entity.name}' without allow_inferred"
            )

    def check_relation(
        self,
        relation: KGRelation,
        source_entity: KGEntity | None,
        target_entity: KGEntity | None,
    ) -> list[str]:
        if relation.verification_status == VerificationStatus.VERIFIED and not relation.evidence_refs():
            raise GraphWriteError("verified relation requires evidence reference")
        if (
            relation.verification_status
            in {VerificationStatus.INFERRED, VerificationStatus.UNVERIFIED}
            and not self.allow_inferred
        ):
            raise GraphWriteError(
                f"refusing to persist {relation.verification_status.value} relation "
                f"{relation.source_entity_id} -{relation.relationship_type.value}-> "
                f"{relation.target_entity_id} without allow_inferred"
            )
        return self.schema.validate_relation(relation, source_entity, target_entity)


class GraphStore(ABC):
    """知识图谱存储端口。"""

    name = "base"

    def __init__(self, policy: GraphWritePolicy | None = None) -> None:
        self.policy = policy or GraphWritePolicy()
        self._lock = threading.RLock()

    # ---- 写入 ----

    @abstractmethod
    def upsert_entity(self, entity: KGEntity) -> KGEntity: ...

    @abstractmethod
    def upsert_relation(self, relation: KGRelation) -> KGRelation: ...

    # ---- 读取 ----

    @abstractmethod
    def get_entity(self, entity_id: str) -> KGEntity | None: ...

    @abstractmethod
    def find_entities(
        self,
        *,
        entity_type: EntityType | None = None,
        name: str | None = None,
        county: str | None = None,
        limit: int = 100,
    ) -> list[KGEntity]: ...

    @abstractmethod
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
    ) -> list[KGRelation]: ...

    @abstractmethod
    def neighbors(
        self,
        entity_id: str,
        *,
        depth: int = 1,
        relationship_types: Iterable[RelationshipType] | None = None,
        include_inferred: bool = False,
        limit: int = 200,
    ) -> Subgraph: ...

    @abstractmethod
    def shortest_path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 6,
        include_inferred: bool = False,
    ) -> list[KGRelation]: ...

    @abstractmethod
    def county_subgraph(self, county: str, *, industry: str = "", limit: int = 200) -> Subgraph: ...

    @abstractmethod
    def stats(self) -> dict[str, int]: ...

    @abstractmethod
    def clear(self) -> None: ...

    # ---- 共用辅助 ----

    def _visible_statuses(
        self,
        *,
        include_inferred: bool,
        include_pending: bool,
        include_unverified: bool,
    ) -> set[VerificationStatus]:
        statuses = {VerificationStatus.VERIFIED}
        if include_inferred:
            statuses.add(VerificationStatus.INFERRED)
        if include_pending:
            statuses.add(VerificationStatus.PENDING)
        if include_unverified:
            statuses.add(VerificationStatus.UNVERIFIED)
        return statuses

    @staticmethod
    def _collect_evidence(entities: Iterable[KGEntity], relations: Iterable[KGRelation]) -> list[str]:
        ids: list[str] = []
        for entity in entities:
            ids.extend(entity.evidence_ids)
        for relation in relations:
            ids.extend(relation.evidence_refs())
        return list(dict.fromkeys(i for i in ids if i))


__all__ = [
    "GraphStore",
    "GraphStoreError",
    "GraphWriteError",
    "GraphWritePolicy",
    "Subgraph",
]
