"""Star A: Industrial Chain Gap Radar.

基于知识图谱的产业链结构 + 证据，识别：
- 产业链缺失环节（图谱中存在环节节点，但没有任何本地企业关联）
- 本地配套不足（环节仅有 1 家企业）
- 外部依赖（本地企业与县域外主体存在投入/供应关系）
- 低专业化（在提供统计数据时计算区位熵）

所有机会默认标记为 INFERRED/PENDING —— 缺口是分析推断，不是既成事实。
"""
from __future__ import annotations

import logging

from ..domain.intelligence import (
    GapType,
    OpportunityCandidate,
    OpportunityReport,
    VerificationStatus,
)
from ..knowledge_graph.graph_store.base import GraphStore
from ..knowledge_graph.ontology.entities import EntityType, KGEntity
from ..knowledge_graph.ontology.relations import KGRelation, RelationshipType
from .evidence_service import EvidenceService
from .quant_service import QuantService

logger = logging.getLogger(__name__)

_SCORE_BY_GAP = {
    GapType.MISSING_SEGMENT: 0.78,
    GapType.WEAK_LOCAL_SUPPLY: 0.62,
    GapType.EXTERNAL_DEPENDENCY: 0.55,
    GapType.LOW_SPECIALIZATION: 0.5,
    GapType.POLICY_GAP: 0.45,
    GapType.TALENT_TECH_GAP: 0.45,
}


class GapRadarService:
    """产业链缺口雷达（确定性核心，可被 LLM 解释与增强）。"""

    def __init__(
        self,
        graph: GraphStore,
        evidence: EvidenceService | None = None,
        quant: QuantService | None = None,
    ) -> None:
        self._graph = graph
        self._evidence = evidence
        self._quant = quant or QuantService()

    def scan(  # noqa: C901 — 逐类缺口检测保持单一直观流程
        self,
        county: str,
        industry: str,
        *,
        lq_inputs: dict[str, float] | None = None,
        max_opportunities: int = 12,
    ) -> OpportunityReport:
        report = OpportunityReport(county=county, industry=industry)
        subgraph = self._graph.county_subgraph(county, industry=industry, limit=300)
        if not subgraph.entities:
            report.notes.append(
                "图谱中没有该县域/产业的实体。请先运行研究并完成知识图谱构建。"
            )
            report.degraded = True
            return report

        by_id = {entity.id: entity for entity in subgraph.entities}
        relations = subgraph.relations
        industry_entity = self._find_industry(industry, subgraph.entities, by_id)
        segments = self._segments(relations, by_id, industry_entity)
        enterprises = [e for e in subgraph.entities if e.type == EntityType.ENTERPRISE]
        evidence_ids: list[str] = []

        segment_enterprises: dict[str, list[str]] = {}
        segment_entity_map: dict[str, KGEntity] = {}
        for segment in segments:
            segment_entity_map[segment.id] = segment
            members: list[str] = []
            for relation in relations:
                if relation.source_entity_id == segment.id and relation.target_entity_id in by_id:
                    target = by_id[relation.target_entity_id]
                    if target.type == EntityType.ENTERPRISE:
                        members.append(target.id)
                if (
                    relation.target_entity_id == segment.id
                    and relation.relationship_type == RelationshipType.BELONGS_TO
                    and relation.source_entity_id in by_id
                    and by_id[relation.source_entity_id].type == EntityType.ENTERPRISE
                ):
                    members.append(relation.source_entity_id)
            segment_enterprises[segment.id] = list(dict.fromkeys(members))
            evidence_ids.extend(segment.evidence_ids)

        # 1) 缺失环节 / 本地配套不足
        # 区分「真实缺口」与「企业覆盖数据缺失」：如果图谱里根本没有企业，
        # 或企业存在但没有任何环节归属关系，不能把空成员列表解释为缺失环节。
        membership_known = bool(enterprises) and any(segment_enterprises.values())
        if segments and not membership_known:
            report.notes.append(
                "企业实体或企业—环节关系覆盖不足，无法区分真实缺口与数据缺失；"
                "本次不生成缺失/弱配套机会。"
            )
            report.degraded = True
        else:
            for segment in segments:
                members = segment_enterprises.get(segment.id, [])
                segment_evidence = list(dict.fromkeys(segment.evidence_ids))
                if not members:
                    report.missing_segments.append(segment.name)
                    report.opportunities.append(
                        self._candidate(
                            county=county,
                            industry=industry,
                            gap_type=GapType.MISSING_SEGMENT,
                            segment=segment.name,
                            description=f"图谱中存在「{segment.name}」环节，但没有任何本地企业关联。",
                            rationale="产业链环节缺少本地承载主体，存在补链/招商空间。",
                            evidence_ids=segment_evidence,
                            targets=[],
                            actions=[
                                f"围绕「{segment.name}」开展定向招商",
                                "梳理该环节的全国龙头与专精特新企业清单",
                            ],
                        )
                    )
                elif len(members) == 1:
                    member = by_id.get(members[0])
                    report.weak_segments.append(segment.name)
                    report.opportunities.append(
                        self._candidate(
                            county=county,
                            industry=industry,
                            gap_type=GapType.WEAK_LOCAL_SUPPLY,
                            segment=segment.name,
                            description=(
                                f"「{segment.name}」环节仅有 1 家本地企业"
                                + (f"（{member.name}）" if member else "")
                                + "，配套能力薄弱。"
                            ),
                            rationale="单一企业支撑整个环节，存在供给集中风险与扩链空间。",
                            evidence_ids=segment_evidence,
                            targets=[member.name] if member else [],
                            actions=["培育第二供应商", "引进配套中小企业"],
                        )
                    )

        # 2) 外部依赖
        external_map: dict[str, list[str]] = {}
        for relation in relations:
            if relation.relationship_type not in {
                RelationshipType.USES_INPUT,
                RelationshipType.SUPPLIES_TO,
            }:
                continue
            source = by_id.get(relation.source_entity_id)
            target = by_id.get(relation.target_entity_id)
            if source is None or target is None:
                continue
            if source.type != EntityType.ENTERPRISE:
                continue
            target_county = target.county
            if target_county and target_county != county:
                external_map.setdefault(target.name, []).append(relation.id)
                evidence_ids.extend(relation.evidence_refs())
        for name, relation_ids in external_map.items():
            report.external_dependencies.append(name)
            relation_evidence: list[str] = []
            for relation in relations:
                if relation.id in relation_ids:
                    relation_evidence.extend(relation.evidence_refs())
            report.opportunities.append(
                self._candidate(
                    county=county,
                    industry=industry,
                    gap_type=GapType.EXTERNAL_DEPENDENCY,
                    segment=name,
                    description=f"本地企业与县域外主体「{name}」存在投入/供应依赖。",
                    rationale="外部依赖意味着本地配套缺口，可作为本地化替代招商方向。",
                    evidence_ids=list(dict.fromkeys(relation_evidence)),
                    targets=[name],
                    actions=[f"评估「{name}」的本地化替代可行性", "对接替代供应商"],
                )
            )

        # 3) 区位熵
        if lq_inputs:
            try:
                lq = self._quant.location_quotient(
                    lq_inputs["local_industry"],
                    lq_inputs["local_total"],
                    lq_inputs["reference_industry"],
                    lq_inputs["reference_total"],
                    industry_name=industry,
                    region_name=county,
                )
                report.specialization_score = round(lq.value, 4)
                report.notes.append(lq.interpretation)
                if lq.value < 1.0:
                    report.opportunities.append(
                        self._candidate(
                            county=county,
                            industry=industry,
                            gap_type=GapType.LOW_SPECIALIZATION,
                            segment=industry,
                            description=f"区位熵 LQ={lq.value:.2f}，本地专业化程度低于参照区域。",
                            rationale="专业化不足通常对应产业链不完整或规模不经济。",
                            evidence_ids=[],
                            targets=[],
                            actions=["聚焦高附加值环节", "评估产业基金与要素配置"],
                            score_bonus=0.05,
                        )
                    )
            except (KeyError, ValueError) as exc:
                report.notes.append(f"区位熵输入无效：{exc}")
        else:
            report.notes.append(
                "未提供参照区域统计数据，本次未计算区位熵（LQ）。"
            )

        if not segments:
            report.notes.append(
                "图谱中还没有产业链环节（industry_segment）关系；"
                "缺失环节判断需要先抽取 CONTAINS/BELONGS_TO 关系。"
            )
            report.degraded = True
        if not enterprises:
            report.notes.append("图谱中没有企业实体，本地配套判断受限。")
            report.degraded = True

        report.opportunities.sort(key=lambda op: op.score, reverse=True)
        report.opportunities = report.opportunities[:max_opportunities]
        for idx, opportunity in enumerate(report.opportunities, start=1):
            opportunity.opportunity_id = f"{county}-{industry}-op{idx}"
        report.evidence_ids = list(dict.fromkeys(i for i in evidence_ids if i))
        return report

    # ---- 内部 ----

    @staticmethod
    def _find_industry(
        industry: str, entities: list[KGEntity], by_id: dict[str, KGEntity]
    ) -> KGEntity | None:
        candidates = [
            e
            for e in entities
            if e.type in {EntityType.INDUSTRY, EntityType.INDUSTRY_SEGMENT}
            and (industry in e.name or e.name in industry)
        ]
        if candidates:
            return candidates[0]
        return None

    @staticmethod
    def _segments(
        relations: list[KGRelation],
        by_id: dict[str, KGEntity],
        industry: KGEntity | None,
    ) -> list[KGEntity]:
        segments: dict[str, KGEntity] = {}
        for relation in relations:
            if relation.relationship_type != RelationshipType.CONTAINS:
                continue
            if industry is not None and relation.source_entity_id != industry.id:
                continue
            target = by_id.get(relation.target_entity_id)
            if target and target.type == EntityType.INDUSTRY_SEGMENT:
                segments[target.id] = target
        if not segments:
            # 退一步：把所有环节节点视作该产业环节
            for entity in by_id.values():
                if entity.type == EntityType.INDUSTRY_SEGMENT:
                    segments[entity.id] = entity
        return list(segments.values())

    @staticmethod
    def _candidate(
        *,
        county: str,
        industry: str,
        gap_type: GapType,
        segment: str,
        description: str,
        rationale: str,
        evidence_ids: list[str],
        targets: list[str],
        actions: list[str],
        score_bonus: float = 0.0,
    ) -> OpportunityCandidate:
        base = _SCORE_BY_GAP[gap_type]
        evidence_factor = 0.08 if evidence_ids else -0.05
        score = max(0.05, min(0.99, base + evidence_factor + score_bonus))
        return OpportunityCandidate(
            title=f"{industry}·{segment}：{gap_type.value}",
            gap_type=gap_type,
            segment=segment,
            description=description,
            rationale=rationale,
            score=round(score, 3),
            evidence_ids=list(dict.fromkeys(evidence_ids)),
            target_enterprises=targets,
            suggested_actions=actions,
            verification_status=(
                VerificationStatus.PENDING if evidence_ids else VerificationStatus.INFERRED
            ),
        )


__all__ = ["GapRadarService", "GapType", "OpportunityReport"]
