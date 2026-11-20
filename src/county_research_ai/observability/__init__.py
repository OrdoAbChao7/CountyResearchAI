"""与 Web 适配层解耦的运行观察层。

研究引擎只依赖本模块的 ``emit`` 与 ``bind_event_sink``；未绑定 sink 时
（例如 CLI 正常运行）所有事件自动丢弃，不改变原有行为。
"""
from __future__ import annotations

from .events import (
    EventDraft,
    EventLevel,
    EventSink,
    NullEventSink,
    bind_event_sink,
    emit,
    pop_event_sink,
    push_event_sink,
)

__all__ = [
    "EventDraft",
    "EventLevel",
    "EventSink",
    "NullEventSink",
    "bind_event_sink",
    "emit",
    "pop_event_sink",
    "push_event_sink",
]
