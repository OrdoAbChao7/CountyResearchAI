"""可恢复实验检查点。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .experiment_models import _atomic_write_json, config_hash


class CheckpointStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(self, *, config: dict[str, Any], state: dict[str, Any]) -> None:
        _atomic_write_json(
            self.path,
            {
                "config_hash": config_hash(config),
                "state": state,
            },
        )

    def start(self, *, config: dict[str, Any], resume: bool = False) -> dict[str, Any]:
        """Create a batch checkpoint or reopen one with the same configuration."""
        if self.path.exists():
            if not resume:
                raise FileExistsError(f"checkpoint already exists: {self.path}")
            payload = self.load(config=config)
            state = payload.get("state")
            if not isinstance(state, dict):
                raise ValueError("checkpoint state must be an object")
            return state
        if resume:
            raise FileNotFoundError(f"checkpoint does not exist: {self.path}")
        state = {"completed": {}}
        self.save(config=config, state=state)
        return state

    def record(self, *, config: dict[str, Any], run_id: str, status: str) -> dict[str, Any]:
        """Persist one terminal run status and return the updated state."""
        payload = self.load(config=config)
        state = payload.get("state")
        if not isinstance(state, dict):
            raise ValueError("checkpoint state must be an object")
        completed = state.get("completed", {})
        if not isinstance(completed, dict):
            raise ValueError("checkpoint completed state must be an object")
        updated = dict(state)
        updated["completed"] = {**completed, run_id: status}
        self.save(config=config, state=updated)
        return updated

    def load(self, *, config: dict[str, Any]) -> dict[str, Any]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        expected = config_hash(config)
        if payload.get("config_hash") != expected:
            raise ValueError("configuration hash mismatch")
        return payload
