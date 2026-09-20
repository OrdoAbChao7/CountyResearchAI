"""单次研究运行的跨阶段上下文。"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..domain.modes import normalize_request
from ..models import (
    AnalysisResult,
    CountyInfo,
    CountyLongHistoryAnalysis,
    CountyRiseFallAnalysis,
    DiscoveryResult,
    ProcessedData,
    RawDoc,
    ReportSection,
    ResearchReport,
    ResearchRequest,
)


class ResearchContext(BaseModel):
    request: ResearchRequest
    county: CountyInfo
    focus: str = ""
    raw_docs: list[RawDoc] = Field(default_factory=list)
    discovery: DiscoveryResult | None = None
    processed: ProcessedData | None = None
    snapshot_analyses: list[AnalysisResult] = Field(default_factory=list)
    rise_fall_analysis: CountyRiseFallAnalysis | None = None
    long_history_analysis: CountyLongHistoryAnalysis | None = None
    report: ResearchReport | None = None
    report_path: Path | None = None

    @classmethod
    def from_request(cls, request: ResearchRequest) -> ResearchContext:
        normalized = normalize_request(request)
        return cls(
            request=normalized,
            county=CountyInfo.from_name(normalized.county),
            focus=normalized.focus or "",
        )
