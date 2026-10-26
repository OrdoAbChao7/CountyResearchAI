"""Canonical Evidence-First contracts with legacy workflow compatibility."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class EvidenceChunk(BaseModel):
    chunk_id: str
    document_id: str = ""
    parent_chunk_id: str = ""
    text: str = ""
    heading: str = ""
    start_offset: int | None = None
    end_offset: int | None = None
    offset_status: Literal["exact", "limited", "unknown"] = "unknown"
    year_hints: list[str] = Field(default_factory=list)
    metric_hints: list[str] = Field(default_factory=list)
    content_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_source_id(cls, values: Any) -> Any:
        if isinstance(values, dict) and not values.get("document_id"):
            values = dict(values)
            values["document_id"] = values.get("source_id", "")
        return values

    @property
    def source_id(self) -> str:
        return self.document_id


class SourceDocument(BaseModel):
    doc_id: str
    canonical_url: str = ""
    source_title: str = ""
    content: str = ""
    content_hash: str = ""
    publish_date: datetime | None = None
    retrieved_at: datetime | None = None
    source_type: str = "unknown"
    administrative_scope: str = ""
    raw_storage_path: str = ""
    fetch_status: str = "unknown"
    provider: str = "unknown"
    metadata: dict[str, object] = Field(default_factory=dict)
    chunks: list[EvidenceChunk] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_source_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        values = dict(values)
        values.setdefault("source_title", values.get("title", ""))
        values.setdefault("canonical_url", values.get("url", ""))
        values.setdefault(
            "publish_date",
            values.get("published_at", values.get("document_timestamp")),
        )
        return values

    @property
    def title(self) -> str:
        return self.source_title

    @property
    def url(self) -> str:
        return self.canonical_url

    @property
    def document_timestamp(self) -> datetime | None:
        return self.publish_date

    @property
    def published_at(self) -> datetime | None:
        return self.publish_date


class AtomicClaim(BaseModel):
    claim_id: str
    statement: str
    region_id: str = ""
    metric_id: str = ""
    value: str = ""
    unit: str = ""
    period: str = ""
    administrative_scope: str = ""
    statistical_caliber: str = ""
    series_version: str = ""
    source_ids: list[str] = Field(default_factory=list)
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    verification_status: str = "unverified"
    verification_reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_claim_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        values = dict(values)
        aliases = {
            "region_id": "region",
            "metric_id": "metric",
            "administrative_scope": "scope",
            "statistical_caliber": "caliber",
            "series_version": "version",
        }
        for canonical, legacy in aliases.items():
            if not values.get(canonical):
                values[canonical] = values.get(legacy, "")
        return values

    @property
    def region(self) -> str:
        return self.region_id

    @property
    def metric(self) -> str:
        return self.metric_id

    @property
    def scope(self) -> str:
        return self.administrative_scope

    @property
    def caliber(self) -> str:
        return self.statistical_caliber

    @property
    def version(self) -> str:
        return self.series_version

    def normalized_numeric_value(self) -> Decimal | None:
        """Return currency-like values in 万元 when the unit is supported."""
        if not self.value:
            return None
        try:
            numeric = Decimal(str(self.value).replace(",", ""))
        except (InvalidOperation, ValueError):
            return None
        multiplier = {
            "万元": Decimal("1"),
            "万": Decimal("1"),
            "亿元": Decimal("10000"),
            "亿": Decimal("10000"),
        }.get(self.unit)
        return numeric * multiplier if multiplier is not None else None


class QuestionSlot(BaseModel):
    slot_id: str
    research_question: str
    required_metrics: list[str] = Field(default_factory=list)
    region: str = ""
    time_period: str = ""
    priority: int = 0
    evidence_requirement: str = ""
    completion_status: str = "pending"
    budget_chars: int = 12000

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_question_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        values = dict(values)
        values.setdefault("research_question", values.get("question", ""))
        values.setdefault("time_period", values.get("period", ""))
        return values

    @property
    def question(self) -> str:
        return self.research_question

    @property
    def period(self) -> str:
        return self.time_period


class ResearchSpec(BaseModel):
    region_id: str
    region_name: str
    mode: str = "snapshot"
    research_focus: str = ""
    target_years: list[str] = Field(default_factory=list)
    required_question_slots: list[QuestionSlot] = Field(default_factory=list)
    budget: int = 12000
    architecture_version: Literal[
        "workflow_legacy", "deep_legacy", "evidence_first_v2"
    ] = "evidence_first_v2"

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_research_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        values = dict(values)
        values.setdefault("region_name", values.get("county", ""))
        values.setdefault(
            "region_id", values.get("county", values.get("region_name", ""))
        )
        values.setdefault("research_focus", values.get("focus", ""))
        values.setdefault(
            "required_question_slots", values.get("question_slots", [])
        )
        values.setdefault(
            "architecture_version", values.get("contract_version", "evidence_first_v2")
        )
        if values["architecture_version"] == "evidence-first-v2":
            values["architecture_version"] = "evidence_first_v2"
        return values

    @property
    def county(self) -> str:
        return self.region_name

    @property
    def focus(self) -> str:
        return self.research_focus

    @property
    def question_slots(self) -> list[QuestionSlot]:
        return self.required_question_slots

    @property
    def contract_version(self) -> str:
        return self.architecture_version


class EvidencePack(BaseModel):
    research_slot: QuestionSlot
    selected_claims: list[AtomicClaim] = Field(default_factory=list)
    selected_chunks: list[EvidenceChunk] = Field(default_factory=list)
    source_map: dict[str, SourceDocument] = Field(default_factory=dict)
    token_budget: int
    selected_evidence_reasons: dict[str, str] = Field(default_factory=dict)
    excluded_evidence_reasons: dict[str, str] = Field(default_factory=dict)
    missing_requirements: list[str] = Field(default_factory=list)
    total_chars: int = 0
    status: Literal["complete", "partial", "empty"] = "empty"
    pack_id: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_pack_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        values = dict(values)
        slot = values.get("research_slot")
        if slot is None and values.get("slot_id"):
            slot = QuestionSlot(
                slot_id=values["slot_id"],
                research_question=values.get("question", ""),
            )
            values["research_slot"] = slot
        values.setdefault("selected_claims", values.get("claims", []))
        values.setdefault("selected_chunks", values.get("chunks", []))
        values.setdefault("token_budget", values.get("budget_chars", 0))
        values.setdefault(
            "selected_evidence_reasons", values.get("selection_reasons", {})
        )
        omitted = values.get("omitted_chunk_ids", [])
        values.setdefault(
            "excluded_evidence_reasons",
            {chunk_id: "legacy_excluded" for chunk_id in omitted},
        )
        return values

    @property
    def slot_id(self) -> str:
        return self.research_slot.slot_id

    @property
    def chunks(self) -> list[EvidenceChunk]:
        return self.selected_chunks

    @property
    def claims(self) -> list[AtomicClaim]:
        return self.selected_claims

    @property
    def budget_chars(self) -> int:
        return self.token_budget

    @property
    def omitted_chunk_ids(self) -> list[str]:
        return list(self.excluded_evidence_reasons)

    @property
    def selection_reasons(self) -> dict[str, str]:
        return self.selected_evidence_reasons

