"""产业实体抽取器（LLM + 确定性规则回退）。

硬约束：抽取出的实体只能引用传入的 ``evidence_ids``。LLM 不得凭空
生成证据 ID；没有证据支撑的实体以 PENDING / UNVERIFIED 状态记录。
"""
from __future__ import annotations

import logging
import re

from ...domain.intelligence import VerificationStatus
from ...llm.base import LLMClient
from ...llm.structured import parse_json_object
from ..ontology.entities import EntityType, KGEntity, normalize_entity_name

logger = logging.getLogger(__name__)

_LLM_SYSTEM = """你是产业知识图谱实体抽取器。只从给定文本中抽取明确出现的产业实体，禁止推测、补全或编造。
输出严格 JSON：
{"entities": [
  {"type": "enterprise|industry|industry_segment|product|material|technology|industrial_park|policy|institution|patent|indicator|county",
   "name": "实体规范名称",
   "aliases": ["别名"],
   "properties": {"可选字段": "值"},
   "confidence": 0.0-1.0,
   "quote": "文本中的原文依据"}
]}
规则：
1. 只抽取文本中真实出现的名称；
2. quote 必须是原文的连续片段；
3. 不确定的实体 confidence 低于 0.5；
4. 不要输出解释，只输出 JSON。"""

_TYPE_ALIASES = {
    "县": EntityType.COUNTY,
    "县域": EntityType.COUNTY,
    "county": EntityType.COUNTY,
    "产业": EntityType.INDUSTRY,
    "行业": EntityType.INDUSTRY,
    "industry": EntityType.INDUSTRY,
    "产业链环节": EntityType.INDUSTRY_SEGMENT,
    "环节": EntityType.INDUSTRY_SEGMENT,
    "industry_segment": EntityType.INDUSTRY_SEGMENT,
    "企业": EntityType.ENTERPRISE,
    "公司": EntityType.ENTERPRISE,
    "enterprise": EntityType.ENTERPRISE,
    "产品": EntityType.PRODUCT,
    "product": EntityType.PRODUCT,
    "材料": EntityType.MATERIAL,
    "material": EntityType.MATERIAL,
    "技术": EntityType.TECHNOLOGY,
    "technology": EntityType.TECHNOLOGY,
    "园区": EntityType.INDUSTRIAL_PARK,
    "产业园": EntityType.INDUSTRIAL_PARK,
    "industrial_park": EntityType.INDUSTRIAL_PARK,
    "政策": EntityType.POLICY,
    "policy": EntityType.POLICY,
    "机构": EntityType.INSTITUTION,
    "科研机构": EntityType.INSTITUTION,
    "institution": EntityType.INSTITUTION,
    "专利": EntityType.PATENT,
    "patent": EntityType.PATENT,
    "指标": EntityType.INDICATOR,
    "indicator": EntityType.INDICATOR,
}

_ENTERPRISE_RE = re.compile(
    r"([一-龥A-Za-z0-9]{2,30}?(?:股份有限公司|有限责任公司|有限公司|集团|股份|公司))"
)
_POLICY_RE = re.compile(r"《([^》]{4,60}(?:规划|意见|方案|通知|办法|行动计划|决定|条例))》")
_PARK_RE = re.compile(
    r"([一-龥A-Za-z0-9]{2,30}?(?:产业园区|工业园|开发区|产业园|集聚区|园区))"
)
_INDUSTRY_RE = re.compile(r"([一-龥]{2,10}(?:产业|加工业|制造业|种植业|文旅业))")
_INDUSTRY_STOP_PREFIXES = (
    "近年", "该县", "全县", "重点", "建成", "形成", "实现", "达到",
    "打造", "培育", "出重点", "省级", "国家级", "百亿",
)


class EntityExtractor:
    """从单篇资料中抽取产业实体。"""

    def __init__(self, llm: LLMClient | None = None, *, max_entities: int = 40) -> None:
        self._llm = llm
        self.max_entities = max_entities

    def extract(
        self,
        text: str,
        *,
        county: str = "",
        focus: str = "",
        evidence_ids: list[str] | None = None,
        source: str = "entity_extractor",
    ) -> list[KGEntity]:
        evidence_ids = [e for e in (evidence_ids or []) if e]
        entities: list[KGEntity] = []
        if self._llm is not None and text.strip():
            try:
                entities = self._llm_extract(
                    text,
                    county=county,
                    focus=focus,
                    evidence_ids=evidence_ids,
                    source=source,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM 实体抽取失败，使用规则回退 | err=%s", exc)
        if not entities:
            entities = self._rule_extract(
                text,
                county=county,
                focus=focus,
                evidence_ids=evidence_ids,
                source=source,
            )
        return self._dedupe(entities)

    # ---- LLM ----

    def _llm_extract(
        self,
        text: str,
        *,
        county: str,
        focus: str,
        evidence_ids: list[str],
        source: str,
    ) -> list[KGEntity]:
        assert self._llm is not None
        user = (
            f"县域：{county or '未知'}\n"
            f"研究产业：{focus or '未指定'}\n"
            f"资料正文（截断）：\n{text[:6000]}"
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
        raw_entities = payload.get("entities", [])
        if not isinstance(raw_entities, list):
            return []
        entities: list[KGEntity] = []
        for raw in raw_entities[: self.max_entities]:
            if not isinstance(raw, dict):
                continue
            entity_type = self._parse_type(str(raw.get("type", "")))
            name = normalize_entity_name(str(raw.get("name", "")))
            if not entity_type or not name:
                continue
            quote = str(raw.get("quote", ""))
            confidence = float(raw.get("confidence", 0.5) or 0.5)
            bound = bool(evidence_ids) and bool(quote) and quote in text
            status = (
                VerificationStatus.VERIFIED
                if bound and confidence >= 0.6
                else VerificationStatus.PENDING
            )
            entities.append(
                KGEntity(
                    type=entity_type,
                    name=name,
                    aliases=[str(a) for a in raw.get("aliases", []) if a],
                    county=county if entity_type not in {EntityType.COUNTY} else "",
                    properties={
                        **(raw.get("properties") or {}),
                        **({"quote": quote} if quote else {}),
                    },
                    evidence_ids=evidence_ids if bound else [],
                    confidence=max(0.1, min(confidence, 1.0)),
                    verification_status=status,
                    source=source,
                )
            )
        return entities

    @staticmethod
    def _parse_type(value: str) -> EntityType | None:
        cleaned = value.strip().lower()
        if cleaned in _TYPE_ALIASES:
            return _TYPE_ALIASES[cleaned]
        try:
            return EntityType(cleaned)
        except ValueError:
            return None

    # ---- 规则回退 ----

    def _rule_extract(
        self,
        text: str,
        *,
        county: str,
        focus: str,
        evidence_ids: list[str],
        source: str,
    ) -> list[KGEntity]:
        status = VerificationStatus.VERIFIED if evidence_ids else VerificationStatus.PENDING
        confidence = 0.75 if evidence_ids else 0.4
        common = dict(
            evidence_ids=evidence_ids,
            confidence=confidence,
            verification_status=status,
            source=f"{source}:rules",
        )
        entities: list[KGEntity] = []
        if county:
            entities.append(
                KGEntity(type=EntityType.COUNTY, name=county, **common)
            )
        if focus:
            entities.append(
                KGEntity(type=EntityType.INDUSTRY, name=focus, county=county, **common)
            )
        for match in dict.fromkeys(_ENTERPRISE_RE.findall(text)):
            entities.append(
                KGEntity(type=EntityType.ENTERPRISE, name=match, county=county, **common)
            )
        for match in dict.fromkeys(_POLICY_RE.findall(text)):
            entities.append(
                KGEntity(type=EntityType.POLICY, name=match, county=county, **common)
            )
        for match in dict.fromkeys(_PARK_RE.findall(text)):
            entities.append(
                KGEntity(
                    type=EntityType.INDUSTRIAL_PARK,
                    name=match,
                    county=county,
                    evidence_ids=evidence_ids,
                    confidence=confidence,
                    verification_status=status,
                    source=f"{source}:rules",
                )
            )
        for match in dict.fromkeys(_INDUSTRY_RE.findall(text)):
            if focus and match == focus:
                continue
            # 规则回退必须保守：明显是句子片段的名词组合不能当作产业节点。
            if match.startswith(_INDUSTRY_STOP_PREFIXES) or "百亿" in match:
                continue
            entities.append(
                KGEntity(type=EntityType.INDUSTRY, name=match, county=county, **common)
            )
        return entities[: self.max_entities]

    @staticmethod
    def _dedupe(entities: list[KGEntity]) -> list[KGEntity]:
        seen: dict[tuple[str, str], KGEntity] = {}
        for entity in entities:
            key = (entity.type.value, entity.name)
            if key not in seen:
                seen[key] = entity
        return list(seen.values())[:40]


__all__ = ["EntityExtractor"]
