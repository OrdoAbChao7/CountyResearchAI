"""产业知识图谱实体本体。

所有实体共享 ``KGEntity`` 结构，用 ``EntityType`` 区分 13 类产业对象。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ...domain.intelligence import VerificationStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EntityType(str, Enum):
    COUNTY = "county"
    INDUSTRY = "industry"
    INDUSTRY_SEGMENT = "industry_segment"
    ENTERPRISE = "enterprise"
    PRODUCT = "product"
    MATERIAL = "material"
    TECHNOLOGY = "technology"
    INDUSTRIAL_PARK = "industrial_park"
    POLICY = "policy"
    INSTITUTION = "institution"
    PATENT = "patent"
    INDICATOR = "indicator"
    EVIDENCE = "evidence"


_NAME_CLEAN_RE = re.compile(r"\s+")


def normalize_entity_name(name: str) -> str:
    return _NAME_CLEAN_RE.sub("", (name or "").strip())


def new_entity_id(entity_type: EntityType | str, name: str, county: str = "") -> str:
    """稳定实体 ID：同类型+同名+同县域得到同一 ID，便于 upsert 与消歧。"""
    type_value = entity_type.value if isinstance(entity_type, EntityType) else str(entity_type)
    key = f"{type_value}:{county}:{normalize_entity_name(name)}"
    digest = hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"{type_value}_{digest}"


class KGEntity(BaseModel):
    """知识图谱实体。

    关系/实体都允许承载证据引用。``verification_status`` 用于区分
    已证实、模型推断、待核实与未发现证据四种状态。
    """

    id: str = ""
    type: EntityType
    name: str
    aliases: list[str] = Field(default_factory=list)
    county: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    observed_at: datetime = Field(default_factory=_utcnow)
    source: str = ""

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, value: str) -> str:
        cleaned = normalize_entity_name(value)
        if not cleaned:
            raise ValueError("entity name must not be empty")
        return cleaned

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        return value

    @model_validator(mode="after")
    def _fill_id_and_check_evidence(self) -> KGEntity:
        if not self.id:
            self.id = new_entity_id(self.type, self.name, self.county)
        if self.verification_status == VerificationStatus.VERIFIED and not self.evidence_ids:
            raise ValueError("verified entity requires at least one evidence_id")
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from must not be later than valid_to")
        return self


__all__ = ["EntityType", "KGEntity", "new_entity_id", "normalize_entity_name"]
