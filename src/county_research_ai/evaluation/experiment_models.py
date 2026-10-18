"""独立实验的运行状态、产物和配置哈希模型。"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RunStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    VALID = "VALID"
    INVALID_MOCK = "INVALID_MOCK"
    INVALID_CONFIG = "INVALID_CONFIG"
    INVALID_USAGE_UNKNOWN = "INVALID_USAGE_UNKNOWN"
    INVALID_RESOURCE_ACCOUNTING = "INVALID_RESOURCE_ACCOUNTING"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NOT_RUN = "NOT_RUN"


_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.PLANNED: {RunStatus.RUNNING, RunStatus.BLOCKED, RunStatus.NOT_RUN},
    RunStatus.RUNNING: {
        RunStatus.VALID,
        RunStatus.INVALID_MOCK,
        RunStatus.INVALID_CONFIG,
        RunStatus.INVALID_USAGE_UNKNOWN,
        RunStatus.INVALID_RESOURCE_ACCOUNTING,
        RunStatus.BUDGET_EXHAUSTED,
        RunStatus.FAILED,
        RunStatus.BLOCKED,
    },
    RunStatus.VALID: set(),
    RunStatus.INVALID_MOCK: set(),
    RunStatus.INVALID_CONFIG: set(),
    RunStatus.FAILED: set(),
    RunStatus.BLOCKED: set(),
    RunStatus.NOT_RUN: set(),
}


@dataclass
class RunManifest:
    run_id: str
    experiment_id: str
    group: str
    county: str
    task_id: str
    mode: str
    model: str
    search_provider: str
    config_hash: str
    formal_target: bool = False
    status: RunStatus = RunStatus.PLANNED
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    artifacts: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    duration_seconds: float | None = None
    resource_usage: dict[str, int] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        experiment_id: str,
        group: str,
        county: str,
        task_id: str,
        mode: str,
        model: str,
        search_provider: str,
        config: dict[str, Any],
    ) -> RunManifest:
        return cls(
            run_id=run_id,
            experiment_id=experiment_id,
            group=group,
            county=county,
            task_id=task_id,
            mode=mode,
            model=model,
            search_provider=search_provider,
            config_hash=config_hash(config),
            formal_target=bool(config.get("formal_target", False)),
        )

    def transition(self, status: RunStatus, *, error: str | None = None) -> None:
        status = RunStatus(status)
        if status not in _TRANSITIONS[self.status]:
            raise ValueError(f"invalid run transition: {self.status} -> {status}")
        self.status = status
        self.updated_at = _now()
        if error is not None:
            self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "experiment_id": self.experiment_id,
            "group": self.group,
            "county": self.county,
            "task_id": self.task_id,
            "mode": self.mode,
            "model": self.model,
            "search_provider": self.search_provider,
            "config_hash": self.config_hash,
            "formal_target": self.formal_target,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "artifacts": dict(self.artifacts),
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "resource_usage": dict(self.resource_usage),
        }

    def write(self, path: Path) -> None:
        _atomic_write_json(Path(path), self.to_dict())


@dataclass(frozen=True)
class RunArtifact:
    root: Path

    def write_text(self, name: str, content: str) -> tuple[Path, str]:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(path, content.encode("utf-8"))
        return path, self.sha256(path)

    def write_json(self, name: str, value: Any) -> tuple[Path, str]:
        content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return self.write_text(name, content)

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _path(self, name: str) -> Path:
        path = (self.root / name).resolve()
        root = self.root.resolve()
        if root != path and root not in path.parents:
            raise ValueError("artifact path escapes run directory")
        return path


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    _atomic_write_bytes(path, content.encode("utf-8"))


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    finally:
        temporary_path = Path(temporary)
        if temporary_path.exists():
            temporary_path.unlink()
