# AxiomScope v2 — Decisions

Short, reversible-by-record decisions made autonomously. Supersede by adding a
new entry rather than editing history.

## D-001 — Continue on `codex/evidence-first-v2`, do not reset

The prior phases left 45 modified and ~20 untracked files uncommitted. Discarding
or resetting would destroy verified work. Continue on the same feature branch and
commit the audited state in scoped commits. The legacy baseline tag/SHA remains
untouched. (2026-10-26)

## D-002 — Treat the relocated-manifest failure as a product defect

`audit_continuation_experiment.py` trusted absolute paths embedded in immutable
artifacts. Resolution now falls back to the current checkout and reports which
path was used (`path_source`). The manifest itself is never rewritten, so the
historical record stays honest. (2026-10-26)

## D-003 — SQLite for the evidence graph, no Postgres/Oracle layer

M2 requires persistence and reload-equality. SQLite is in the standard library,
works offline on Windows, and is sufficient for single-node research workloads.
The schema is written with explicit columns so a later Postgres migration is
mechanical. No ORM added. (2026-10-26)

## D-004 — No new paid Provider/Judge calls this session

The frozen corpus already supports offline replay. Quality claims will stay
limited to offline/fixture/replay evidence until a cost gate is explicitly
granted. (2026-10-26)

## D-005 — Preserve legacy entry points

Public CLI (`county-research`), `ResearchApplication`, and all three modes remain
functional. New APIs are additive; compatibility adapters (`model_validator`
aliases, property shims) are kept and covered by tests. (2026-10-26)

## D-006 — Deterministic verification is not semantic entailment

The bound verifier may mark a claim `supported` only from exact Claim → Chunk →
Source mapping with region/metric/value/unit/period/caliber/version checks. Model
judgement, if ever enabled, is recorded as an assessment, never as proof.
(2026-10-26)

## D-007 — Enforce the requested date window in verification

A live smoke marked a 2027 planning target `SUPPORTED` inside a 2024 contract.
Claims outside `date_window`, or numeric claims without a period, are now
`NOT_COMPARABLE` with an explicit reason. This is a contract-level rule, applied
through `save_ledger(window=...)` and `verify_claim(window=...)`. (2026-10-26)

## D-008 — In-process worker, explicit resume, no auto-restart

Avoid a broker for the local MVP. Jobs are durable in SQLite; abandoned
`RUNNING` jobs become `INTERRUPTED` on startup and require `POST /resume`. This
avoids surprise provider spend and duplicate side effects. (2026-10-26)

## D-009 — Do not infer strategy D or live results

The offline harness reports A/B/C only. D, live evaluation, ablations, and a
semantic Judge are `NOT_RUN` / `BLOCKED_EXTERNAL`. No number is extrapolated to
fill the gap. (2026-10-26)

## D-010 — Default API mode is MOCK even when keys exist

`AXIOMSCOPE_API_LIVE` must be explicitly true, plus both provider keys present,
before a job can reach a paid provider. This prevents accidental spend from a
local demo. (2026-10-26)

## D-011 — One span must support a claim

Support cannot be assembled from separate spans (metric in one, value in
another). The verifier requires a single quote plus source metadata to contain
region, period, value/unit, and statement or metric. This is stricter and
reduces recall, deliberately. (2026-10-26)

## D-012 — Verification and relations are run-scoped

Claims are content-derived and repeat across jobs. `verification_records` and
`claim_relations` carry `run_id`; findings read the chain for their own run, and
a resumed job clears prior findings/relations/verification for its run before
re-verifying. (2026-10-26)

## D-013 — Only the deadline is a cumulative enforced cap

`max_tokens` and `max_documents` bound a single call/collection, not the total
run. The API reports them as `bounded_per_call`; `capabilities` no longer lists
them as enforced. Claiming cumulative enforcement without token accounting would
be false. (2026-10-26)
