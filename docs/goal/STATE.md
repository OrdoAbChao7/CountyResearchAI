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
| Python tests | `675 passed` (`pytest --no-cov -q`) |
| Frontend | `tsc --noEmit` clean, 4 Vitest tests, Vite build 160.8 kB JS |
| Live smoke | `MOCK` run: `SUCCEEDED`/`SUFFICIENT`, 3 sources, 6 findings, 4,213-byte brief |

Note: the venv editable install pointed at the pre-rename path
`E:\Projects\CountyResearchAI\src`. It was reinstalled with
`pip install -e . --no-deps` so `python -m county_research_ai.api` works.

## Milestone gate map

| Milestone | Gate | Status | Evidence | Remaining work |
| --- | --- | --- | --- | --- |
| M0 legacy audit + freeze | actual code audited, baseline reproduced, mock/fixture classified | **PASS** | `ARCHITECTURE_BASELINE_AUDIT.md`, `docs/goal/*`, suite green | keep audit current |
| M1 retrieval / snapshots / eval foundation | snapshots + hashes/offsets, replay, query-aware lexical baseline, negative controls | **PARTIAL** | `evidence/source_contract.py`, `search/lexical.py`, contracts, phase replays | live replay / Recall@K on a real query not run; full snapshot replay runner limited |
| M2 temporal evidence graph | persistent typed graph, finding→claim→span→snapshot, conflict/temporal semantics | **PASS** | `evidence/graph.py`, 19 graph tests incl false reference, window, reload equality | semantic entailment explicitly out of scope |
| M3 durable orchestration | bounded loop, restart/resume, cancellation, disjoint finish states | **PASS (workflow path)** | `api/jobs.py`, `api/worker.py`, resume/cancel/deadline tests | agent-path checkpoints remain opt-in; no distributed queue |
| M4 API + web workspace | FastAPI `/api/v1`, SSE, cancel/resume, evidence explorer, brief export, React app | **PASS (screenshot NOT_RUN)** | `src/.../api/`, `web/`, 10 API app tests, live smoke | browser E2E/screenshots not automated |
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
| Q1 failure attribution | PASS | 90 GT facts: 21 retrieved, 15 extracted, 2 supported, 4 reported, 0 end-to-end; `experiments/quality/20261026_q1_funnel/`; 872 withheld review |
| Q2 dataset | IN_PROGRESS | next |
| Q3 Strategy D | NOT_STARTED | evidence-driven order: conflict identity → answer integration → retrieval |
| Q4 A/B/C/D + ablations | NOT_STARTED | offline first |
| Q5 reliability | NOT_STARTED | lease/fencing or documented guard; Playwright or NOT_RUN |
| Q6 final verification | NOT_STARTED | no paid calls; live remains BLOCKED_EXTERNAL |

Largest measured bottleneck: retrieval coverage (69/90 facts absent from C's
archived docs; long-history 0/30). Largest verifier-side issue: coarse,
decontextualized claim identity (872/1,275 withheld; 351 different-measure-only
conflicts). Verified findings are not used in the final answer (2 supported,
0 reported).
