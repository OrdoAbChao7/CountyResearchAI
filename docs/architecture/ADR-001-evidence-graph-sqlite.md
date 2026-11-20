# ADR-001 — SQLite append-only evidence graph

Status: accepted (2026-10-26)

## Context

The in-memory `EvidenceLedger` proved the contracts, but findings could not be
reopened after a process restart and there was no durable relation between a
finding and its source quote. The product requires finding → claim → span →
immutable snapshot navigation and run-to-run auditability.

## Decision

Persist the graph in SQLite with explicit tables: `source_snapshots`,
`evidence_spans`, `claims`, `claim_evidence_edges`, `claim_relations`,
`verification_records`, `findings`, `run_snapshots`.

Source snapshots and spans are append-only: re-inserting the same id with a
different hash/quote raises `ValueError` instead of overwriting. Claims may be
updated because verification status changes; identity-bearing fields are stable.

No ORM, no Postgres. SQLite is in the standard library, works offline on Windows,
and is sufficient for single-node research.

## Consequences

- Reload-equality is tested; the loaded `EvidenceLedger` matches the saved one.
- Historical artifacts are never rewritten; the graph is a new store.
- A later Postgres migration is a mechanical column-for-column translation.
- Large corpora will eventually need pagination; current API list endpoints are
  bounded (`limit <= 200`).
