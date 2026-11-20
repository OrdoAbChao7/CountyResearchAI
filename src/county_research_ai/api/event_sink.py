"""Adapter that persists research-engine events into the existing JobStore."""
from __future__ import annotations

from ..observability import EventDraft
from .jobs import JobStore


class JobEventSink:
    """Write observation events to ``job_events`` without a second store.

    The sink deliberately keeps the event payload flat and JSON-safe so the
    existing SSE endpoint and the event reducer can consume it unchanged.
    """

    def __init__(self, store: JobStore, job_id: str) -> None:
        self.store = store
        self.job_id = job_id

    def emit(self, draft: EventDraft) -> None:
        payload = dict(draft.payload)
        payload.setdefault("level", draft.level)
        if draft.stage:
            payload.setdefault("stage", draft.stage)
        if draft.message:
            payload.setdefault("message", draft.message)
        self.store.append_event(self.job_id, draft.type, payload)


__all__ = ["JobEventSink"]
