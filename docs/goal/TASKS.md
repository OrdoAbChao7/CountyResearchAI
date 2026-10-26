# Quality Recovery & Independent Evaluation — Tasks

Goal: diagnose why Strategy C trails A/B, reduce verifier withholding without
loosening truth, build an independent evaluation set, implement Strategy D, run
paired A/B/C/D experiments and ablations, and close engineering reliability.

Branch: `codex/quality-recovery` (checkpoint `checkpoint-m4-pass-20261026`).
No paid Provider or semantic Judge calls without a cost gate.

## Milestones and acceptance

| ID | Milestone | Acceptance | Status |
| --- | --- | --- | --- |
| Q0 | Baseline audit | clean checkpoint; pytest/ruff/typecheck/Vitest/build reproduced; versions and HEAD recorded; M0–M4 untouched | PASS |
| Q1 | Failure attribution | per-task funnel: required facts → retrieved → extracted → verified → answered; stage metrics; 872-claim review sample with reasons; ranked defect list | PASS |
| Q2 | Dataset | real tasks with source URL/snapshot, quote, period, unit, hash; dev and frozen blind split; leaks controlled; honest count and gap | PARTIAL — 2 blind tasks / 10 facts validated; 40–60 gap documented |
| Q3 | Strategy D | deterministic improvements chosen by dev evidence: conflict grouping, temporal/region/unit matching, gap research; explainable and bounded | PASS — measure identity, period inference, verified answer; dev evidence |
| Q4 | A/B/C/D + ablations | paired frozen runs; No Graph, No Verifier, No Gap, BM25-only, BM25+Adaptive, old vs improved conflict grouping; costs and uncertainty; negative results reported | PARTIAL — dev A/B/C/D + 3 ablations + 2-task blind pilot; live/large blind NOT_RUN |
| Q5 | Reliability | SQLite lease/heartbeat/fencing or documented single-process guard; Playwright E2E or NOT_RUN; fault injection/concurrency tests; logs/traces | PASS (local scope) — leases/fencing, per-job storage, 2 browser E2E, stress tests; two-process live NOT_RUN |
| Q6 | Final verification | all local tests pass; M0–M4 no regression; statistical/engineering significance stated honestly; STATE/QUALITY_REPORT/results updated | PASS engineering / PARTIAL research — 692 Python, 4 frontend, 2 E2E; blind/live gaps documented |

## Q0 acceptance detail

- `pytest --no-cov -q`, `ruff check src tests scripts`, `npm run typecheck`,
  `npm test`, `npm run build` actually executed on the recovery branch.
- Baseline artifacts under `experiments/quality/20261026_baseline/`.
- Existing M0–M4 behavior untouched; `.claude/` not modified or committed.

## Q1 diagnosis units

For every archived C task with raw inputs and a frozen report:

1. Required facts from the frozen ground truth.
2. Retrieval: fact value/metric present in RawDocs? rank/coverage.
3. Extraction: fact present as an `AtomicClaim` with region/period/unit?
4. Verification: deterministic status and reason; compare to legacy status.
5. Answer: fact value present in the final report/claim observations?
6. Cost: LLM units, searches, seconds.

Funnel gaps are assigned to: `not_retrieved`, `not_extracted`,
`wrongly_rejected`, or `not_in_answer`. `wrongly_rejected` is only asserted when
the expected fact and quote match independently; otherwise it is labelled
`withheld_unlabelled` and remains a review item.
