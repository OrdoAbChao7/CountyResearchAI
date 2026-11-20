"""Question-tree projection with coverage, gaps and conflicts."""
from __future__ import annotations

from ..jobs import JobRecord
from .common import deep_projection
from .models import QuestionsView, QuestionView


def build_questions_view(job: JobRecord) -> QuestionsView:
    deep = deep_projection(job)
    tree = deep.get("question_tree") or {}
    questions = [
        QuestionView(
            id=str(question.get("id", "")),
            title=str(question.get("title", "")),
            category=str(question.get("category", "")),
            description=str(question.get("description", "")),
            required_indicators=list(question.get("required_indicators", []) or []),
            evidence_ids=[str(value) for value in question.get("evidence_ids", []) or []],
            is_satisfied=bool(question.get("is_satisfied")),
        )
        for question in tree.get("questions", []) or []
    ]
    return QuestionsView(
        run_id=job.job_id,
        county=str(tree.get("county", job.county)),
        focus=str(tree.get("focus", job.focus)),
        mode=str(tree.get("mode", job.mode)),
        coverage_rate=deep.get("coverage_rate"),
        questions=questions,
        gaps=list(deep.get("gaps") or []),
        conflicts=list(deep.get("conflicts") or []),
        reflection_turns=int(deep.get("reflection_turns", 0) or 0),
        retrieval_stop_reason=str(deep.get("retrieval_stop_reason", "")),
    )


__all__ = ["build_questions_view"]
