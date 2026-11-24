"""单次研究运行的跨阶段上下文。"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.modes import normalize_request
from ..domain.research_contracts import EvidencePack, QuestionSlot, ResearchSpec, SourceDocument
from ..evidence.ledger import EvidenceLedger
from ..models import (
    AnalysisResult,
    CountyInfo,
    CountyLongHistoryAnalysis,
    CountyRiseFallAnalysis,
    DiscoveryResult,
    ProcessedData,
    RawDoc,
    ResearchReport,
    ResearchRequest,
)
from ..search.request_history import SearchRequestHistory


class ResearchContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: ResearchRequest
    county: CountyInfo
    focus: str = ""
    raw_docs: list[RawDoc] = Field(default_factory=list)
    search_history: SearchRequestHistory = Field(
        default_factory=SearchRequestHistory, exclude=True, repr=False
    )
    discovery: DiscoveryResult | None = None
    processed: ProcessedData | None = None
    research_spec: ResearchSpec | None = None
    source_credibility_check: Callable[[SourceDocument], bool] | None = Field(
        default=None, exclude=True, repr=False
    )
    evidence_ledger: EvidenceLedger | None = None
    evidence_pack: EvidencePack | None = None
    evidence_packs: list[EvidencePack] = Field(default_factory=list)
    snapshot_analyses: list[AnalysisResult] = Field(default_factory=list)
    rise_fall_analysis: CountyRiseFallAnalysis | None = None
    long_history_analysis: CountyLongHistoryAnalysis | None = None
    report: ResearchReport | None = None
    report_path: Path | None = None
    # The coordinator result is intentionally excluded from serialisation: it
    # holds a live EvidenceStore and is consumed by the projection layer in the
    # same process. Keeping it here avoids a second result type or a parallel
    # in-memory registry.
    deep_research: Any | None = Field(default=None, exclude=True, repr=False)

    @property
    def contract_question_slots(self) -> list[QuestionSlot]:
        if self.research_spec is None:
            return []
        return [slot for slot in self.research_spec.question_slots if slot.is_contract_question]

    @classmethod
    def from_request(
        cls,
        request: ResearchRequest,
        *,
        research_spec: ResearchSpec | None = None,
        source_credibility_check: Callable[[SourceDocument], bool] | None = None,
    ) -> ResearchContext:
        normalized = normalize_request(request)
        return cls(
            request=normalized,
            county=CountyInfo.from_name(normalized.county),
            focus=normalized.focus or "",
            research_spec=research_spec,
            source_credibility_check=source_credibility_check,
        )
