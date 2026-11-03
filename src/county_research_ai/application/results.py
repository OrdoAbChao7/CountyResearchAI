"""应用层结果模型。"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from ..models import ResearchReport


class ResearchRunResult(BaseModel):
    report: ResearchReport
    report_path: Path
