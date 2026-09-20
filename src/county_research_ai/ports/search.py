from __future__ import annotations

from typing import Protocol

from ..domain.modes import ResearchMode
from ..models import RawDoc


class SearchPort(Protocol):
    def collect(
        self, county: str, focus: str, max_results: int, *, mode: ResearchMode
    ) -> list[RawDoc]: ...
