"""应用层结果模型。"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..models import ResearchReport
from .context import ResearchContext


class ResearchRunResult(BaseModel):
    report: ResearchReport
    report_path: Path
    context: ResearchContext | None = Field(default=None, exclude=True, repr=False)
