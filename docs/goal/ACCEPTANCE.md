# AxiomScope v2 — Acceptance Ledger

Status values: `PASS`, `FAIL`, `BLOCKED_EXTERNAL`, `NOT_RUN`, `PARTIAL`.
Every PASS needs a command, exit code, observed count, artifact path, revision.

## Baseline and tests

| Check | Status | Command / artifact | Observed |
| --- | --- | --- | --- |
| Python suite | PASS | `python -m pytest --no-cov -q` | `702 passed in 10.99s`, exit 0 |
| Relocated manifest audit | PASS | `tests/test_audit_path_resolution.py` | 4 passed |
| Frontend typecheck | PASS | `cd web; npm run typecheck` | exit 0 |
| Frontend tests | PASS | `cd web; npm test` | 4 passed |
| Frontend build | PASS | `cd web; npm run build` | 40 modules, 160.8 kB JS |
| API live smoke | PASS | `python -m county_research_ai.api` :8013 | health, capabilities, built UI, SSE 200; honest budget labels |
| End-to-end MOCK task | PASS | live POST + poll | `SUCCEEDED`/`SUFFICIENT`, 3 sources, 6 findings (1 supported, 5 window-excluded) |
| Deadline exhaustion | PASS | `test_deadline_exhaustion_is_not_reported_as_sufficient` | `BUDGET_EXHAUSTED` |
| Cancellation | PASS | `test_cancel_requested_before_execution_stops_job` | `CANCELLED` |
| Resume | PASS | `test_resume_requeues_and_resubmits` | QUEUED + resubmitted |
| Date-window false support | PASS | graph + API evidence tests | 2027 claim `NOT_COMPARABLE` in 2024 window |
| Browser E2E | PASS | `cd web; npm run test:e2e` | 2 passed (create/SSE/evidence/brief; cancel/resume); traces + screenshots |
| API storage isolation | PASS | `test_jobs_do_not_overwrite_each_others_reports` | distinct report paths |
| Lease/fencing | PASS | `test_live_lease_blocks_recovery_and_takeover`, `test_expired_lease_takeover_rejects_stale_terminal_write`, `test_concurrent_claims_have_exactly_one_winner` | 3 passed |
| Legacy CLI | PASS | `python -m county_research_ai.cli --county 安吉县 --dry-run` | exit 0 |

## Milestone gates

| Milestone | Status | Why |
| --- | --- | --- |
| M0 audit/freeze | PASS | code-backed audit + reproduced suite + artifact taxonomy |
| M1 retrieval/snapshot/eval foundation | PARTIAL | snapshots/BM25/contract/negative controls done; live Recall@K/replay not run |
| M2 temporal evidence graph | PASS | persistence, navigation, conflict/temporal/false-reference/reload tests |
| M3 durable orchestration | PASS (workflow path) | resume/cancel/deadline tested; agent-path checkpoints opt-in |
| M4 API + web workspace | PASS | endpoints, SSE, UI, brief, build, live smoke, Playwright E2E |
| M5 multi-baseline evaluation + release | FAIL / PARTIAL | D measured offline; 2-task blind pilot; 40–60 tasks, live, Judge, full ablations missing |

## Evaluation evidence

| Item | Status | Artifact |
| --- | --- | --- |
| Pre-registered design | PASS | `docs/evaluation/DESIGN.md` |
| Offline A/B/C aggregation | PASS | `experiments/evaluation/20261026_multi_baseline_offline/summary.json` |
| Verifier ablation (C raw archives) | PASS | `experiments/evaluation/20261026_verifier_ablation/summary.json` |
| Observational hash | PASS | `4341ea07abbaa5495565052e7d8fd3a5a35eb03063f45b09680a0481142d5c1e` |
| Strategy D measurement | PASS (dev + 2-task blind) | `experiments/quality/20261026_q3_strategy_d/`, `20261026_q4_blind_pilot/` |
| Independent task set | PARTIAL | 2 blind tasks / 10 facts; 40–60 gap documented |
| Live end-to-end | BLOCKED_EXTERNAL | no cost gate |
| Ablations | PARTIAL | no-verifier, BM25/adaptive, old/new grouping; no-gap NOT_RUN |
| Semantic Judge | NOT_RUN | — |
| Human rubric/adjudication | NOT_RUN | — |

## Quality Recovery gates

| Gate | Status | Evidence |
| --- | --- | --- |
| Q0 baseline | PASS | 675 tests at Q0; logs under `experiments/quality/20261026_baseline/` |
| Q1 failure attribution | PASS | baseline funnel: 21/90 retrieved, 2 supported, 0 E2E; 872 withheld review |
| Q2 dataset | PARTIAL | 2 blind tasks / 10 exact-quote facts validated; gap documented |
| Q3 Strategy D | PASS (dev) | measure identity, period inference, verified answer; dev E2E 3→15/90 |
| Q4 A/B/C/D + ablations | PARTIAL | dev + 2-task blind; live/large blind NOT_RUN |
| Q5 reliability | PASS (local) | leases/fencing, storage isolation, 2 Playwright tests; two-process stress NOT_RUN |
| Q6 final acceptance | PASS engineering / PARTIAL research | 692 tests, all local checks; see Q6 report |

## Never claimed

- That Evidence-First v2 outperforms the baselines. The measured offline C group
  trails A/B on this small sample.
- Semantic entailment, statistical significance, or token savings.
- Live-provider runs, a comprehensive blind benchmark, or ablations that were not
  executed.

## Q7 Retrieval Recovery evidence

| Check | Status | Artifact / observed |
| --- | --- | --- |
| Pooled archive diagnosis | PASS | 47/90 retrieved; 26/69 missing facts recovered |
| Autonomous free-web recovery | PARTIAL | long-history 6/30 (4 exact, 2 value-metric); rise-fall 0/12 |
| Oracle source availability | PASS (diagnostic) | 17/30 long-history sources fetchable/present |
| Strategy D pooled E2E | PASS (dev) | 33/90 (36.7%); pooled+free 31/90 |
| Task-clustered bootstrap | PASS (dev) | D pooled − C +0.333, 95% [0.156, 0.522], 9/9/0 |
| Verifier audit | PARTIAL | 25 assistant labels; false support 30% (3/10), false rejection 26.7% (4/15) |
| Human verifier labels | BLOCKED_HUMAN_ANNOTATION | no human adjudication |
| Sealed 40–60 task holdout | NOT_MET | 2 PILOT tasks; 0 SEALED |
| Two-process lease stress | PASS | one success/job, stale rejected, takeover + crash recovery |
| Q7 tests / regressions | PASS | 702 Python, 4 frontend, 2 Playwright |
