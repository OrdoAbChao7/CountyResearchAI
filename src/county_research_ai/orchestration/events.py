"""运行事件存储：JSONL 追加 + 内存索引（供 SSE 与审计使用）。"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ..domain.events import RunEvent


class RunEventStore:
    """线程安全的事件存储。

    事件按 run 单独存放，seq 单调递增；SSE 通过 ``after(seq)`` 增量读取。
    """

    def __init__(self, run_id: str, run_dir: Path) -> None:
        self.run_id = run_id
        self.path = Path(run_dir) / "events.jsonl"
        self._lock = threading.RLock()
        self._events: list[RunEvent] = []
        self._seq = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        event = RunEvent.model_validate_json(line)
                    except Exception:  # noqa: BLE001
                        continue
                    self._events.append(event)
                    self._seq = max(self._seq, event.seq)
        except OSError:
            return

    def emit(
        self,
        event_type: str,
        *,
        agent: str = "",
        node: str = "",
        message: str = "",
        data: dict[str, Any] | None = None,
    ) -> RunEvent:
        with self._lock:
            self._seq += 1
            event = RunEvent(
                seq=self._seq,
                run_id=self.run_id,
                type=event_type,
                agent=agent,
                node=node,
                message=message,
                data=data or {},
            )
            self._events.append(event)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(event.model_dump_json() + "\n")
            except OSError:
                pass
            return event

    def callback(
        self, event_type: str, agent: str, message: str, data: dict[str, Any]
    ) -> None:
        """适配 ``EventCallback`` 签名，供 AgentContext 使用。"""
        payload = dict(data or {})
        node = str(payload.pop("node", ""))
        self.emit(
            event_type,
            agent=agent,
            node=node,
            message=message,
            data=payload,
        )

    def after(self, seq: int = 0, *, limit: int = 500) -> list[RunEvent]:
        with self._lock:
            events = [event for event in self._events if event.seq > seq]
        return events[:limit]

    def all(self) -> list[RunEvent]:
        with self._lock:
            return list(self._events)

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq


__all__ = ["RunEventStore"]
