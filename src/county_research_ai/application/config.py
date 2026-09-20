from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchApplicationConfig:
    max_search_results: int
    cache_enabled: bool
    cache_ttl_hours: int
    report_filename_template: str
