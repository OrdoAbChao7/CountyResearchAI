"""Canonical Evidence-First contracts with legacy workflow compatibility."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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


class DateWindow(BaseModel):
    """Inclusive research window. ``None`` means unbounded on that side."""

    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> DateWindow:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("date_window.start must not be after date_window.end")
        return self

    @property
    def is_set(self) -> bool:
        return self.start is not None or self.end is not None

    def contains(self, value: date) -> bool:
        if self.start is not None and value < self.start:
            return False
        if self.end is not None and value > self.end:
            return False
        return True


class EvidenceThresholds(BaseModel):
    """What must be true before a run may finish as SUFFICIENT."""

    min_independent_sources: int = Field(default=1, ge=0)
    min_supported_claims: int = Field(default=0, ge=0)
    min_supported_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_requirement: str = ""


class BudgetCaps(BaseModel):
    """Hard caps. Zero means "not set" except max_steps, which must be positive."""

    max_steps: int = Field(default=8, ge=1, le=50)
    max_search_calls: int = Field(default=3, ge=0, le=100)
    max_tokens: int = Field(default=0, ge=0, le=1_000_000)
    max_cost: float = Field(default=0.0, ge=0.0, le=10_000.0)
    deadline_seconds: float = Field(default=0.0, ge=0.0, le=86_400.0)
    max_documents: int = Field(default=0, ge=0, le=500)


class RequestedOutput(BaseModel):
    format: Literal["decision_brief", "report", "json"] = "decision_brief"
    language: Literal["zh", "en"] = "zh"
    include_evidence_appendix: bool = True
    max_words: int = Field(default=0, ge=0)


class ResearchContract(BaseModel):
    """User-facing research contract with explicit scope, thresholds, and caps.

    ``ResearchSpec`` remains the internal planning representation. This model is
    the validated boundary used by the API and evaluation harnesses so a run
    cannot silently ignore its budget, scope, or evidence requirements.
    """

    objective: str = Field(min_length=1, max_length=2000)
    regions: list[str] = Field(min_length=1, max_length=10)
    date_window: DateWindow = Field(default_factory=DateWindow)
    required_questions: list[str] = Field(default_factory=list, max_length=20)
    evidence_thresholds: EvidenceThresholds = Field(default_factory=EvidenceThresholds)
    budget: BudgetCaps = Field(default_factory=BudgetCaps)
    requested_output: RequestedOutput = Field(default_factory=RequestedOutput)
    domain_adapter: str = Field(default="county_industry", min_length=1)
    mode: str = "snapshot"
    research_focus: str = ""
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("objective", "domain_adapter")
    @classmethod
    def _non_empty_text(cls, value: str, info: Any) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{info.field_name} must not be blank")
        return stripped

    @field_validator("regions")
    @classmethod
    def _valid_regions(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for region in value:
            stripped = region.strip()
            if not stripped:
                raise ValueError("regions must not contain blank entries")
            if stripped not in cleaned:
                cleaned.append(stripped)
        if not cleaned:
            raise ValueError("regions must contain at least one region")
        return cleaned

    @field_validator("required_questions")
    @classmethod
    def _valid_questions(cls, value: list[str]) -> list[str]:
        cleaned = [question.strip() for question in value]
        if any(not question for question in cleaned):
            raise ValueError("required_questions must not contain blank entries")
        if any(len(question) > 500 for question in cleaned):
            raise ValueError("each required_question must be at most 500 characters")
        return cleaned

    def to_research_spec(self) -> ResearchSpec:
        region_name = self.regions[0]
        focus = self.research_focus or self.objective
        slots = [
            QuestionSlot(
                slot_id=f"contract:{index}",
                research_question=question,
                region=region_name,
                time_period=_period_label(self.date_window),
                priority=index,
                evidence_requirement=self.evidence_thresholds.evidence_requirement,
                budget_chars=self.budget.max_tokens or 12000,
            )
            for index, question in enumerate(self.required_questions)
        ]
        return ResearchSpec(
            region_id=region_name,
            region_name=region_name,
            research_focus=focus,
            mode=self.mode,
            target_years=_window_years(self.date_window),
            required_question_slots=slots,
            budget=self.budget.max_tokens or 12000,
            architecture_version="evidence_first_v2",
        )

    @classmethod
    def from_research_spec(cls, spec: ResearchSpec) -> ResearchContract:
        return cls(
            objective=spec.research_focus or f"{spec.region_name} 研究",
            regions=[spec.region_name],
            required_questions=[slot.research_question for slot in spec.required_question_slots],
            budget=BudgetCaps(max_tokens=spec.budget),
            mode=spec.mode,
            research_focus=spec.research_focus,
        )


def _window_years(window: DateWindow) -> list[str]:
    years: list[str] = []
    if window.start is not None:
        years.append(str(window.start.year))
    if window.end is not None and str(window.end.year) not in years:
        years.append(str(window.end.year))
    return years


def _period_label(window: DateWindow) -> str:
    if window.start is not None and window.end is not None:
        return f"{window.start.isoformat()}~{window.end.isoformat()}"
    if window.start is not None:
        return f"{window.start.isoformat()}~"
    if window.end is not None:
        return f"~{window.end.isoformat()}"
    return ""


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

