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
            # Only verified evidence may enter the graph.  An Evidence ID that
            # merely exists is not enough; graph facts must trace to verified
            # source text.
            evidence_ids = [
                item.id for item in items if item.verification_status == "verified"
            ][:5]
            if not evidence_ids:
                continue
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
        """Bind a relation to verified evidence whose text contains its quote.

        The extractor receives one document-level Evidence ID, but the quote
        may belong to a different evidence item from the same document.  Search
        all verified evidence for the quote instead of blindly trusting the
        first ID.
        """
        quote = (relation.quote or "").strip()
        if not quote:
            return None
        verified_items = [
            item
            for item in evidence_service.all()
            if item.verification_status == "verified"
        ]
        supporting = [
            item
            for item in verified_items
            if quote in f"{item.claim}\n{item.snippet}\n{item.title}"
        ]
        if not supporting:
            return None
        preferred = supporting[0]
        for item in supporting:
            if item.id in relation.evidence_refs():
                preferred = item
                break
        return relation.model_copy(
            update={
                "source_evidence_id": preferred.id,
                "evidence_ids": [item.id for item in supporting[:5]],
            }
        )


def _evidence_text(item: object) -> str:
    return "\n".join(
        str(part)
        for part in (
            getattr(item, "claim", ""),
            getattr(item, "snippet", ""),
            getattr(item, "title", ""),
        )
        if part
    )


def seed_core_graph(
    graph: GraphStore,
    *,
    county: str,
    focus: str,
    evidence_ids: list[str],
    evidence_service: EvidenceService,
) -> None:
    """写入县域与主导产业基础节点（仅在已验证证据支持时）。

    ``evidence_ids`` 仅作为候选；函数会重新检查 ID 是否存在、是否已验证、
    以及证据文本是否真的提到县域名（和产业名）。不存在或未验证的 ID
    绝不会生成 VERIFIED 核心关系。
    """
    if not county or not evidence_ids:
        return
    county_items = []
    for evidence_id in evidence_ids:
        item = evidence_service.get(evidence_id)
        if (
            item is not None
            and item.verification_status == "verified"
            and county in _evidence_text(item)
        ):
            county_items.append(item)
    if not county_items:
        return

    county_entity = KGEntity(
        type=EntityType.COUNTY,
        name=county,
        evidence_ids=[item.id for item in county_items[:3]],
        confidence=0.9,
        verification_status=VerificationStatus.VERIFIED,
        source="core_seed",
    )
    graph.upsert_entity(county_entity)
    if not focus:
        return

    industry_items = [
        item for item in county_items if focus in _evidence_text(item)
    ]
    if not industry_items:
        return
    industry = KGEntity(
        type=EntityType.INDUSTRY,
        name=focus,
        county=county,
        evidence_ids=[item.id for item in industry_items[:3]],
        confidence=0.85,
        verification_status=VerificationStatus.VERIFIED,
        source="core_seed",
    )
    graph.upsert_entity(industry)
    relation = KGRelation(
        source_entity_id=county_entity.id,
        target_entity_id=industry.id,
        relationship_type=RelationshipType.HAS_INDUSTRY,
        source_evidence_id=industry_items[0].id,
        confidence=0.85,
        verification_status=VerificationStatus.VERIFIED,
        quote=(industry_items[0].snippet or industry_items[0].claim)[:300],
        extracted_by="core_seed",
    )
    try:
        graph.upsert_relation(relation)
    except Exception as exc:  # noqa: BLE001
        logger.warning("核心图谱关系写入失败 | err=%s", exc)


__all__ = ["GraphBuildStats", "KnowledgeGraphBuilder", "seed_core_graph"]
