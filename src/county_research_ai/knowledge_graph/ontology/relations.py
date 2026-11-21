"""产业知识图谱关系本体与证据约束。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ...domain.intelligence import VerificationStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RelationshipType(str, Enum):
    HAS_INDUSTRY = "HAS_INDUSTRY"
    CONTAINS = "CONTAINS"
    BELONGS_TO = "BELONGS_TO"
    LOCATED_IN = "LOCATED_IN"
    PRODUCES = "PRODUCES"
    USES_INPUT = "USES_INPUT"
    SUPPLIES_TO = "SUPPLIES_TO"
    COOPERATES_WITH = "COOPERATES_WITH"
    COMPETES_WITH = "COMPETES_WITH"
    SUPPORTS = "SUPPORTS"
    DEVELOPS = "DEVELOPS"
    APPLIED_IN = "APPLIED_IN"
    OWNS = "OWNS"


def new_relation_id(
    source_entity_id: str,
    target_entity_id: str,
    relationship_type: RelationshipType | str,
) -> str:
    rel = (
        relationship_type.value
        if isinstance(relationship_type, RelationshipType)
        else str(relationship_type)
    )
    key = f"{source_entity_id}|{rel}|{target_entity_id}"
    digest = hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"rel_{digest}"


class KGRelation(BaseModel):
    """带证据溯源与时效的产业关系。

    强制约束：``verification_status=VERIFIED`` 时必须提供
    ``source_evidence_id`` 或 ``evidence_ids``，否则在模型层直接拒绝。
    这样 LLM 推测无法伪装成已证实关系。
    """

    id: str = ""
    source_entity_id: str
    target_entity_id: str
    relationship_type: RelationshipType
    source_evidence_id: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    verification_status: VerificationStatus = VerificationStatus.INFERRED
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    observed_at: datetime = Field(default_factory=_utcnow)
    properties: dict[str, Any] = Field(default_factory=dict)
    quote: str = ""
    extracted_by: str = ""

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        return value

    @model_validator(mode="after")
    def _validate_evidence_and_time(self) -> KGRelation:
        if self.verification_status == VerificationStatus.VERIFIED:
            if not (self.source_evidence_id or self.evidence_ids):
                raise ValueError(
                    "verified relation requires source_evidence_id or evidence_ids"
                )
        if self.source_entity_id == self.target_entity_id:
            raise ValueError("self-referencing relations are not allowed")
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from must not be later than valid_to")
        if not self.id:
            self.id = new_relation_id(
                self.source_entity_id, self.target_entity_id, self.relationship_type
            )
        return self

    def evidence_refs(self) -> list[str]:
        refs = list(self.evidence_ids)
        if self.source_evidence_id:
            refs.insert(0, self.source_evidence_id)
        return list(dict.fromkeys(r for r in refs if r))

    def is_active(self, as_of: datetime | None = None) -> bool:
        moment = as_of or _utcnow()
        if self.valid_from and moment < self.valid_from:
            return False
        if self.valid_to and moment > self.valid_to:
            return False
        return True


__all__ = ["KGRelation", "RelationshipType", "new_relation_id"]
