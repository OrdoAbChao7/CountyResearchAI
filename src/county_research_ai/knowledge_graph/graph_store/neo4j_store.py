"""Neo4j 图存储适配器。

- 只有配置 ``graph.backend=neo4j`` 且驱动可用时才会实例化。
- 所有实体写入 ``:KGEntity`` 标签；关系写入 ``:RELATED`` 边并通过
  ``relationship_type`` 属性表达 13 种产业关系，避免动态关系类型注入。
- 读写全部参数化，路径长度等结构参数经过整数白名单校验后内联。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from ...domain.intelligence import VerificationStatus
from ..ontology.entities import EntityType, KGEntity
from ..ontology.relations import KGRelation, RelationshipType
from .base import GraphStore, GraphStoreError, GraphWritePolicy, Subgraph

logger = logging.getLogger(__name__)


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class Neo4jGraphStore(GraphStore):
    """基于 Neo4j 的持久化产业知识图谱。"""

    name = "neo4j"

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        *,
        database: str = "neo4j",
        policy: GraphWritePolicy | None = None,
        connection_timeout: int = 10,
    ) -> None:
        super().__init__(policy)
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover - 取决于可选依赖
            raise GraphStoreError(
                "neo4j driver is not installed; pip install 'county-research-ai[graph]'"
            ) from exc

        try:
            self._driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                connection_timeout=connection_timeout,
            )
            self._driver.verify_connectivity()
        except Exception as exc:  # noqa: BLE001
            raise GraphStoreError(f"cannot connect to Neo4j at {uri}: {exc}") from exc
        self._database = database
        self._ensure_schema()

    # ---- schema & lifecycle ----

    def _ensure_schema(self) -> None:
        statements = [
            "CREATE CONSTRAINT kg_entity_id IF NOT EXISTS "
            "FOR (e:KGEntity) REQUIRE e.id IS UNIQUE",
            "CREATE INDEX kg_entity_name IF NOT EXISTS FOR (e:KGEntity) ON (e.name)",
            "CREATE INDEX kg_entity_county IF NOT EXISTS FOR (e:KGEntity) ON (e.county)",
            "CREATE INDEX kg_entity_type IF NOT EXISTS FOR (e:KGEntity) ON (e.entity_type)",
            "CREATE INDEX kg_entity_domain IF NOT EXISTS FOR (e:KGEntity) ON (e.domain)",
        ]
        try:
            with self._driver.session(database=self._database) as session:
                for stmt in statements:
                    session.run(stmt).consume()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Neo4j schema 初始化失败（继续运行） | err=%s", exc)

    def close(self) -> None:
        self._driver.close()

    def _run(self, query: str, **params: Any) -> list[dict[str, Any]]:
        try:
            with self._driver.session(database=self._database) as session:
                return [dict(record) for record in session.run(query, **params)]
        except Exception as exc:  # noqa: BLE001
            raise GraphStoreError(f"neo4j query failed: {exc}") from exc

    # ---- 写入 ----

    def upsert_entity(self, entity: KGEntity) -> KGEntity:
        self.policy.check_entity(entity)
        self._run(
            """
            MERGE (e:KGEntity {id: $id})
            SET e.entity_type = $entity_type,
                e.name = $name,
                e.aliases = $aliases,
                e.county = $county,
                e.domain = 'industrial',
                e.properties = $properties,
                e.evidence_ids = $evidence_ids,
                e.confidence = $confidence,
                e.verification_status = $verification_status,
                e.valid_from = $valid_from,
                e.valid_to = $valid_to,
                e.observed_at = $observed_at,
                e.source = $source,
                e.updated_at = $observed_at
            """,
            id=entity.id,
            entity_type=entity.type.value,
            name=entity.name,
            aliases=entity.aliases,
            county=entity.county,
            properties=json.dumps(entity.properties, ensure_ascii=False),
            evidence_ids=entity.evidence_ids,
            confidence=entity.confidence,
            verification_status=entity.verification_status.value,
            valid_from=_iso(entity.valid_from),
            valid_to=_iso(entity.valid_to),
            observed_at=_iso(entity.observed_at),
            source=entity.source,
        )
        return entity

    def upsert_relation(self, relation: KGRelation) -> KGRelation:
        source = self.get_entity(relation.source_entity_id)
        target = self.get_entity(relation.target_entity_id)
        if source is None or target is None:
            raise GraphStoreError("relation endpoints must exist before upsert")
        self.policy.check_relation(relation, source, target)
        self._run(
            """
            MATCH (a:KGEntity {id: $source_entity_id})
            MATCH (b:KGEntity {id: $target_entity_id})
            MERGE (a)-[r:RELATED {id: $id}]->(b)
            SET r.relationship_type = $relationship_type,
                r.source_evidence_id = $source_evidence_id,
                r.evidence_ids = $evidence_ids,
                r.confidence = $confidence,
                r.verification_status = $verification_status,
                r.valid_from = $valid_from,
                r.valid_to = $valid_to,
                r.observed_at = $observed_at,
                r.properties = $properties,
                r.quote = $quote,
                r.extracted_by = $extracted_by
            """,
            id=relation.id,
            source_entity_id=relation.source_entity_id,
            target_entity_id=relation.target_entity_id,
            relationship_type=relation.relationship_type.value,
            source_evidence_id=relation.source_evidence_id,
            evidence_ids=relation.evidence_refs(),
            confidence=relation.confidence,
            verification_status=relation.verification_status.value,
            valid_from=_iso(relation.valid_from),
            valid_to=_iso(relation.valid_to),
            observed_at=_iso(relation.observed_at),
            properties=json.dumps(relation.properties, ensure_ascii=False),
            quote=relation.quote,
            extracted_by=relation.extracted_by,
        )
        return relation

    # ---- 读取 ----

    @staticmethod
    def _entity_from_row(row: dict[str, Any]) -> KGEntity:
        properties = row.get("properties") or "{}"
        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except json.JSONDecodeError:
                properties = {}
        return KGEntity.model_construct(
            id=row["id"],
            type=EntityType(row["entity_type"]),
            name=row["name"],
            aliases=row.get("aliases") or [],
            county=row.get("county") or "",
            properties=properties,
            evidence_ids=row.get("evidence_ids") or [],
            confidence=row.get("confidence", 0.5),
            verification_status=VerificationStatus(row.get("verification_status", "unverified")),
            valid_from=_parse_dt(row.get("valid_from")),
            valid_to=_parse_dt(row.get("valid_to")),
            observed_at=_parse_dt(row.get("observed_at")) or datetime.now(timezone.utc),
            source=row.get("source") or "",
        )

    @staticmethod
    def _relation_from_row(row: dict[str, Any]) -> KGRelation:
        properties = row.get("properties") or "{}"
        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except json.JSONDecodeError:
                properties = {}
        evidence = row.get("evidence_ids") or []
        return KGRelation.model_construct(
            id=row["id"],
            source_entity_id=row["source_entity_id"],
            target_entity_id=row["target_entity_id"],
            relationship_type=RelationshipType(row["relationship_type"]),
            source_evidence_id=row.get("source_evidence_id") or "",
            evidence_ids=evidence,
            confidence=row.get("confidence", 0.5),
            verification_status=VerificationStatus(row.get("verification_status", "unverified")),
            valid_from=_parse_dt(row.get("valid_from")),
            valid_to=_parse_dt(row.get("valid_to")),
            observed_at=_parse_dt(row.get("observed_at")) or datetime.now(timezone.utc),
            properties=properties,
            quote=row.get("quote") or "",
            extracted_by=row.get("extracted_by") or "",
        )

    def get_entity(self, entity_id: str) -> KGEntity | None:
        rows = self._run(
            "MATCH (e:KGEntity {id: $id}) RETURN e", id=entity_id
        )
        if not rows:
            return None
        node = rows[0]["e"]
        return self._entity_from_row(dict(node))

    def find_entities(
        self,
        *,
        entity_type: EntityType | None = None,
        name: str | None = None,
        county: str | None = None,
        limit: int = 100,
    ) -> list[KGEntity]:
        clauses = []
        params: dict[str, Any] = {"limit": int(limit)}
        if entity_type:
            clauses.append("e.entity_type = $entity_type")
            params["entity_type"] = entity_type.value
        if county:
            clauses.append("e.county = $county")
            params["county"] = county
        if name:
            clauses.append("(e.name CONTAINS $name OR any(a IN e.aliases WHERE a CONTAINS $name))")
            params["name"] = name
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._run(
            f"MATCH (e:KGEntity) {where} RETURN e ORDER BY e.confidence DESC LIMIT $limit",
            **params,
        )
        return [self._entity_from_row(dict(row["e"])) for row in rows]

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
        statuses = [s.value for s in self._visible_statuses(
            include_inferred=include_inferred,
            include_pending=include_pending,
            include_unverified=include_unverified,
        )]
        params: dict[str, Any] = {"statuses": statuses, "limit": int(limit)}
        clauses = ["r.verification_status IN $statuses"]
        if source_id:
            clauses.append("a.id = $source_id")
            params["source_id"] = source_id
        if target_id:
            clauses.append("b.id = $target_id")
            params["target_id"] = target_id
        if relationship_type:
            clauses.append("r.relationship_type = $relationship_type")
            params["relationship_type"] = relationship_type.value
        if as_of is not None:
            # Apply the time filter in Cypher, *before* LIMIT.  Filtering after
            # LIMIT can drop valid historical relations when the graph has more
            # recent relations than the limit.
            clauses.append(
                "(r.valid_from IS NULL OR r.valid_from = '' OR r.valid_from <= $as_of)"
            )
            clauses.append(
                "(r.valid_to IS NULL OR r.valid_to = '' OR r.valid_to > $as_of)"
            )
            params["as_of"] = _iso(as_of)
        rows = self._run(
            "MATCH (a:KGEntity)-[r:RELATED]->(b:KGEntity) "
            f"WHERE {' AND '.join(clauses)} "
            "RETURN a.id AS source_entity_id, b.id AS target_entity_id, r "
            "ORDER BY r.confidence DESC LIMIT $limit",
            **params,
        )
        relations: list[KGRelation] = []
        for row in rows:
            payload = dict(row["r"])
            payload.setdefault("id", payload.get("id", ""))
            payload["source_entity_id"] = row["source_entity_id"]
            payload["target_entity_id"] = row["target_entity_id"]
            rel = self._relation_from_row(payload)
            # Defensive re-check in case a backend stores dates in another
            # format; the Cypher filter is the primary guard.
            if as_of and not rel.is_active(as_of):
                continue
            relations.append(rel)
        return relations

    def neighbors(
        self,
        entity_id: str,
        *,
        depth: int = 1,
        relationship_types: Iterable[RelationshipType] | None = None,
        include_inferred: bool = False,
        limit: int = 200,
    ) -> Subgraph:
        depth = max(0, min(int(depth), 4))
        if depth == 0:
            entity = self.get_entity(entity_id)
            return Subgraph(entities=[entity] if entity else [], evidence_ids=entity.evidence_ids if entity else [])
        statuses = [s.value for s in self._visible_statuses(
            include_inferred=include_inferred,
            include_pending=False,
            include_unverified=False,
        )]
        params: dict[str, Any] = {
            "id": entity_id,
            "statuses": statuses,
            "limit": int(limit),
        }
        type_clause = ""
        if relationship_types:
            type_clause = "AND all(x IN relationships(p) WHERE x.relationship_type IN $types) "
            params["types"] = [t.value for t in relationship_types]
        rows = self._run(
            "MATCH p=(start:KGEntity {id: $id})-[:RELATED*1.." + str(depth) + "]-(n) "
            "WHERE all(x IN relationships(p) WHERE x.verification_status IN $statuses) "
            + type_clause +
            "RETURN p LIMIT $limit",
            **params,
        )
        entities: dict[str, KGEntity] = {}
        relations: dict[str, KGRelation] = {}
        for row in rows:
            path = row["p"]
            for node in path.nodes:
                entity = self._entity_from_row(dict(node))
                entities[entity.id] = entity
            for rel in path.relationships:
                payload = dict(rel)
                source_id = rel.start_node["id"] if not isinstance(rel.start_node, dict) else rel.start_node.get("id")
                target_id = rel.end_node["id"] if not isinstance(rel.end_node, dict) else rel.end_node.get("id")
                payload["source_entity_id"] = source_id
                payload["target_entity_id"] = target_id
                parsed = self._relation_from_row(payload)
                relations[parsed.id] = parsed
        seed = self.get_entity(entity_id)
        if seed:
            entities.setdefault(seed.id, seed)
        entity_list = list(entities.values())
        relation_list = list(relations.values())
        return Subgraph(
            entities=entity_list,
            relations=relation_list,
            evidence_ids=self._collect_evidence(entity_list, relation_list),
            truncated=len(relation_list) >= limit,
        )

    def shortest_path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 6,
        include_inferred: bool = False,
    ) -> list[KGRelation]:
        depth = max(1, min(int(max_depth), 10))
        statuses = [s.value for s in self._visible_statuses(
            include_inferred=include_inferred,
            include_pending=False,
            include_unverified=False,
        )]
        rows = self._run(
            "MATCH (a:KGEntity {id: $source}), (b:KGEntity {id: $target}), "
            "p = shortestPath((a)-[:RELATED*.." + str(depth) + "]->(b)) "
            "WHERE all(x IN relationships(p) WHERE x.verification_status IN $statuses) "
            "RETURN p LIMIT 1",
            source=source_id,
            target=target_id,
            statuses=statuses,
        )
        if not rows:
            return []
        path = rows[0]["p"]
        relations: list[KGRelation] = []
        for rel in path.relationships:
            payload = dict(rel)
            payload["source_entity_id"] = rel.start_node["id"]
            payload["target_entity_id"] = rel.end_node["id"]
            relations.append(self._relation_from_row(payload))
        return relations

    def county_subgraph(self, county: str, *, industry: str = "", limit: int = 200) -> Subgraph:
        seeds = self.find_entities(county=county, limit=limit)
        county_entities = self.find_entities(entity_type=EntityType.COUNTY, name=county, limit=5)
        if industry:
            for entity_type in (EntityType.INDUSTRY, EntityType.INDUSTRY_SEGMENT):
                seeds.extend(self.find_entities(entity_type=entity_type, name=industry, limit=10))
        seeds.extend(county_entities)
        merged = Subgraph()
        for seed in {e.id: e for e in seeds}.values():
            merged = merged.merge(self.neighbors(seed.id, depth=2, limit=limit))
            if len(merged.entities) >= limit:
                merged.truncated = True
                break
        return merged

    def stats(self) -> dict[str, int]:
        rows = self._run(
            "MATCH (e:KGEntity) WITH count(e) AS entities "
            "CALL { MATCH ()-[r:RELATED]->() RETURN count(r) AS relations } "
            "CALL { MATCH ()-[r:RELATED]->() WHERE r.verification_status = 'verified' "
            "RETURN count(r) AS verified } "
            "RETURN entities, relations, verified"
        )
        if not rows:
            return {"entities": 0, "relations": 0, "verified_relations": 0}
        row = rows[0]
        return {
            "entities": int(row["entities"]),
            "relations": int(row["relations"]),
            "verified_relations": int(row["verified"]),
        }

    def clear(self) -> None:
        self._run("MATCH (n:KGEntity) DETACH DELETE n")


__all__ = ["Neo4jGraphStore"]
