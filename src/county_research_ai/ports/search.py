from __future__ import annotations

from datetime import date
from typing import Protocol

from ..domain.modes import ResearchMode
from ..models import RawDoc


class SearchPort(Protocol):
    def collect(
        self,
        county: str,
        focus: str,
        max_results: int,
        *,
        mode: ResearchMode,
        date_start: date | None = None,
        date_end: date | None = None,
        target_years: list[str] | None = None,
    ) -> list[RawDoc]: ...
