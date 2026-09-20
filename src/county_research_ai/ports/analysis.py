from __future__ import annotations

from typing import Protocol

from ..models import (
    AnalysisResult,
    CountyInfo,
    CountyLongHistoryAnalysis,
    CountyRiseFallAnalysis,
    DiscoveryResult,
    ProcessedData,
    RawDoc,
)


class SnapshotAnalyzerPort(Protocol):
    def analyze(
        self, county: CountyInfo, focus: str, data: ProcessedData
    ) -> list[AnalysisResult]: ...

    def generate_summary(
        self, county: CountyInfo, focus: str, analyses: list[AnalysisResult]
    ) -> str: ...

    def discover_focus(
        self, *, county: CountyInfo, raw_docs: list[RawDoc]
    ) -> DiscoveryResult: ...


class RiseFallAnalyzerPort(Protocol):
    def analyze(
        self, county: CountyInfo, data: ProcessedData
    ) -> CountyRiseFallAnalysis: ...


class LongHistoryAnalyzerPort(Protocol):
    def analyze(
        self, county: CountyInfo, data: ProcessedData
    ) -> CountyLongHistoryAnalysis: ...
