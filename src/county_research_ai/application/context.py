"""单次研究运行的跨阶段上下文。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.modes import normalize_request
from ..domain.research_contracts import EvidencePack, ResearchSpec
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


class ResearchContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: ResearchRequest
    county: CountyInfo
    focus: str = ""
    raw_docs: list[RawDoc] = Field(default_factory=list)
    discovery: DiscoveryResult | None = None
    processed: ProcessedData | None = None
    research_spec: ResearchSpec | None = None
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

    @classmethod
    def from_request(cls, request: ResearchRequest) -> ResearchContext:
        normalized = normalize_request(request)
        return cls(
            request=normalized,
            county=CountyInfo.from_name(normalized.county),
            focus=normalized.focus or "",
        )
