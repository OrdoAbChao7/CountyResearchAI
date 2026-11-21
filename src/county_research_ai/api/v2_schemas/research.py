from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ...domain.intelligence import ResearchRunRequest


class ResearchRunCreate(BaseModel):
    county: str = Field(min_length=2, max_length=40)
    focus: str | None = Field(default=None, max_length=60)
    objectives: list[str] = Field(default_factory=list, max_length=10)
    mode: str = "snapshot"
    options: dict[str, Any] = Field(default_factory=dict)

    def to_domain(self) -> ResearchRunRequest:
        return ResearchRunRequest(
            county=self.county.strip(),
            focus=(self.focus or "").strip() or None,
            objectives=[o.strip() for o in self.objectives if o.strip()],
            mode=self.mode,
            options=self.options,
        )


class ReportResponse(BaseModel):
    run_id: str
    markdown: str
    path: str = ""


__all__ = ["ReportResponse", "ResearchRunCreate"]
