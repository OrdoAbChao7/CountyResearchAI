"""知识图谱构建服务。

把「已抽取证据的原始资料」转成带证据绑定的实体-关系图。默认只写入
VERIFIED 关系；模型推断 (INFERRED) 一律拒绝落库，避免幻觉污染图谱。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..domain.intelligence import VerificationStatus
from ..knowledge_graph.entity_resolution.resolver import EntityResolver
from ..knowledge_graph.extraction.entity_extractor import EntityExtractor
from ..knowledge_graph.extraction.relation_extractor import RelationExtractor
from ..knowledge_graph.graph_store.base import GraphStore, GraphWriteError
from ..knowledge_graph.ontology.entities import EntityType, KGEntity
from ..knowledge_graph.ontology.relations import KGRelation, RelationshipType
from ..models import RawDoc
from .evidence_service import EvidenceService

logger = logging.getLogger(__name__)


@dataclass
class GraphBuildStats:
    docs_processed: int = 0
    entities_written: int = 0
    entities_merged: int = 0
    relations_written: int = 0
    relations_rejected: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "docs_processed": self.docs_processed,
            "entities_written": self.entities_written,
            "entities_merged": self.entities_merged,
            "relations_written": self.relations_written,
            "relations_rejected": self.relations_rejected,
            "errors": self.errors,
        }


class KnowledgeGraphBuilder:
    """从资料构建证据约束的产业图谱。"""

    def __init__(
        self,
        graph: GraphStore,
        entity_extractor: EntityExtractor,
        relation_extractor: RelationExtractor,
        resolver: EntityResolver | None = None,
        *,
        max_docs: int = 20,
        allow_inferred: bool = False,
    ) -> None:
        self._graph = graph
        self._entity_extractor = entity_extractor
        self._relation_extractor = relation_extractor
        self._resolver = resolver or EntityResolver()
        self.max_docs = max_docs
        self.allow_inferred = allow_inferred

    def build(
        self,
        docs: list[RawDoc],
        *,
        county: str,
        focus: str,
        evidence_service: EvidenceService,
    ) -> GraphBuildStats:
        stats = GraphBuildStats()
        evidence_by_url: dict[str, list] = {}
        for item in evidence_service.all():
            if item.url:
                evidence_by_url.setdefault(item.url, []).append(item)

        for doc in docs[: self.max_docs]:
            text = f"{doc.title}\n{doc.snippet}\n{doc.content}"
            if len(text.strip()) < 20:
                continue
            items = evidence_by_url.get(doc.url, [])
            evidence_ids = [item.id for item in items][:5]
            stats.docs_processed += 1
            try:
                entities = self._entity_extractor.extract(
                    text,
                    county=county,
                    focus=focus,
                    evidence_ids=evidence_ids,
                    source=f"graph_builder:{doc.source or 'web'}",
                )
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(f"entity extraction failed: {exc}")
                continue
            resolved = [self._resolve_and_write(entity, stats) for entity in entities]
            resolved = [e for e in resolved if e is not None]
            if len(resolved) < 2 or not evidence_ids:
                continue
            try:
                relations = self._relation_extractor.extract(
                    text,
                    resolved,
                    evidence_id=evidence_ids[0],
                    county=county,
                )
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(f"relation extraction failed: {exc}")
                continue
            for candidate in relations:
                relation = self._bind_evidence(candidate, evidence_service)
                if relation is None:
                    stats.relations_rejected += 1
                    continue
                if (
                    relation.verification_status != VerificationStatus.VERIFIED
                    and not self.allow_inferred
                ):
                    stats.relations_rejected += 1
                    continue
                try:
                    self._graph.upsert_relation(relation)
                    stats.relations_written += 1
                except (GraphWriteError, Exception) as exc:  # noqa: BLE001
                    stats.relations_rejected += 1
                    stats.errors.append(f"relation rejected: {exc}")
        return stats

    # ---- 内部 ----

    def _resolve_and_write(
        self, entity: KGEntity, stats: GraphBuildStats
    ) -> KGEntity | None:
        existing = self._graph.find_entities(
            entity_type=entity.type, county=entity.county or None, limit=100
        )
        resolution = self._resolver.resolve(entity, existing)
        if resolution.matched and resolution.canonical is not None:
            merged = self._resolver.merge(resolution.canonical, entity)
            try:
                written = self._graph.upsert_entity(merged)
                stats.entities_merged += 1
                return written
            except Exception as exc:  # noqa: BLE001
                stats.errors.append(f"entity merge failed: {exc}")
                return resolution.canonical
        try:
            written = self._graph.upsert_entity(entity)
            stats.entities_written += 1
            return written
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(f"entity write rejected: {exc}")
            return None

    @staticmethod
    def _bind_evidence(
        relation: KGRelation, evidence_service: EvidenceService
    ) -> KGRelation | None:
        refs = [r for r in relation.evidence_refs() if evidence_service.get(r) is not None]
        if not refs:
            return None
        status = relation.verification_status
        if status == VerificationStatus.VERIFIED and not refs:
            return None
        return relation.model_copy(
            update={
                "source_evidence_id": relation.source_evidence_id
                if relation.source_evidence_id in refs
                else refs[0],
                "evidence_ids": refs,
            }
        )


def seed_core_graph(
    graph: GraphStore,
    *,
    county: str,
    focus: str,
    evidence_ids: list[str],
) -> None:
    """写入县域与主导产业基础节点（仅在拥有证据时）。"""
    if not county or not evidence_ids:
        return
    county_entity = KGEntity(
        type=EntityType.COUNTY,
        name=county,
        evidence_ids=evidence_ids[:3],
        confidence=0.9,
        verification_status=VerificationStatus.VERIFIED,
        source="core_seed",
    )
    graph.upsert_entity(county_entity)
    if not focus:
        return
    industry = KGEntity(
        type=EntityType.INDUSTRY,
        name=focus,
        county=county,
        evidence_ids=evidence_ids[:3],
        confidence=0.85,
        verification_status=VerificationStatus.VERIFIED,
        source="core_seed",
    )
    graph.upsert_entity(industry)
    relation = KGRelation(
        source_entity_id=county_entity.id,
        target_entity_id=industry.id,
        relationship_type=RelationshipType.HAS_INDUSTRY,
        source_evidence_id=evidence_ids[0],
        confidence=0.85,
        verification_status=VerificationStatus.VERIFIED,
        extracted_by="core_seed",
    )
    try:
        graph.upsert_relation(relation)
    except Exception as exc:  # noqa: BLE001
        logger.warning("核心图谱关系写入失败 | err=%s", exc)


__all__ = ["GraphBuildStats", "KnowledgeGraphBuilder", "seed_core_graph"]
