"""Observation events must reach the existing JobStore and never break research."""
from __future__ import annotations

from county_research_ai.api.event_sink import JobEventSink
from county_research_ai.api.jobs import JobStore
from county_research_ai.domain.research_contracts import ResearchContract
from county_research_ai.observability import (
    EventDraft,
    bind_event_sink,
    emit,
    pop_event_sink,
    push_event_sink,
)


def test_emit_without_sink_is_a_noop() -> None:
    emit("deep.started", payload={"county": "安吉县"})


def test_bound_sink_receives_events() -> None:
    received: list[EventDraft] = []

    class Sink:
        def emit(self, draft: EventDraft) -> None:
            received.append(draft)

    with bind_event_sink(Sink()):
        emit("question_tree.created", stage="analyze", payload={"questions": 3})

    assert [draft.type for draft in received] == ["question_tree.created"]
    assert received[0].stage == "analyze"
    assert received[0].payload == {"questions": 3}


def test_a_failing_sink_does_not_interrupt_research() -> None:
    class BrokenSink:
        def emit(self, draft: EventDraft) -> None:
            raise RuntimeError("sink down")

    with bind_event_sink(BrokenSink()):
        emit("evidence.ingested")


def test_push_and_pop_restore_the_previous_binding() -> None:
    received: list[str] = []

    class Sink:
        def __init__(self, name: str) -> None:
            self.name = name

        def emit(self, draft: EventDraft) -> None:
            received.append(f"{self.name}:{draft.type}")

    outer = push_event_sink(Sink("outer"))
    inner = push_event_sink(Sink("inner"))
    emit("a")
    pop_event_sink(inner)
    emit("b")
    pop_event_sink(outer)

    assert received == ["inner:a", "outer:b"]


def test_job_event_sink_persists_into_job_events(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite")
    job = store.create_job(
        ResearchContract(objective="事件测试", regions=["安吉县"]),
        mode_label="MOCK",
    )
    sink = JobEventSink(store, job.job_id)

    sink.emit(
        EventDraft(
            type="conflicts.detected",
            stage="analyze",
            payload={"conflicts": []},
        )
    )

    event = store.list_events(job.job_id)[-1]
    assert event.event_type == "conflicts.detected"
    assert event.payload == {
        "conflicts": [],
        "level": "info",
        "stage": "analyze",
    }
    assert event.seq > 1
