from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from ..application.context import ResearchContext
from ..domain.research_contracts import EvidencePack
from ..evidence.bound_verifier import EvidenceBoundVerifier
from ..models import AnalysisResult, ResearchReport


class RenderedReport(BaseModel):
    report: ResearchReport
    markdown: str


class ResearchModeHandler(Protocol):
    name: str
    default_focus: str

    def analyze(self, context: ResearchContext) -> ResearchContext: ...

    def render(self, context: ResearchContext) -> RenderedReport: ...


def render_evidence_pack_appendix(context: ResearchContext) -> str:
    """Expose the ledger selection and evidence gaps in generated reports."""
    packs = evidence_packs_for_context(context)
    if not packs:
        return ""
    sections = ["\n\n---\n### Evidence-First 证据包审计\n"]
    for pack in packs:
        source_lines = [
            f"- [{source.source_title or source.canonical_url}]({source.canonical_url})"
            for source in pack.source_map.values()
            if source.canonical_url
        ]
        source_text = "\n".join(source_lines) or "- _无已选来源_"
        missing = "、".join(pack.missing_requirements) or "无"
        chunk_ids = "、".join(chunk.chunk_id for chunk in pack.selected_chunks) or "无"
        sections.append(
            f"\n#### {pack.research_slot.slot_id}（{pack.research_slot.time_period or '全时期'}）\n\n"
            f"- 状态：{pack.status}\n"
            f"- 已选片段：{len(pack.selected_chunks)}；已选事实：{len(pack.selected_claims)}\n"
            f"- Chunk ID：{chunk_ids}\n"
            f"- 未满足要求：{missing}\n"
            f"- 来源映射：\n{source_text}\n"
        )
    return "".join(sections)


def evidence_packs_for_context(context: ResearchContext) -> list[EvidencePack]:
    return context.evidence_packs or ([context.evidence_pack] if context.evidence_pack else [])


def audit_analysis_results(
    context: ResearchContext, analyses: list[AnalysisResult]
) -> list[AnalysisResult]:
    packs = evidence_packs_for_context(context)
    if not packs:
        return analyses
    verifier = EvidenceBoundVerifier()
    audited = []
    for analysis in analyses:
        content, _ = verifier.verify_markdown(
            analysis.content, packs, county=context.county.name
        )
        audited.append(analysis.model_copy(update={"content": content}))
    return audited


def audit_markdown(context: ResearchContext, markdown: str) -> str:
    packs = evidence_packs_for_context(context)
    if not packs:
        return markdown
    audited, _ = EvidenceBoundVerifier().verify_markdown(
        markdown, packs, county=context.county.name
    )
    return audited
