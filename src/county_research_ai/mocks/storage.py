"""Mock 存储实现。

MockStorage 是内存版 Storage,无需磁盘,用于单元测试。
生产链路请使用 LocalFSStorage(见 storage/local_fs.py)。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..models import ProcessedData, RawDoc
from ..storage.base import Storage

logger = logging.getLogger(__name__)


class MockStorage(Storage):
    """内存版 Storage — 用于单元测试,不依赖磁盘。

    正式生产链路请使用 LocalFSStorage(见 storage/local_fs.py)。
    """

    name = "mock-storage"

    def __init__(self) -> None:
        settings = get_settings()
        self._raw_dir = settings.data_dir / settings.storage.raw_subdir
        self._proc_dir = settings.data_dir / settings.storage.processed_subdir
        self._reports_dir = settings.reports_dir
        self._mem: dict[str, Any] = {}

    def save_raw(self, county: str, docs: list[RawDoc]) -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        layout = get_settings().storage.archive_layout
        sub = layout.format(county=county, date=date_str)
        p = self._raw_dir / sub
        p.mkdir(parents=True, exist_ok=True)
        f = p / "raw_docs.json"
        f.write_text(
            "[" + ",".join(d.model_dump_json(indent=2) for d in docs) + "]",
            encoding="utf-8",
        )
        return p

    def load_raw(self, county: str) -> list[RawDoc]:
        sub = self._raw_dir / county
        if not sub.exists():
            return []
        latest = sorted(sub.glob("*/raw_docs.json"), reverse=True)
        if not latest:
            return []
        data = json.loads(latest[0].read_text(encoding="utf-8"))
        return [RawDoc(**d) for d in data]

    def save_processed(self, county: str, focus: str, data: ProcessedData) -> Path:
        p = self._proc_dir / county
        p.mkdir(parents=True, exist_ok=True)
        f = p / f"{focus}.json"
        f.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        self._mem[f"{county}:{focus}"] = f
        return f

    def load_processed(
        self, county: str, focus: str, max_age_hours: int = 0
    ) -> ProcessedData | None:
        p = self._proc_dir / county / f"{focus}.json"
        if not p.exists():
            return None
        if max_age_hours > 0:
            import time
            age_h = (time.time() - p.stat().st_mtime) / 3600
            if age_h > max_age_hours:
                logger.info("processed 缓存已过期 | 县=%s | 方向=%s | 年龄=%.1fh",
                            county, focus, age_h)
                return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return ProcessedData(**data)

    def save_report(self, filename: str, content: str) -> Path:
        p = self._reports_dir / filename
        p.write_text(content, encoding="utf-8")
        logger.info("报告已写入: %s", p)
        return p
