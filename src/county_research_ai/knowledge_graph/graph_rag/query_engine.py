"""Agent 可调用的 GraphRAG 查询引擎。

与 ``EvidenceService`` 通过协议协同：图谱给出结构关系，证据服务给出
原文出处。没有 LLM 时提供确定性的结构化回答，绝不虚构事实。
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field

from ...domain.intelligence import VerificationStatus
from ...llm.base import LLMClient
from ..graph_store.base import GraphStore, Subgraph
from ..ontology.entities import EntityType, KGEntity
from ..ontology.relations import KGRelation, RelationshipType
from .retriever import GraphRetriever, RetrievedContext

logger = logging.getLogger(__name__)


class EvidenceLookup(Protocol):
    def by_ids(self, ids: list[str]) -> list: ...

    def search(self, keywords: list[str], *, topic: str = "", limit: int = 10) -> list: ...


class GraphQueryResult(BaseModel):
    query: str
    answer: str = ""
    entities: list[dict[str, Any]] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    degraded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class GraphRAGQueryEngine:
    """图检索 + 证据回填 + 可选 LLM 归纳。"""

    def __init__(
        self,
        graph: GraphStore,
        evidence: EvidenceLookup | None = None,
        llm: LLMClient | None = None,
        *,
        retriever: GraphRetriever | None = None,
    ) -> None:
        self._graph = graph
        self._evidence = evidence
        self._llm = llm
        self._retriever = retriever or GraphRetriever(graph)

    # ---- 通用问答 ----

    def answer(self, question: str, *, county: str = "", focus: str = "") -> GraphQueryResult:
        context = self._retriever.retrieve(question, county=county, focus=focus)
        result = self._context_result(question, context)
        if context.is_empty():
            if self._evidence is not None:
                items = self._evidence.search(self._retriever._terms(question), limit=6)
                if items:
                    result.evidence = [self._evidence_brief(i) for i in items]
                    result.evidence_ids = [i.id for i in items]
                    result.answer = self._fallback_answer(question, context, items)
                    result.notes.append("图谱无结果，已回退到证据库检索。")
                    return result
            result.notes.append("没有可用图谱证据，无法回答该问题。")
            return result
        if self._llm is not None:
            try:
                result.answer = self._llm_answer(question, context, result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("GraphRAG LLM 回答失败，使用确定性摘要 | err=%s", exc)
                result.degraded = True
                result.answer = self._fallback_answer(question, context, [])
        else:
            result.answer = self._fallback_answer(question, context, [])
        return result

    def _llm_answer(
        self, question: str, context: RetrievedContext, result: GraphQueryResult
    ) -> str:
        assert self._llm is not None
        entity_lines = "\n".join(
            f"- {e.name}（{e.type.value}, {e.verification_status.value}）"
            for e in context.entities[:30]
        )
        relation_lines = "\n".join(
            f"- {self._entity_name(r.source_entity_id)} -{r.relationship_type.value}-> "
            f"{self._entity_name(r.target_entity_id)} "
            f"（{r.verification_status.value}, 证据: {', '.join(r.evidence_refs()) or '无'}）"
            for r in context.relations[:40]
        )
        evidence_lines = "\n".join(
            f"[{item['id']}] {item['claim']} —— {item['title']}"
            for item in result.evidence[:15]
        )
        prompt = (
            "你是产业知识图谱分析助手。只能依据以下图谱事实与证据回答，"
            "不要补充未出现的信息。答案中的每个关键事实后用 [EvidenceID] 标注来源；"
            "若证据不足，明确说明。\n\n"
            f"问题：{question}\n\n实体：\n{entity_lines or '（无）'}\n\n"
            f"关系：\n{relation_lines or '（无）'}\n\n"
            f"证据：\n{evidence_lines or '（无）'}"
        )
        response = self._llm.chat(
            [{"role": "user", "content": prompt}], temperature=0.1, max_tokens=1200
        )
        return response.content.strip()

    def _fallback_answer(
        self, question: str, context: RetrievedContext, items: list
    ) -> str:
        if context.is_empty() and not items:
            return "知识图谱与证据库中均未找到可支撑该问题的信息。"
        lines = [f"围绕「{question}」，当前可核实的信息如下："]
        if context.relations:
            lines.append(f"图谱中存在 {len(context.relations)} 条已验证关系：")
            for relation in context.relations[:8]:
                lines.append(
                    f"- {self._entity_name(relation.source_entity_id)} "
                    f"{relation.relationship_type.value} "
                    f"{self._entity_name(relation.target_entity_id)}"
                )
        elif context.entities:
            lines.append(
                "匹配实体：" + "、".join(e.name for e in context.entities[:8])
            )
        for item in items[:6]:
            lines.append(f"- {item.claim}（来源：{item.title}，证据 {item.id}）")
        if context.evidence_ids and not items:
            lines.append(f"相关证据 ID：{', '.join(context.evidence_ids[:10])}")
        lines.append("说明：以上为图谱/证据库的确定性摘要，未经 LLM 归纳。")
        return "\n".join(lines)

    # ---- 专用查询 ----

    def enterprise_relations(self, enterprise: str, *, county: str = "") -> GraphQueryResult:
        entity = self._find(EntityType.ENTERPRISE, enterprise, county)
        query = f"企业关系：{enterprise}"
        if entity is None:
            return GraphQueryResult(query=query, notes=["未找到该企业实体。"])
        subgraph = self._graph.neighbors(entity.id, depth=2, limit=100)
        grouped: dict[str, list[str]] = {}
        for relation in subgraph.relations:
            grouped.setdefault(relation.relationship_type.value, []).append(
                self._relation_line(relation)
            )
        return self._result_from_subgraph(
            query,
            subgraph,
            answer=(
                f"企业「{entity.name}」在当前图谱中有 "
                f"{len(subgraph.relations)} 条已验证关系，涵盖 "
                f"{'、'.join(grouped.keys()) or '无'}。"
            ),
            extra={"grouped_relations": grouped},
        )

    def supply_chain(
        self, industry: str, *, county: str = "", direction: str = "both", depth: int = 2
    ) -> GraphQueryResult:
        entity = self._find(EntityType.INDUSTRY, industry, county) or self._find(
            EntityType.INDUSTRY_SEGMENT, industry, county
        )
        query = f"产业链：{industry}（{direction}）"
        if entity is None:
            return GraphQueryResult(query=query, notes=["未找到该产业实体。"])
        subgraph = self._graph.neighbors(
            entity.id,
            depth=max(1, min(depth, 3)),
            relationship_types=[
                RelationshipType.CONTAINS,
                RelationshipType.BELONGS_TO,
                RelationshipType.PRODUCES,
                RelationshipType.USES_INPUT,
                RelationshipType.SUPPLIES_TO,
                RelationshipType.HAS_INDUSTRY,
            ],
            limit=150,
        )
        names = {e.id: e for e in subgraph.entities}
        segments: list[str] = []
        upstream: list[str] = []
        downstream: list[str] = []
        for relation in subgraph.relations:
            if relation.relationship_type == RelationshipType.CONTAINS and relation.source_entity_id in {
                entity.id
            }:
                target = names.get(relation.target_entity_id)
                if target and target.type == EntityType.INDUSTRY_SEGMENT:
                    segments.append(target.name)
            if relation.relationship_type == RelationshipType.USES_INPUT:
                target = names.get(relation.target_entity_id)
                if target:
                    upstream.append(target.name)
            if relation.relationship_type == RelationshipType.PRODUCES:
                target = names.get(relation.target_entity_id)
                if target:
                    downstream.append(target.name)
            if relation.relationship_type == RelationshipType.SUPPLIES_TO:
                source = names.get(relation.source_entity_id)
                if source:
                    upstream.append(source.name)
        payload = {
            "segments": segments,
            "upstream": list(dict.fromkeys(upstream)),
            "downstream": list(dict.fromkeys(downstream)),
        }
        result = self._result_from_subgraph(
            query,
            subgraph,
            answer=(
                f"「{entity.name}」产业链中识别出 {len(payload['segments'])} 个环节、"
                f"{len(payload['upstream'])} 个上游投入主体、"
                f"{len(payload['downstream'])} 个下游产出主体。"
            ),
        )
        result.notes.append(f"结构化结果：{payload}")
        return result

    def chain_paths(
        self, source: str, target: str, *, county: str = ""
    ) -> GraphQueryResult:
        src = self._find_any(source, county)
        dst = self._find_any(target, county)
        query = f"产业链路径：{source} → {target}"
        if src is None or dst is None:
            return GraphQueryResult(query=query, notes=["起点或终点实体不存在。"])
        path = self._graph.shortest_path(src.id, dst.id, max_depth=6)
        entities = [src, dst]
        for relation in path:
            for endpoint in (relation.source_entity_id, relation.target_entity_id):
                entity = self._graph.get_entity(endpoint)
                if entity and entity.id not in {e.id for e in entities}:
                    entities.append(entity)
        answer = (
            " → ".join([src.name] + [self._entity_name(r.target_entity_id) for r in path])
            if path
            else "两者之间不存在已证实的产业链路径。"
        )
        return GraphQueryResult(
            query=query,
            answer=answer,
            entities=[self._entity_brief(e) for e in entities],
            relations=[self._relation_brief(r) for r in path],
            evidence_ids=list(dict.fromkeys(i for r in path for i in r.evidence_refs())),
            notes=[] if path else ["未发现已证实的路径；可补充上游/下游企业关系证据后重试。"],
        )

    def clusters(self, county: str, *, industry: str = "") -> GraphQueryResult:
        subgraph = self._graph.county_subgraph(county, industry=industry, limit=300)
        parks = [e for e in subgraph.entities if e.type == EntityType.INDUSTRIAL_PARK]
        enterprises = [e for e in subgraph.entities if e.type == EntityType.ENTERPRISE]
        by_park: dict[str, list[str]] = {}
        for relation in subgraph.relations:
            if relation.relationship_type != RelationshipType.CONTAINS:
                continue
            source = subgraph.entity(relation.source_entity_id)
            target = subgraph.entity(relation.target_entity_id)
            if source and target and source.type == EntityType.INDUSTRIAL_PARK:
                by_park.setdefault(source.name, []).append(target.name)
        result = self._result_from_subgraph(
            f"产业集群：{county} {industry}".strip(),
            subgraph,
            answer=(
                f"{county}图谱中识别到 {len(parks)} 个园区、{len(enterprises)} 家企业，"
                f"{len(by_park)} 个园区已建立企业归属关系。"
            ),
        )
        result.notes.append(f"园区-企业：{by_park}")
        return result

    def park_enterprises(self, park: str, *, county: str = "") -> GraphQueryResult:
        entity = self._find(EntityType.INDUSTRIAL_PARK, park, county)
        query = f"园区企业：{park}"
        if entity is None:
            return GraphQueryResult(query=query, notes=["未找到该园区实体。"])
        relations = self._graph.get_relations(
            source_id=entity.id,
            relationship_type=RelationshipType.CONTAINS,
            limit=200,
        )
        enterprises = [
            self._graph.get_entity(r.target_entity_id) for r in relations
        ]
        enterprises = [e for e in enterprises if e]
        return GraphQueryResult(
            query=query,
            answer=f"园区「{entity.name}」当前有 {len(enterprises)} 家已证实入驻企业。",
            entities=[self._entity_brief(entity)] + [self._entity_brief(e) for e in enterprises],
            relations=[self._relation_brief(r) for r in relations],
            evidence_ids=list(dict.fromkeys(i for r in relations for i in r.evidence_refs())),
        )

    def policy_industry_links(self, industry: str, *, county: str = "") -> GraphQueryResult:
        entity = self._find(EntityType.INDUSTRY, industry, county) or self._find(
            EntityType.INDUSTRY_SEGMENT, industry, county
        )
        query = f"政策-产业关联：{industry}"
        if entity is None:
            return GraphQueryResult(query=query, notes=["未找到该产业实体。"])
        relations = [
            r
            for r in self._graph.get_relations(
                target_id=entity.id,
                relationship_type=RelationshipType.SUPPORTS,
                limit=100,
            )
        ]
        policies = [self._graph.get_entity(r.source_entity_id) for r in relations]
        policies = [p for p in policies if p]
        return GraphQueryResult(
            query=query,
            answer=(
                f"图谱中有 {len(policies)} 项政策/机构与「{entity.name}」建立了支持关系。"
            ),
            entities=[self._entity_brief(p) for p in policies],
            relations=[self._relation_brief(r) for r in relations],
            evidence_ids=list(dict.fromkeys(i for r in relations for i in r.evidence_refs())),
        )

    def evidence_trace(self, *, entity_id: str = "", relation_id: str = "") -> GraphQueryResult:
        query = f"证据追溯：{entity_id or relation_id}"
        evidence_ids: list[str] = []
        entities: list[KGEntity] = []
        relations: list[KGRelation] = []
        if entity_id:
            entity = self._graph.get_entity(entity_id)
            if entity:
                entities.append(entity)
                evidence_ids.extend(entity.evidence_ids)
                relations = self._graph.get_relations(
                    source_id=entity.id, include_inferred=True, include_pending=True, limit=100
                )
        elif relation_id:
            for relation in self._graph.get_relations(
                include_inferred=True,
                include_pending=True,
                include_unverified=True,
                limit=5000,
            ):
                if relation.id == relation_id:
                    relations.append(relation)
                    break
        for relation in relations:
            evidence_ids.extend(relation.evidence_refs())
        evidence_ids = list(dict.fromkeys(i for i in evidence_ids if i))
        items = self._evidence.by_ids(evidence_ids) if self._evidence else []
        if not items and self._evidence:
            items = self._evidence.search([query], limit=5)
        return GraphQueryResult(
            query=query,
            answer=(
                f"追溯得到 {len(evidence_ids)} 个证据引用与 {len(items)} 条证据记录。"
                if evidence_ids
                else "该对象没有绑定任何证据。"
            ),
            entities=[self._entity_brief(e) for e in entities],
            relations=[self._relation_brief(r) for r in relations],
            evidence=[self._evidence_brief(i) for i in items],
            evidence_ids=evidence_ids,
            notes=[] if evidence_ids else ["无证据关系不得作为事实结论使用。"],
        )

    def multi_hop(self, entity: str, *, county: str = "", depth: int = 3) -> GraphQueryResult:
        seed = self._find_any(entity, county)
        query = f"多跳关系：{entity}（depth={depth}）"
        if seed is None:
            return GraphQueryResult(query=query, notes=["未找到该实体。"])
        subgraph = self._graph.neighbors(seed.id, depth=max(1, min(depth, 4)), limit=200)
        return self._result_from_subgraph(
            query,
            subgraph,
            answer=(
                f"从「{seed.name}」出发，{depth} 跳内发现 "
                f"{len(subgraph.entities)} 个实体与 {len(subgraph.relations)} 条已验证关系。"
            ),
        )

    # ---- 内部 ----

    def _result_from_subgraph(
        self,
        query: str,
        subgraph: Subgraph,
        *,
        answer: str,
        extra: dict[str, Any] | None = None,
    ) -> GraphQueryResult:
        items = []
        evidence_ids = subgraph.evidence_ids
        if self._evidence is not None and evidence_ids:
            items = self._evidence.by_ids(evidence_ids)
        result = GraphQueryResult(
            query=query,
            answer=answer,
            entities=[self._entity_brief(e) for e in subgraph.entities],
            relations=[self._relation_brief(r) for r in subgraph.relations],
            evidence=[self._evidence_brief(i) for i in items[:20]],
            evidence_ids=evidence_ids,
            notes=[],
        )
        if extra:
            result.notes.extend(f"{k}：{v}" for k, v in extra.items())
        return result

    def _context_result(self, question: str, context: RetrievedContext) -> GraphQueryResult:
        items = []
        if self._evidence is not None and context.evidence_ids:
            items = self._evidence.by_ids(context.evidence_ids)
        return GraphQueryResult(
            query=question,
            entities=[self._entity_brief(e) for e in context.entities],
            relations=[self._relation_brief(r) for r in context.relations],
            evidence=[self._evidence_brief(i) for i in items[:20]],
            evidence_ids=context.evidence_ids,
            notes=list(context.notes),
        )

    def _find(
        self, entity_type: EntityType, name: str, county: str = ""
    ) -> KGEntity | None:
        candidates = self._graph.find_entities(
            entity_type=entity_type, name=name, county=county or None, limit=10
        )
        if candidates:
            return candidates[0]
        # 不限县域再试一次（抽取时可能未写 county）
        candidates = self._graph.find_entities(entity_type=entity_type, name=name, limit=10)
        return candidates[0] if candidates else None

    def _find_any(self, name: str, county: str = "") -> KGEntity | None:
        candidates = self._graph.find_entities(name=name, county=county or None, limit=10)
        if candidates:
            return candidates[0]
        candidates = self._graph.find_entities(name=name, limit=10)
        return candidates[0] if candidates else None

    def _entity_name(self, entity_id: str) -> str:
        entity = self._graph.get_entity(entity_id)
        return entity.name if entity else entity_id

    def _relation_line(self, relation: KGRelation) -> str:
        return (
            f"{self._entity_name(relation.source_entity_id)} "
            f"-{relation.relationship_type.value}-> "
            f"{self._entity_name(relation.target_entity_id)}"
            f"（{relation.verification_status.value}，证据 {', '.join(relation.evidence_refs()) or '无'}）"
        )

    @staticmethod
    def _entity_brief(entity: KGEntity) -> dict[str, Any]:
        return {
            "id": entity.id,
            "type": entity.type.value,
            "name": entity.name,
            "county": entity.county,
            "verification_status": entity.verification_status.value,
            "confidence": entity.confidence,
            "evidence_ids": entity.evidence_ids,
        }

    @staticmethod
    def _relation_brief(relation: KGRelation) -> dict[str, Any]:
        return {
            "id": relation.id,
            "source_entity_id": relation.source_entity_id,
            "target_entity_id": relation.target_entity_id,
            "type": relation.relationship_type.value,
            "verification_status": relation.verification_status.value,
            "confidence": relation.confidence,
            "evidence_ids": relation.evidence_refs(),
            "quote": relation.quote,
        }

    @staticmethod
    def _evidence_brief(item: object) -> dict[str, Any]:
        return {
            "id": getattr(item, "id", ""),
            "claim": getattr(item, "claim", ""),
            "title": getattr(item, "title", ""),
            "url": getattr(item, "url", ""),
            "year": getattr(item, "year", None),
            "credibility_score": getattr(item, "credibility_score", 0.0),
            "verification_status": getattr(item, "verification_status", "unverified"),
        }


__all__ = ["GraphQueryResult", "GraphRAGQueryEngine", "VerificationStatus"]
