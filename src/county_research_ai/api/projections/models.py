"""Typed projections over the run-scoped evidence graph."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: str
    type: Literal[
        "county", "question", "evidence", "source", "topic", "gap", "conflict"
    ]
    label: str
    sublabel: str = ""
    weight: float = 1.0
    data: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: Literal[
        "has_question",
        "supported_by",
        "cited_from",
        "belongs_to",
        "has_gap",
        "conflicts_with",
    ]
    label: str = ""
    directed: bool = True
    weight: float = 1.0
    data: dict[str, Any] = Field(default_factory=dict)


class GraphMeta(BaseModel):
    total_nodes: int = 0
    returned_nodes: int = 0
    total_edges: int = 0
    returned_edges: int = 0
    truncated: bool = False
    coverage_rate: float | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    returned_counts: dict[str, int] = Field(default_factory=dict)
    dropped_self_loops: int = 0
    unmatched_conflicts: int = 0


class GraphView(BaseModel):
    run_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    meta: GraphMeta


class QuestionView(BaseModel):
    id: str
    title: str
    category: str = ""
    description: str = ""
    required_indicators: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    is_satisfied: bool = False


class QuestionsView(BaseModel):
    run_id: str
    county: str
    focus: str
    mode: str
    coverage_rate: float | None = None
    questions: list[QuestionView] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    reflection_turns: int = 0
    retrieval_stop_reason: str = ""


class CitationView(BaseModel):
    n: int
    evidence_id: str
    claim_id: str
    statement: str
    value: str = ""
    unit: str = ""
    period: str = ""
    title: str = ""
    url: str = ""
    credibility: float = 0.0
    domain_type: str = "unknown"
    year: str | None = None
    status: str = ""
    quote: str = ""


class ReportSectionView(BaseModel):
    id: str
    order: int
    title: str
    content: str
    status: Literal["completed"] = "completed"
    sources: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


class NarrativeSectionView(BaseModel):
    id: str
    order: int
    title: str
    content: str
    sources: list[str] = Field(default_factory=list)


class NarrativeView(BaseModel):
    provenance: Literal["native_sections", "markdown_split"]
    sections: list[NarrativeSectionView] = Field(default_factory=list)
    markdown_available: bool = False


class VerificationView(BaseModel):
    verified: int = 0
    unverified: int = 0
    total: int = 0
    notes: list[str] = Field(default_factory=list)
    per_section: dict[str, int] = Field(default_factory=dict)


class ReportView(BaseModel):
    run_id: str
    county: str
    focus: str
    mode: str
    generated_at: datetime
    version: str = "1.0"
    provenance: Literal["verified_structured_facts"] = "verified_structured_facts"
    sections: list[ReportSectionView]
    citations: list[CitationView]
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    claim_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    verification: VerificationView
    narrative: NarrativeView
    markdown_available: bool = True
    markdown: str = ""


class EvidenceLinkView(BaseModel):
    relation: str
    span_id: str
    quote: str
    snapshot_id: str
    url: str
    title: str
    start_offset: int | None = None
    end_offset: int | None = None


class EvidenceItemView(BaseModel):
    id: str
    claim_id: str
    statement: str
    snippet: str = ""
    metric: str = ""
    value: str = ""
    unit: str = ""
    period: str = ""
    scope: str = ""
    caliber: str = ""
    status: str = ""
    reason: str = ""
    topic: str = ""
    year: str | None = None
    credibility: float = 0.0
    url: str = ""
    title: str = ""
    domain_type: str = "unknown"
    citation_number: int | None = None
    question_ids: list[str] = Field(default_factory=list)
    links: list[EvidenceLinkView] = Field(default_factory=list)


class EvidenceListResponse(BaseModel):
    run_id: str
    items: list[EvidenceItemView]
    total: int
    limit: int
    offset: int
