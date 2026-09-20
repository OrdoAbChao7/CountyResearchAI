from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..models import ProcessedData, RawDoc


class StoragePort(Protocol):
    def save_raw(self, county: str, docs: list[RawDoc]) -> Path: ...

    def load_processed(
        self, county: str, focus: str, max_age_hours: int = 0
    ) -> ProcessedData | None: ...

    def save_processed(self, county: str, focus: str, data: ProcessedData) -> Path: ...

    def save_report(self, filename: str, content: str) -> Path: ...
