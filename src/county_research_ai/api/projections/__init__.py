"""Run-scoped projection APIs over evidence and report artifacts."""
from __future__ import annotations

from .common import ProjectionUnavailable, deep_projection
from .evidence import build_evidence_list
from .graph import build_graph_view
from .models import (
    CitationView,
    EvidenceItemView,
    EvidenceLinkView,
    EvidenceListResponse,
    GraphEdge,
    GraphMeta,
    GraphNode,
    GraphView,
    NarrativeSectionView,
    NarrativeView,
    QuestionsView,
    QuestionView,
    ReportSectionView,
    ReportView,
    VerificationView,
)
from .questions import build_questions_view
from .report import build_report_view, split_markdown_sections

__all__ = [
    "CitationView",
    "EvidenceItemView",
    "EvidenceLinkView",
    "EvidenceListResponse",
    "GraphEdge",
    "GraphMeta",
    "GraphNode",
    "GraphView",
    "NarrativeSectionView",
    "NarrativeView",
    "ProjectionUnavailable",
    "QuestionView",
    "QuestionsView",
    "ReportSectionView",
    "ReportView",
    "VerificationView",
    "build_evidence_list",
    "build_graph_view",
    "build_questions_view",
    "build_report_view",
    "deep_projection",
    "split_markdown_sections",
]
