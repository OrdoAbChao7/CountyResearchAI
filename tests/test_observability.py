"""观察层事件总线测试。"""
from __future__ import annotations

import threading

from county_research_ai.observability.events import (
    EventDraft,
    NullEventSink,
    bind_event_sink,
    emit,
)


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[EventDraft] = []

    def emit(self, draft: EventDraft) -> None:
        self.events.append(draft)


class ExplodingSink:
    def emit(self, draft: EventDraft) -> None:
        raise RuntimeError("sink down")


def test_emit_without_sink_is_noop() -> None:
    # Should not raise even though no sink is bound.
    emit("stage.started", stage="collect")


def test_emit_forwards_draft_to_bound_sink() -> None:
    sink = RecordingSink()
    with bind_event_sink(sink):
        emit(
            "evidence.ingested",
            stage="analyze",
            level="warn",
            message="ingested",
            payload={"total": 3},
        )

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.type == "evidence.ingested"
    assert event.stage == "analyze"
    assert event.level == "warn"
    assert event.message == "ingested"
    assert event.payload == {"total": 3}


def test_bind_restores_previous_sink() -> None:
    outer = RecordingSink()
    inner = RecordingSink()

    with bind_event_sink(outer):
        emit("outer.before")
        with bind_event_sink(inner):
            emit("inner")
        emit("outer.after")

    assert [e.type for e in inner.events] == ["inner"]
    assert [e.type for e in outer.events] == ["outer.before", "outer.after"]


def test_sink_errors_do_not_escape() -> None:
    with bind_event_sink(ExplodingSink()):
        emit("run.started")  # must not raise


def test_null_sink_accepts_events() -> None:
    sink = NullEventSink()
    with bind_event_sink(sink):
        emit("run.started")


def test_context_is_not_propagated_to_new_thread() -> None:
    sink = RecordingSink()
    seen: list[int] = []

    def worker() -> None:
        emit("worker.event")
        seen.append(len(sink.events))

    with bind_event_sink(sink):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

    assert seen == [0]
    assert sink.events == []


def test_event_payload_defaults_are_not_shared() -> None:
    first = EventDraft(type="a")
    second = EventDraft(type="b")
    first.payload["key"] = "value"
    assert second.payload == {}
