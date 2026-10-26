# AxiomScope v2 — Acceptance Ledger

Status values: `PASS`, `FAIL`, `BLOCKED_EXTERNAL`, `NOT_RUN`, `PARTIAL`.
Every PASS needs a command, exit code, observed count, artifact path, revision.

## Baseline and tests

| Check | Status | Command / artifact | Observed |
| --- | --- | --- | --- |
| Python suite | PASS | `python -m pytest --no-cov -q` | `662 passed in 8.31s`, exit 0 |
| Relocated manifest audit | PASS | `tests/test_audit_path_resolution.py` | 4 passed |
| Frontend typecheck | PASS | `cd web; npm run typecheck` | exit 0 |
| Frontend tests | PASS | `cd web; npm test` | 4 passed |
| Frontend build | PASS | `cd web; npm run build` | 40 modules, 160.8 kB JS |
| API live smoke | PASS | `python -m county_research_ai.api` :8011 | health, capabilities, UI, SSE 200 |
| End-to-end MOCK task | PASS | live POST + poll | `SUCCEEDED`/`SUFFICIENT`, 3 sources, 6 findings, 4,213 B brief |
| Deadline exhaustion | PASS | `test_deadline_exhaustion_is_not_reported_as_sufficient` | `BUDGET_EXHAUSTED` |
| Cancellation | PASS | `test_cancel_requested_before_execution_stops_job` | `CANCELLED` |
| Resume | PASS | `test_resume_requeues_and_resubmits` | QUEUED + resubmitted |
| Date-window false support | PASS | graph + API evidence tests | 2027 claim `NOT_COMPARABLE` in 2024 window |
| Browser screenshot / E2E | NOT_RUN | — | no browser automation installed |

## Milestone gates

| Milestone | Status | Why |
| --- | --- | --- |
| M0 audit/freeze | PASS | code-backed audit + reproduced suite + artifact taxonomy |
| M1 retrieval/snapshot/eval foundation | PARTIAL | snapshots/BM25/contract/negative controls done; live Recall@K/replay not run |
| M2 temporal evidence graph | PASS | persistence, navigation, conflict/temporal/false-reference/reload tests |
| M3 durable orchestration | PASS (workflow path) | resume/cancel/deadline tested; agent-path checkpoints opt-in |
| M4 API + web workspace | PASS (screenshot NOT_RUN) | endpoints, SSE, UI, brief, build and live smoke verified |
| M5 multi-baseline evaluation + release | FAIL / PARTIAL | offline A/B/C report and docs exist; D, 40–60 tasks, ablations, live, Judge missing |

## Evaluation evidence

| Item | Status | Artifact |
| --- | --- | --- |
| Pre-registered design | PASS | `docs/evaluation/DESIGN.md` |
| Offline A/B/C aggregation | PASS | `experiments/evaluation/20261026_multi_baseline_offline/summary.json` |
| Verifier ablation (C raw archives) | PASS | `experiments/evaluation/20261026_verifier_ablation/summary.json` |
| Observational hash | PASS | `4341ea07abbaa5495565052e7d8fd3a5a35eb03063f45b09680a0481142d5c1e` |
| Strategy D measurement | NOT_RUN | — |
| Independent 40–60 task set | NOT_RUN | inherited frozen corpus only |
| Live end-to-end | BLOCKED_EXTERNAL | no cost gate |
| Ablations | NOT_RUN | — |
| Semantic Judge | NOT_RUN | — |
| Human rubric/adjudication | NOT_RUN | — |

## Never claimed

- That Evidence-First v2 outperforms the baselines. The measured offline C group
  trails A/B on this small sample.
- Semantic entailment, statistical significance, or token savings.
- Screenshots, live-provider runs, or ablations that were not executed.
