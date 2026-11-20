"""运行事件模型与上下文绑定的事件总线。"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

EventLevel = Literal["debug", "info", "warn", "error"]


class EventDraft(BaseModel):
    """一条尚未分配 run_id / seq 的事件。"""

    type: str
    stage: str | None = None
    level: EventLevel = "info"
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class EventSink(Protocol):
    """事件接收端；实现方负责持久化与分配序号。"""

    def emit(self, draft: EventDraft) -> None: ...


class NullEventSink:
    """显式空实现，便于测试或需要占位的调用方。"""

    def emit(self, draft: EventDraft) -> None:
        return None


_sink: ContextVar[EventSink | None] = ContextVar(
    "county_research_event_sink",
    default=None,
)


@contextmanager
def bind_event_sink(sink: EventSink) -> Iterator[None]:
    """在当前上下文绑定事件接收端，退出时恢复上一个绑定。

    注意：``contextvars`` 不会自动传播到新建线程。Web 执行器必须在
    实际运行研究的 worker 线程内部绑定，而不是只在请求线程绑定。
    """

    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def push_event_sink(sink: EventSink) -> Token:
    """Bind a sink without a ``with`` block; the caller must reset the token.

    This is the explicit counterpart to :func:`bind_event_sink` for executors
    that already own a ``try/finally`` and must not restructure it.
    """

    return _sink.set(sink)


def pop_event_sink(token: Token) -> None:
    _sink.reset(token)


def emit(
    type: str,
    *,
    stage: str | None = None,
    level: EventLevel = "info",
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    """发送一条事件；未绑定 sink 或 sink 异常时静默跳过。

    观察层不能反过来中断研究流程，因此这里吞掉 sink 的所有异常。
    """

    sink = _sink.get()
    if sink is None:
        return
    try:
        sink.emit(
            EventDraft(
                type=type,
                stage=stage,
                level=level,
                message=message,
                payload=payload or {},
            )
        )
    except Exception:  # noqa: BLE001 - 观察失败不得影响研究
        return None


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
