# ADR-003 — In-process worker with explicit resume

Status: accepted (2026-10-26)

## Context

A working local demo needs background execution without adding a message broker.
Durability and honest state reporting matter more than throughput.

## Decision

- Job status and events live in SQLite.
- A bounded `ThreadPoolExecutor` executes jobs inside the API process.
- On startup, jobs left `RUNNING` become `INTERRUPTED` with
  `error_code=process_restarted`; they are not auto-resumed.
- `POST /resume` explicitly re-queues a non-running, non-succeeded job.
- Cancellation and deadline checks happen between stages. A single long provider
  call cannot be interrupted mid-flight; this limitation is documented.
- Finish outcomes are disjoint: `SUFFICIENT`, `BUDGET_EXHAUSTED`, `NO_PROGRESS`,
  `CONFLICT_UNRESOLVED`, `NEEDS_HUMAN_REVIEW`, `CANCELLED`, `FAILED`.

## Consequences

- Restart-safe history and an honest resume path without LangGraph or Celery.
- Concurrent jobs share one process; `max_workers` defaults to 1 to avoid
  unexpected provider spend and SQLite contention.
- A multi-user deployment must replace this with a durable queue; the job store
  and runner boundary is the seam for that change.
