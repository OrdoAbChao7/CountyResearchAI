"""Agent 执行轨迹的持久化。"""
from __future__ import annotations

import re
from datetime import timezone
from pathlib import Path
from typing import Protocol

from .models import AgentTrace


class TraceStore(Protocol):
    def save(self, trace: AgentTrace) -> Path: ...


class JsonTraceStore:
    """将一次运行的可审计摘要保存为 UTF-8 JSON。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def save(self, trace: AgentTrace) -> Path:
        county = _safe_segment(trace.request.county, fallback="county")
        timestamp = trace.started_at.astimezone(timezone.utc).strftime("%Y%m%d")
        path = self.root / county / timestamp / f"{trace.run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            trace.model_dump_json(indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path


def _safe_segment(value: str, *, fallback: str) -> str:
    segment = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", value, flags=re.UNICODE).strip("._")
    return segment or fallback
