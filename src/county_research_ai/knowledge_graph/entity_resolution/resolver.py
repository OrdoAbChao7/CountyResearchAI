"""实体消歧与合并。

规则优先级：稳定 ID → 规范化名称 → 别名 → 包含关系 → 模糊相似度。
只在同类型、同县域（或县域为空）的候选之间匹配，避免跨县误合并。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ...domain.intelligence import VerificationStatus
from ..ontology.entities import KGEntity

_LEGAL_SUFFIXES = [
    "股份有限公司",
    "有限责任公司",
    "集团有限公司",
    "有限公司",
    "集团",
    "公司",
]
_PAREN_RE = re.compile(r"[（(][^）)]{0,30}[）)]")
_PUNCT_RE = re.compile(r"[\s·・,，。.;；:：、\-—_/\\]+")

_STATUS_STRENGTH = {
    VerificationStatus.UNVERIFIED: 0,
    VerificationStatus.INFERRED: 1,
    VerificationStatus.PENDING: 2,
    VerificationStatus.VERIFIED: 3,
}


@dataclass
class EntityResolution:
    entity_id: str
    matched: bool
    method: str  # id / normalized_name / alias / containment / fuzzy / new
    score: float = 1.0
    canonical: KGEntity | None = None


@dataclass
class EntityResolver:
    fuzzy_threshold: float = 0.88
    containment_min_delta: int = 2
    alias_map: dict[str, str] = field(default_factory=dict)

    def normalize(self, name: str) -> str:
        text = _PAREN_RE.sub("", name or "")
        text = _PUNCT_RE.sub("", text)
        for suffix in _LEGAL_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix) + 1:
                text = text[: -len(suffix)]
                break
        return text.strip().lower()

    def resolve(self, candidate: KGEntity, existing: list[KGEntity]) -> EntityResolution:
        if candidate.id:
            for entity in existing:
                if entity.id == candidate.id:
                    return EntityResolution(entity.id, True, "id", 1.0, entity)

        mapped = self.alias_map.get(candidate.name)
        if mapped:
            for entity in existing:
                if entity.id == mapped or entity.name == mapped:
                    return EntityResolution(entity.id, True, "alias_map", 1.0, entity)

        norm = self.normalize(candidate.name)
        pool = [
            entity
            for entity in existing
            if entity.type == candidate.type
            and (not candidate.county or not entity.county or entity.county == candidate.county)
        ]

        for entity in pool:
            if self.normalize(entity.name) == norm:
                return EntityResolution(entity.id, True, "normalized_name", 1.0, entity)

        aliases = {self.normalize(a) for e in pool for a in e.aliases}
        if norm in aliases:
            for entity in pool:
                if norm in {self.normalize(a) for a in entity.aliases}:
                    return EntityResolution(entity.id, True, "alias", 0.98, entity)

        for entity in pool:
            other = self.normalize(entity.name)
            if not other or not norm:
                continue
            shorter, longer = sorted((norm, other), key=len)
            if shorter in longer and len(longer) - len(shorter) >= self.containment_min_delta:
                return EntityResolution(entity.id, True, "containment", 0.92, entity)

        best: tuple[float, KGEntity | None] = (0.0, None)
        for entity in pool:
            ratio = SequenceMatcher(None, norm, self.normalize(entity.name)).ratio()
            if ratio > best[0]:
                best = (ratio, entity)
        if best[1] is not None and best[0] >= self.fuzzy_threshold:
            return EntityResolution(best[1].id, True, "fuzzy", best[0], best[1])

        return EntityResolution(candidate.id, False, "new", 0.0, None)

    def merge(self, primary: KGEntity, other: KGEntity) -> KGEntity:
        """把 ``other`` 合并进 ``primary``（保留 primary 的 ID）。"""
        aliases = list(
            dict.fromkeys(
                primary.aliases
                + other.aliases
                + ([other.name] if other.name != primary.name else [])
            )
        )
        evidence = list(dict.fromkeys(primary.evidence_ids + other.evidence_ids))
        status = (
            other.verification_status
            if _STATUS_STRENGTH[other.verification_status] > _STATUS_STRENGTH[primary.verification_status]
            else primary.verification_status
        )
        return primary.model_copy(
            update={
                "aliases": aliases,
                "evidence_ids": evidence,
                "properties": {**other.properties, **primary.properties},
                "confidence": max(primary.confidence, other.confidence),
                "verification_status": status,
                "county": primary.county or other.county,
                "valid_from": min(
                    [d for d in (primary.valid_from, other.valid_from) if d], default=None
                ),
                "valid_to": max(
                    [d for d in (primary.valid_to, other.valid_to) if d], default=None
                ),
            }
        )


__all__ = ["EntityResolution", "EntityResolver"]
