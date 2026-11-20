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
