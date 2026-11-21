"""产业关系抽取器（LLM + 确定性规则回退）。

证据规则：
- 关系必须绑定本段文本对应的 ``evidence_id``；
- 只有 quote 在原文中真实出现时才可标记 VERIFIED；
- 其余一律 INFERRED，且默认不会被持久化进图（见 GraphWritePolicy）。
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from ...domain.intelligence import VerificationStatus
from ...llm.base import LLMClient
from ...llm.structured import parse_json_object
from ..ontology.entities import KGEntity
from ..ontology.relations import KGRelation, RelationshipType

logger = logging.getLogger(__name__)

_LLM_SYSTEM = """你是产业知识图谱关系抽取器。只抽取文本明确表达的关系，禁止推测。
输出严格 JSON：
{"relations": [
  {"source": "实体名称或ID", "target": "实体名称或ID",
   "type": "HAS_INDUSTRY|CONTAINS|BELONGS_TO|LOCATED_IN|PRODUCES|USES_INPUT|SUPPLIES_TO|COOPERATES_WITH|COMPETES_WITH|SUPPORTS|DEVELOPS|APPLIED_IN|OWNS",
   "confidence": 0.0-1.0,
   "quote": "文本中的连续原文依据"}
]}
规则：
1. source/target 必须是给定实体列表中的名称或 ID；
2. quote 必须逐字出现在原文中；
3. 没有明确依据就不要输出该关系。"""

_PATTERNS: list[tuple[re.Pattern[str], RelationshipType]] = [
    (re.compile(r"(?P<a>[一-龥A-Za-z0-9]{2,30}?)(?:位于|坐落于|地处)(?P<b>[一-龥]{2,12}(?:县|市|区))"), RelationshipType.LOCATED_IN),
    (re.compile(r"(?P<a>[一-龥A-Za-z0-9]{2,30}?)(?:主要生产|生产|制造)(?P<b>[一-龥A-Za-z0-9]{2,20})"), RelationshipType.PRODUCES),
    (re.compile(r"(?P<a>[一-龥A-Za-z0-9]{2,30}?)(?:为|向)(?P<b>[一-龥A-Za-z0-9]{2,30}?)(?:提供|供应|配套)"), RelationshipType.SUPPLIES_TO),
    (re.compile(r"(?P<a>[一-龥A-Za-z0-9]{2,30}?)(?:与)(?P<b>[一-龥A-Za-z0-9]{2,30}?)(?:合作|共建|联合)"), RelationshipType.COOPERATES_WITH),
    (re.compile(r"(?P<a>[一-龥A-Za-z0-9]{2,30}?)(?:属于|归属于)(?P<b>[一-龥]{2,20}(?:产业|行业))"), RelationshipType.BELONGS_TO),
]


class RelationExtractor:
    """从文本和已抽取实体中识别产业关系。"""

    def __init__(self, llm: LLMClient | None = None, *, max_relations: int = 40) -> None:
        self._llm = llm
        self.max_relations = max_relations

    def extract(
        self,
        text: str,
        entities: Iterable[KGEntity],
        *,
        evidence_id: str = "",
        county: str = "",
        extracted_by: str = "relation_extractor",
    ) -> list[KGRelation]:
        entity_list = [e for e in entities if e and e.id]
        if not text.strip() or len(entity_list) < 2:
            return []
        relations: list[KGRelation] = []
        if self._llm is not None:
            try:
                relations = self._llm_extract(
                    text,
                    entity_list,
                    evidence_id=evidence_id,
                    extracted_by=extracted_by,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM 关系抽取失败，使用规则回退 | err=%s", exc)
        if not relations:
            relations = self._rule_extract(
                text,
                entity_list,
                evidence_id=evidence_id,
                extracted_by=extracted_by,
            )
        return relations[: self.max_relations]

    # ---- LLM ----

    def _llm_extract(
        self,
        text: str,
        entities: list[KGEntity],
        *,
        evidence_id: str,
        extracted_by: str,
    ) -> list[KGRelation]:
        assert self._llm is not None
        entity_lines = "\n".join(
            f"- {e.id} | {e.type.value} | {e.name}" for e in entities[:60]
        )
        user = (
            f"实体列表（ID | 类型 | 名称）：\n{entity_lines}\n\n"
            f"文本（截断）：\n{text[:6000]}"
        )
        response = self._llm.chat(
            [
                {"role": "system", "content": _LLM_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=2000,
        )
        payload = parse_json_object(response.content)
        raw_relations = payload.get("relations", [])
        if not isinstance(raw_relations, list):
            return []
        by_id = {e.id: e for e in entities}
        by_name = {e.name: e for e in entities}
        relations: list[KGRelation] = []
        for raw in raw_relations[: self.max_relations]:
            if not isinstance(raw, dict):
                continue
            source = by_id.get(str(raw.get("source", ""))) or by_name.get(
                str(raw.get("source", ""))
            )
            target = by_id.get(str(raw.get("target", ""))) or by_name.get(
                str(raw.get("target", ""))
            )
            if source is None or target is None or source.id == target.id:
                continue
            try:
                rel_type = RelationshipType(str(raw.get("type", "")).strip())
            except ValueError:
                continue
            quote = str(raw.get("quote", ""))
            bound = bool(evidence_id) and bool(quote) and quote in text
            confidence = float(raw.get("confidence", 0.5) or 0.5)
            if confidence < 0.5 and not bound:
                continue
            relations.append(
                KGRelation(
                    source_entity_id=source.id,
                    target_entity_id=target.id,
                    relationship_type=rel_type,
                    source_evidence_id=evidence_id if bound else "",
                    confidence=max(0.1, min(confidence, 1.0)),
                    verification_status=(
                        VerificationStatus.VERIFIED
                        if bound
                        else VerificationStatus.INFERRED
                    ),
                    quote=quote,
                    extracted_by=extracted_by,
                )
            )
        return relations

    # ---- 规则回退 ----

    def _rule_extract(
        self,
        text: str,
        entities: list[KGEntity],
        *,
        evidence_id: str,
        extracted_by: str,
    ) -> list[KGRelation]:
        names = {e.name: e for e in entities if len(e.name) >= 2}
        relations: list[KGRelation] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if len(line) < 8:
                continue
            for pattern, rel_type in _PATTERNS:
                for match in pattern.finditer(line):
                    source_name = match.group("a").strip()
                    target_name = match.group("b").strip()
                    source = self._match_entity(source_name, names)
                    target = self._match_entity(target_name, names)
                    if source is None or target is None or source.id == target.id:
                        continue
                    quote = match.group(0)
                    relations.append(
                        KGRelation(
                            source_entity_id=source.id,
                            target_entity_id=target.id,
                            relationship_type=rel_type,
                            source_evidence_id=evidence_id if evidence_id else "",
                            confidence=0.8 if evidence_id else 0.45,
                            verification_status=(
                                VerificationStatus.VERIFIED
                                if evidence_id and quote in text
                                else VerificationStatus.INFERRED
                            ),
                            quote=quote,
                            extracted_by=f"{extracted_by}:rules",
                        )
                    )
                    if len(relations) >= self.max_relations:
                        return relations
        return relations

    @staticmethod
    def _match_entity(name: str, names: dict[str, KGEntity]) -> KGEntity | None:
        if name in names:
            return names[name]
        for entity_name, entity in names.items():
            if name in entity_name or entity_name in name:
                return entity
        return None


__all__ = ["RelationExtractor"]
