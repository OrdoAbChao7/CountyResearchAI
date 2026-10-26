"""Research outcome vocabulary shared by the engine, API, and evaluators."""
from __future__ import annotations

from enum import StrEnum


class ResearchOutcome(StrEnum):
    """Why a research run finished.

    These are intentionally disjoint. A run that stops because it ran out of
    budget must never be reported as having sufficient evidence.
    """

    SUFFICIENT = "SUFFICIENT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    NO_PROGRESS = "NO_PROGRESS"
    CONFLICT_UNRESOLVED = "CONFLICT_UNRESOLVED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
