"""GraphRAG 检索器：问题 → 种子实体 → 多跳子图 → 证据集合。"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..graph_store.base import GraphStore, Subgraph
from ..ontology.entities import EntityType, KGEntity

_CHUNK_RE = re.compile(r"[一-龥A-Za-z0-9]{2,}")
_STOPWORDS = {
    "什么", "哪些", "如何", "是否", "以及", "这个", "那个", "情况", "分析",
    "研究", "产业", "企业", "发展", "现状", "问题", "相关", "进行", "可以",
    "我们", "该县", "全县", "介绍", "一下", "报告",
}

_TYPE_WEIGHT = {
    EntityType.INDUSTRY: 1.6,
    EntityType.INDUSTRY_SEGMENT: 1.5,
    EntityType.ENTERPRISE: 1.3,
    EntityType.INDUSTRIAL_PARK: 1.2,
    EntityType.POLICY: 1.1,
    EntityType.TECHNOLOGY: 1.1,
    EntityType.PATENT: 1.0,
    EntityType.PRODUCT: 1.0,
    EntityType.MATERIAL: 1.0,
    EntityType.INSTITUTION: 1.0,
    EntityType.COUNTY: 0.8,
    EntityType.INDICATOR: 0.7,
    EntityType.EVIDENCE: 0.5,
}


class RetrievedContext(BaseModel):
    question: str = ""
    county: str = ""
    focus: str = ""
    entities: list[KGEntity] = Field(default_factory=list)
    relations: list = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    matched_entities: list[dict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    truncated: bool = False

    def to_subgraph(self) -> Subgraph:
        return Subgraph(
            entities=self.entities,
            relations=self.relations,
            evidence_ids=self.evidence_ids,
            truncated=self.truncated,
        )

    def is_empty(self) -> bool:
        return not self.entities and not self.relations


class GraphRetriever:
    """基于实体匹配 + 多跳邻居扩展的图谱检索。"""

    def __init__(
        self,
        graph: GraphStore,
        *,
        max_hops: int = 2,
        seed_limit: int = 6,
        entity_limit: int = 60,
    ) -> None:
        self._graph = graph
        self.max_hops = max_hops
        self.seed_limit = seed_limit
        self.entity_limit = entity_limit

    @staticmethod
    def _terms(text: str) -> list[str]:
        chunks = _CHUNK_RE.findall(text or "")
        terms: list[str] = []
        for chunk in chunks:
            if chunk in _STOPWORDS:
                continue
            terms.append(chunk)
            # 长中文串补充 2-4 字滑窗，提升召回
            if len(chunk) > 4:
                for size in (2, 3, 4):
                    for idx in range(0, len(chunk) - size + 1):
                        piece = chunk[idx: idx + size]
                        if piece not in _STOPWORDS:
                            terms.append(piece)
        return list(dict.fromkeys(terms))[:80]

    def _score(self, entity: KGEntity, question: str, terms: list[str], focus: str) -> float:
        score = _TYPE_WEIGHT.get(entity.type, 0.8) * max(entity.confidence, 0.2)
        name = entity.name
        if name and name in question:
            score += 6.0
        elif any(alias and alias in question for alias in entity.aliases):
            score += 4.5
        if focus and (focus in name or name in focus):
            score += 3.0
        for term in terms:
            if term in name or any(term in alias for alias in entity.aliases):
                score += 1.2 if len(term) >= 2 else 0.3
        return score

    def retrieve(
        self,
        question: str,
        *,
        county: str = "",
        focus: str = "",
        max_hops: int | None = None,
        include_inferred: bool = False,
    ) -> RetrievedContext:
        terms = self._terms(question)
        pool: dict[str, KGEntity] = {}
        for entity in self._graph.find_entities(county=county, limit=500) if county else []:
            pool[entity.id] = entity
        for entity in self._graph.find_entities(name=focus, limit=20) if focus else []:
            pool[entity.id] = entity
        for term in terms:
            for entity in self._graph.find_entities(name=term, limit=10):
                pool.setdefault(entity.id, entity)

        scored = sorted(
            ((self._score(e, question, terms, focus), e) for e in pool.values()),
            key=lambda pair: pair[0],
            reverse=True,
        )
        seeds = [entity for score, entity in scored if score > 0][: self.seed_limit]
        context = RetrievedContext(question=question, county=county, focus=focus)
        if not seeds:
            context.notes.append("图谱中未匹配到与问题相关的实体；建议先执行检索与图谱构建。")
            return context

        merged = Subgraph()
        for seed in seeds:
            merged = merged.merge(
                self._graph.neighbors(
                    seed.id,
                    depth=max_hops if max_hops is not None else self.max_hops,
                    include_inferred=include_inferred,
                    limit=self.entity_limit,
                )
            )
        # 保证种子实体在结果中
        present = {e.id for e in merged.entities}
        entities = list(merged.entities) + [s for s in seeds if s.id not in present]
        entities = entities[: self.entity_limit]
        relations = merged.relations[: self.entity_limit * 2]
        evidence: list[str] = []
        for entity in entities:
            evidence.extend(entity.evidence_ids)
        for relation in relations:
            evidence.extend(relation.evidence_refs())
        context.entities = entities
        context.relations = relations
        context.evidence_ids = list(dict.fromkeys(i for i in evidence if i))
        context.matched_entities = [
            {
                "id": entity.id,
                "name": entity.name,
                "type": entity.type.value,
                "score": round(score, 3),
                "verification_status": entity.verification_status.value,
            }
            for score, entity in scored[: self.seed_limit]
        ]
        context.truncated = merged.truncated
        if not relations:
            context.notes.append("匹配到实体，但没有可用的已验证关系。")
        return context


__all__ = ["GraphRetriever", "RetrievedContext"]
