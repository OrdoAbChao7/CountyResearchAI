# ADR-004 — Execution leases, fencing, and per-job storage

Status: accepted (2026-10-26)

## Context

The SQLite job store originally had an atomic QUEUED→RUNNING transition but no
lease. Two API processes sharing a data directory could mark each other's live
jobs `INTERRUPTED` on startup, and a slow worker could overwrite a newer
attempt's terminal state. API jobs also shared raw/report paths by county/date,
so concurrent jobs could overwrite each other's archives.

## Decision

- Each execution acquires a lease (`lease_owner`, `lease_expires_at`) and gets a
  monotonic `fencing_token` from an atomic `claim_for_execution`.
- A daemon heartbeat thread renews the lease every `lease/3` seconds. If renewal
  fails, the worker stops and its result is ignored.
- Terminal writes go through `finish_job`, which updates the job and inserts the
  terminal event in one transaction and requires the matching owner/token.
- Startup recovery only marks `RUNNING` jobs with an empty or expired lease as
  `INTERRUPTED`; live leases are preserved.
- `QUEUED` jobs are re-submitted on startup; `resume` re-queues non-running,
  non-succeeded jobs.
- Each API job gets isolated storage under
  `<data>/api_jobs/<job_id>/` and `<reports>/api_jobs/<job_id>/`, so concurrent
  jobs cannot overwrite raw data or reports.
- A MOCK-only, env-gated delay (`AXIOMSCOPE_MOCK_STAGE_DELAY_SECONDS`, max 10 s)
  makes browser cancellation deterministic; it is never used in LIVE mode.

## Consequences

- Stale workers cannot commit `SUCCEEDED`/`FAILED` after losing the lease.
- Multiple local API processes can share one job DB without startup stealing
  live work, though SQLite remains single-writer and is not a distributed queue.
- Heartbeat renewal is between stages and in the delay loop; a single provider
  call longer than the lease is not interrupted mid-call.
- Tests cover live-lease recovery blocking, expired-lease takeover, stale
  terminal rejection, concurrent claim winners, and per-job report isolation.
- A real two-process stress test was not run; the store-level invariants are
  tested, not a production multi-node deployment.
