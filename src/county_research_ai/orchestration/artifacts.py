"""运行产物：检查点之外的证据、文档与报告文件。

LangGraph 检查点保证图状态可恢复；这里持久化大对象与原始资料，
使进程重启后仍能恢复证据库并继续研究。
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import RawDoc
from ..services.evidence_service import EvidenceService


@dataclass
class RunArtifacts:
    run_id: str
    run_dir: Path
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    # ---- JSON ----

    def write_json(self, name: str, data: Any) -> Path:
        path = self.run_dir / name
        tmp = self.run_dir / f".{name}.{os.getpid()}.{threading.get_ident()}.tmp"
        with self._lock:
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        return path

    def read_json(self, name: str, default: Any = None) -> Any:
        path = self.run_dir / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def write_text(self, name: str, text: str) -> Path:
        path = self.run_dir / name
        tmp = self.run_dir / f".{name}.{os.getpid()}.{threading.get_ident()}.tmp"
        with self._lock:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        return path

    def read_text(self, name: str, default: str = "") -> str:
        path = self.run_dir / name
        if not path.exists():
            return default
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return default

    # ---- 证据 ----

    def save_evidence(self, evidence: EvidenceService) -> Path:
        with self._lock:
            return evidence.persist(self.run_dir / "evidence.json")

    def load_evidence(self, evidence: EvidenceService) -> int:
        path = self.run_dir / "evidence.json"
        if not path.exists():
            return 0
        try:
            return evidence.load(path)
        except Exception:  # noqa: BLE001
            return 0

    # ---- 文档 ----

    def save_docs(self, docs: list[RawDoc]) -> Path:
        payload = [doc.model_dump(mode="json") for doc in docs]
        return self.write_json("documents.json", payload)

    def load_docs(self) -> list[RawDoc]:
        payload = self.read_json("documents.json", default=[]) or []
        docs: list[RawDoc] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            try:
                docs.append(RawDoc.model_validate(raw))
            except Exception:  # noqa: BLE001
                continue
        return docs


__all__ = ["RunArtifacts"]
