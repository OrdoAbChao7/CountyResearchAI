from __future__ import annotations

from typing import Protocol

from ..models import CountyInfo, ProcessedData, RawDoc


class ProcessingPort(Protocol):
    def process(
        self, raw_docs: list[RawDoc], *, county: CountyInfo, focus: str
    ) -> ProcessedData: ...
