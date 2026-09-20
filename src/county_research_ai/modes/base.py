from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from ..application.context import ResearchContext
from ..models import ResearchReport


class RenderedReport(BaseModel):
    report: ResearchReport
    markdown: str


class ResearchModeHandler(Protocol):
    name: str
    default_focus: str

    def analyze(self, context: ResearchContext) -> ResearchContext: ...

    def render(self, context: ResearchContext) -> RenderedReport: ...
