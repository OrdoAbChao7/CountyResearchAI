from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..models import (
    CountyLongHistoryAnalysis,
    CountyRiseFallAnalysis,
    RawDoc,
    ResearchReport,
)

FilenameRenderer = Callable[[str, dict[str, str]], str]


class SnapshotRendererPort(Protocol):
    def render_markdown(self, report: ResearchReport) -> str: ...


class RiseFallRendererPort(Protocol):
    def render(
        self, analysis: CountyRiseFallAnalysis, raw_docs: list[RawDoc]
    ) -> str: ...


class LongHistoryRendererPort(Protocol):
    def render(
        self, analysis: CountyLongHistoryAnalysis, raw_docs: list[RawDoc]
    ) -> str: ...
