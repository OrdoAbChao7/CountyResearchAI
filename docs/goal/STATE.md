# AxiomScope v2 — Goal State

Updated: 2026-10-26
Branch: `codex/evidence-first-v2`
Repository: `E:\Projects\AxiomScope` (formerly `E:\Projects\CountyResearchAI`)

## Verified baseline

| Item | Value |
| --- | --- |
| HEAD at session start | `548016aa1224385e7bd5f6e7f81e39b79a61c59a` |
| Legacy baseline | `52a6ed0f5164721cece221ffb9e7f67f73ac3dd7` on `codex/experiment-superiority` (frozen) |
| Python | 3.13.7 (`.venv`), FastAPI 0.162.0, uvicorn 0.54.0 |
| Node | 24.19.0, npm 11.17.0 |
| Python tests | `702 passed` (`pytest --no-cov -q`) |
| Frontend | `tsc --noEmit` clean, 4 Vitest tests, Vite build 160.8 kB JS |
| Live smoke | `MOCK` run: `SUCCEEDED`/`SUFFICIENT`, 3 sources, 6 findings, 4,213-byte brief |

Note: the venv editable install pointed at the pre-rename path
`E:\Projects\CountyResearchAI\src`. It was reinstalled with
`pip install -e . --no-deps` so `python -m county_research_ai.api` works.

The table above is the historical M4-era baseline. Current Finish Roadmap
numbers (780 Python tests, 18 Vitest, 2 Playwright) are recorded in the
"Finish Roadmap goal" section at the end of this file and in
`docs/goal/ACCEPTANCE.md`.

## Milestone gate map

| Milestone | Gate | Status | Evidence | Remaining work |
| --- | --- | --- | --- | --- |
| M0 legacy audit + freeze | actual code audited, baseline reproduced, mock/fixture classified | **PASS** | `ARCHITECTURE_BASELINE_AUDIT.md`, `docs/goal/*`, suite green | keep audit current |
| M1 retrieval / snapshots / eval foundation | snapshots + hashes/offsets, replay, query-aware lexical baseline, negative controls | **PARTIAL** | `evidence/source_contract.py`, `search/lexical.py`, contracts, phase replays | live replay / Recall@K on a real query not run; full snapshot replay runner limited |
| M2 temporal evidence graph | persistent typed graph, finding→claim→span→snapshot, conflict/temporal semantics | **PASS** | `evidence/graph.py`, 19 graph tests incl false reference, window, reload equality | semantic entailment explicitly out of scope |
| M3 durable orchestration | bounded loop, restart/resume, cancellation, disjoint finish states | **PASS (workflow path)** | `api/jobs.py`, `api/worker.py`, resume/cancel/deadline tests | agent-path checkpoints remain opt-in; no distributed queue |
| M4 API + web workspace | FastAPI `/api/v1`, SSE, cancel/resume, evidence explorer, brief export, React app | **PASS** | `src/.../api/`, `web/`, 10 API app tests, live smoke, Wizard Playwright E2E + screenshots | section streaming / token accounting deliberately absent |
| M5 multi-baseline evaluation + release docs | A/B/C/D paired eval, locked task set, ablations, final report, brand docs | **FAIL / PARTIAL** | design + offline A/B/C report + verifier ablation + README/ADR/demo/career docs | D not measured; 40–60 independent tasks, remaining ablations, live, semantic Judge, human adjudication missing |

## Constraints in force

- No new paid Provider or Judge calls without an explicit fresh cost gate.
- Historical experiment artifacts are immutable; new artifacts go to new directories.
- No destructive git operations, no force push, no external deployment.
- Mock / fixture / replay / live evidence must stay explicitly labeled.
- Public CLI and legacy modes must remain available.

## Next executable action

1. Curate and lock a 40–60 task independent set with expected evidence quotes and
   hashes (`docs/evaluation/DESIGN.md`).
2. Run strategy D on the same frozen inputs, then paired A/B/C/D offline.
3. Execute the pre-registered ablations on a dev split.
4. Request an explicit cost gate for a budgeted live run and semantic Judge.
5. Install browser automation and capture the demo screenshots/E2E.

## Stop condition (2026-10-26)

Stopped with M0–M4 verified and M5 partial because the remaining work requires
external prerequisites, not more code:

- strategy D quality, live end-to-end evaluation, and a semantic Judge require a
  fresh explicit paid-provider cost gate (currently forbidden);
- a 40–60 task independent holdout requires curating/locking new real tasks and
  expected evidence, which is not authorized by the current corpus;
- human rubric adjudication and browser automation are not installed/authorized.

Safe offline work completed instead: A/B/C aggregation and the deterministic
verifier ablation. `.claude/` is intentionally left untracked (local harness
configuration).

## Quality Recovery goal (2026-10-26)

Branch: `codex/quality-recovery`; checkpoint tag `checkpoint-m4-pass-20261026`.
Plan and acceptance: `docs/goal/TASKS.md`; results: `docs/goal/QUALITY_REPORT.md`.

| Stage | Status | Evidence |
| --- | --- | --- |
| Q0 baseline | PASS | 675 Python tests; scoped ruff clean; frontend checks; `experiments/quality/20261026_baseline/` |
| Q1 failure attribution | PASS | 90 GT facts: 21 retrieved, 15 extracted, 2 supported, 4 reported, 0 end-to-end; `experiments/quality/20261026_q1_funnel_baseline/`; 872 withheld review |
| Q2 dataset | PARTIAL | 2 blind tasks / 10 exact-quote facts validated; disjoint from dev; 40–60 gap documented in `docs/goal/DATASET.md` |
| Q3 Strategy D | PASS (dev) | measure identity + period inference + verified extractive answer; withheld 872→203; supported 2→15; dev E2E 3→15 of 90 |
| Q4 A/B/C/D + ablations | PARTIAL | dev A/B/C/D + no-verifier + BM25/adaptive + old/new grouping; blind pilot 2 tasks / 10 facts (D 4/10, A/B 0/4, C NOT_RUN); live NOT_RUN |
| Q5 reliability | PASS (local scope) | leases/fencing/heartbeat, atomic terminal event, per-job storage; Playwright 2/2 pass with traces/screenshots; two-process live stress NOT_RUN |
| Q6 final verification | PASS engineering / PARTIAL research | 702 Python tests, 4 frontend, 2 Playwright, CLI dry-run; `docs/goal/Q6_FINAL_ACCEPTANCE.md` |

Largest measured bottleneck: retrieval coverage (69/90 facts absent from C's
archived docs; long-history 0/30). The verifier-side coarse-identity issue was
reduced from 872 to 203 withheld claims by measure identity + period inference;
the remaining 203 are not labelled false rejections. Dev Strategy D E2E is
15/90 vs C 3/90; the blind pilot is only 2 tasks/10 facts (D 4/10) and does not
support a generalization claim.

Remaining before research acceptance: 38–58 additional blind tasks, live
end-to-end + semantic Judge (cost gate), gap/temporal retrieval, two-process
lease stress, and a labelled false-support audit.

## Quality Recovery stop condition (2026-10-26)

Local engineering work is complete and verified: Q0–Q6 engineering gates pass,
702 Python tests + 4 frontend + 2 Playwright pass, and M0–M4 behavior is
retained. Research acceptance remains **PARTIAL** because:

- 38–58 additional independent blind tasks are required; only 2 disjoint
  exact-quote tasks could be built without new retrieval/annotation.
- Live end-to-end evaluation and a semantic Judge are `BLOCKED_EXTERNAL` until a
  paid-provider cost gate is explicitly authorized (`docs/goal/COST_GATE.md`).
- Gap-driven/temporal retrieval is not implemented; 69/90 dev GT facts remain
  outside the archived documents.
- Two-process live lease stress and a labelled false-support audit are NOT_RUN.

Do not resume by loosening the verifier or reusing the blind pilot for tuning.
The next safe actions are dataset curation from new authorized sources, gap/temporal
retrieval implementation on a dev split, then one locked blind run.

## Q7 Retrieval Recovery goal (2026-10-26)

| Sub-phase | Status | Evidence |
| --- | --- | --- |
| Q7.1 retrieval recovery | PARTIAL | 32/69 missing facts recovered at retrieval level (26 pooled archive + 6 free web); D pooled E2E 33/90; long-history retrieval 6/30 but E2E 0/30; oracle 17/30 sources available |
| Q7.2 verifier audit | PARTIAL | 25 assistant labels; false support 30% (3/10), false rejection 26.7% (4/15); human labels BLOCKED |
| Q7.3 independent holdout | NOT_MET | 2 PILOT tasks, 0 SEALED; 38–58 task gap documented |
| Q7.4 evaluation | PARTIAL | task-clustered bootstrap (18 tasks): D pooled − C +0.333 [0.156,0.522]; no sealed A/B/C/D |
| Q7.5 reliability | PASS | two-worker stress: one success/job, stale rejected, takeover + crash recovery; 702 tests, E2E 2/2 |
| Q7.6 final acceptance | PARTIAL | `docs/goal/Q7_REPORT.md`; research generalization not established |

Q7 full report: `docs/goal/Q7_REPORT.md`. Stop reason: no sealed 40–60 task set,
no human annotation, no paid live/Judge cost gate. Do not reclassify PILOT as
SEALED or loosen the verifier.

## Finish Roadmap goal (2026-11-20)

Branch: `codex/finish-roadmap`; worktree outside the main checkout
(`E:\Projects\CountyResearchAI-finish-roadmap`); base mainline
`codex/quality-recovery` @ `144f4c8`. The main checkout was not modified or
committed to.

| Task | Status | Evidence |
| --- | --- | --- |
| T2 deep-research capture | PASS | `application/context.py`, `modes/{snapshot,rise_fall,long_history}.py`, `api/worker.py:359`; projection persisted in `jobs.result_json`; mode + worker tests |
| T3 fine-grained events | PASS | `observability/events.py`, `api/event_sink.py`, `research_agent/coordinator.py`; per-job `seq`, SSE replay, event-order test; 35-event MOCK run |
| T7 graph/report projections | PASS | `api/projections/{graph,report,questions,evidence}.py`, `/graph` + `/report.json`; stable IDs, URL dedupe, multiedges, 400/800 connected truncation, citation numbering, conflict/gap tests |
| T10 report/evidence workbench | PASS | `web/src/components/*`; StepRail, ReportStudio, EvidenceDrawer, AgentTimeline, ContextPanel; screenshots + Vitest |
| T12 Cytoscape graph | PASS | lazy `GraphCanvas` chunk, cose layout, filters, focus, list fallback, conflict/gap styles; 500-claim projection test |
| T13 engineering hardening | PASS | 780 Python tests, scoped ruff clean, 18 Vitest, 2 Playwright E2E; event idempotency/recovery/concurrency, XSS and malicious-source regressions |

Skipped by instruction after verifying equivalents: T0 (executed as read-only
audit, no code), T4/T5/T6/T8/T9/T11. No second RunManager, queue, JSONL store,
`/api/v1/runs` API, `frontend/` rewrite or React 19 upgrade was introduced.

Remaining and not claimed as PASS:

- M5's 40–60 independent sealed tasks, live end-to-end evaluation, semantic
  Judge and human adjudication are still unfinished (`BLOCKED_EXTERNAL` for paid
  live/Judge).
- The 400-node test is a synthetic projection test, not a browser performance
  benchmark of a real investigation.
- Report sections are rendered once and revealed sequentially; section-level
  streaming remains future work.
- Real supply-chain relations are not modelled; the graph shows only persisted
  evidence/topic/source/conflict/gap relations.
