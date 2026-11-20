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
| Live end-to-end | PARTIAL | four bounded smokes: `docs/goal/LIVE_SMOKE.md`; fourth failed in adaptive follow-up; no Live evaluation |
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

## Finish Roadmap acceptance (2026-11-20)

Revision: `codex/finish-roadmap`, based on `144f4c8`; commands run with the
mainline `.venv` and `PYTHONPATH=src`.

| Check | Status | Command / artifact | Observed |
| --- | --- | --- | --- |
| Python suite | PASS | `PYTHONPATH=src python -m pytest --no-cov -q` | `780 passed in 24.91s`, exit 0 |
| Ruff (changed scope) | PASS | `python -m ruff check src tests scripts/run_finish_roadmap_demo.py` | all checks passed |
| Frontend typecheck | PASS | `cd web; npm run typecheck` | exit 0 |
| Frontend unit tests | PASS | `cd web; npm test -- --run` | 18 passed (3 files) |
| Frontend build | PASS | `cd web; npm run build` | main 202.3 kB, lazy GraphCanvas 455.5 kB |
| Playwright E2E | PASS | `AXIOMSCOPE_E2E_PORT=8020 npx playwright test --reporter=list` | 2 passed; full wizard + cancel/resume |
| Anji MOCK demo | PASS | `PYTHONPATH=src python scripts/run_finish_roadmap_demo.py` | `SUCCEEDED/SUFFICIENT`, 35 events, 25 nodes/33 edges, 1 SUPPORTED / 5 NOT_COMPARABLE, 2 conflicts, 3 gaps |
| Deep-research capture (T2) | PASS | `tests/test_api_app.py::test_deep_mock_pipeline_emits_fine_grained_events`; mode tests | projection in `result.deep_research`, all modes |
| Event order/recovery/idempotency (T3/T13) | PASS | `tests/test_api_jobs.py` | repeated completion no-op, recovery continuity, 40 concurrent appends with unique contiguous seq |
| Graph projection (T7/T12) | PASS | `tests/test_graph_projection.py` (7 tests) | stable IDs, URL dedupe, multiedges, no self-loops, unmatched conflicts, 500 claims → ≤400 nodes/≤800 edges, connected |
| Report projection + citation (T7/T13) | PASS | `tests/test_report_projection.py`, `tests/test_projection_api.py` | 6 sections, citations, escaping, path traversal 403 |
| P0-1 conflicting numbers | PASS | `tests/test_evidence_store.py::test_repeated_imports_keep_conflicting_items_out_of_verified_state`, `tests/test_evidence_graph.py::test_two_supported_conflicting_claims_need_review` | conflicting items stay `conflicting`; both claims `NEEDS_REVIEW`, not `SUPPORTED` |
| P0-2 entity binding | PASS | `tests/test_evidence_store.py::test_enterprise_evidence_is_the_source_clause_not_a_synthesized_fact`, `::test_negated_or_uncertain_enterprise_mentions_are_not_extracted` | source clause retained; negated/uncertain names rejected |
| P0-3 report integrity | PASS | `tests/test_report_projection.py::test_report_escapes_malicious_source_text_without_dropping_facts` and verified-fact tests | only `SUPPORTED` rows; value/unit/period preserved; `<script>`/`javascript:` blocked |
| Wizard UI / error states | PASS | `web/src/workspace.test.ts`, `web/src/markdown.test.ts`, E2E screenshots | URL restore, event dedupe, loading/empty/error, keyboard Escape/focus return, list view |

Not accepted here:

| Item | Status | Why |
| --- | --- | --- |
| 40–60 sealed independent task set | NOT_MET | only pilot tasks exist; no new authorized corpus |
| Live end-to-end / semantic Judge | PARTIAL | four bounded Live smokes (`docs/goal/LIVE_SMOKE.md`); fourth failed before verification; semantic Judge and Live evaluation still not run |
| Human rubric/adjudication | BLOCKED_HUMAN_ANNOTATION | no human labels |
| Real 400-node browser benchmark | NOT_RUN | 400/800 cap tested on synthetic projection; browser E2E uses the small MOCK case |
| Section-level streaming / token accounting | NOT_RUN | renderer is one-shot; UI explicitly presents post-completion reveal |

Superseded on 2026-11-20: the 400/800 cap now has a browser test against a
synthetic projection; a real-investigation benchmark remains NOT_RUN. See the
Goal Mode section below.

## Goal Mode acceptance (2026-11-20, second pass)

Revision: `codex/finish-roadmap` @ `0adc236`; same `.venv` and `PYTHONPATH=src`.

| Check | Status | Command / artifact | Observed |
| --- | --- | --- | --- |
| Python suite | PASS | `PYTHONPATH=src python -m pytest --no-cov -q` | `780 passed in 24.63s` |
| P0 regressions | PASS | three P0 test modules | `47 passed in 2.96s` |
| Ruff | PASS | `ruff check src tests scripts/run_finish_roadmap_demo.py` | all checks passed |
| Frontend typecheck | PASS | `cd web; npm run typecheck` | exit 0 |
| Frontend unit tests | PASS | `cd web; npm test` | 4 files / `20 passed` |
| Frontend build | PASS | `cd web; npm run build` | main 208.21 kB, GraphCanvas 456.11 kB, CSS 35.98 kB |
| Playwright E2E | PASS | `AXIOMSCOPE_E2E_PORT=8040 npx playwright test` | `4 passed (28.2s)` |
| 400-node browser projection | PASS (synthetic) | Playwright large-graph test | 400 nodes / 800 edges: 505 ms first canvas, 204 ms list switch |
| Accessibility | PASS (automated) | `@axe-core/playwright`, WCAG A/AA | define / run / report / disputes / graph list / drawer: 0 violations |
| Report ↔ graph linkage | PASS | E2E `10-report-graph-link.png` | citation → drawer → graph-selected evidence |
| Conflict/gap panel | PASS | E2E `09-disputes.png` | 2 conflicts, 3 gaps from the real MOCK run |
| Dispute panel contrast | PASS | axe `color-contrast` | fixed orange token and selected-row secondary text |

Not accepted here:

| Item | Status | Why |
| --- | --- | --- |
| Real-investigation 400-node benchmark | NOT_RUN | browser test uses a synthetic 400/800 fixture |
| Live end-to-end / semantic Judge | PARTIAL | four authorized bounded smokes (`docs/goal/LIVE_SMOKE.md`); fourth failed before verification; no Live evaluation or Judge |
| 40–60 sealed tasks / human labels | NOT_MET | unchanged from M5 |
| Screen-reader manual walkthrough | NOT_RUN | axe automation only |

## Live smoke acceptance (2026-11-20)

Revision: `codex/finish-roadmap` + `scripts/run_live_smoke.py`. These were four
explicitly authorized paid smokes, not an evaluation.

| Check | Status | Command / artifact | Observed |
| --- | --- | --- | --- |
| Live provider call | PASS | `scripts/run_live_smoke.py --confirm-paid` | DeepSeek `deepseek-flash` + Tavily basic; first three: 2 LLM / 7 searches; fourth: 2 LLM / 11 searches |
| Live job execution (first) | PASS (engineering) | job `d367c9b277cf47d086d28f9824d661e5` | `SUCCEEDED` / `LIVE`; 28 events; 30.6 s |
| Live job execution (second) | PASS (engineering) | job `fdf7f3e86d444419967124236c4cc1ad` | `SUCCEEDED` / `LIVE`; 28 events; 28.9 s |
| Live job execution (third) | PASS (engineering) | job `007487e8e7494e3fba1770c1f7b0781f` | `SUCCEEDED` / `LIVE`; 28 events; 29.2 s |
| Live job execution (fourth) | FAILED (engineering) | job `4f4d6610f48248a599e6b112ce5b9ee0` | `FAILED` / `LIVE`; 14 events; 31.85 s |
| Live 2024 period coverage (fourth) | PASS (live observability) | `retrieval.period_coverage` | target `2024`; 22 selected; 1 in-window claim/source; period met; topic missing 4 slots |
| Live target-year follow-up queries (fourth) | PASS (live) | `retrieval.round.started` | 4 queries; real text recorded, including `2024年`; all routed to gov |
| Live adaptive follow-up failure (fourth) | FAILED | `job.failed` | all 4 gov queries returned zero whitelisted docs; `SearchError` fail-fast; `ResearchStageError` |
| Adaptive follow-up empty-result fix | FIXED (offline) | `tests/test_search_collector.py` (3 new tests) | empty results no longer fail-fast; all-provider errors still raise; 830 passed |
| Live projections | PASS (engineering) | `experiments/quality/live_smoke_20261120*/` | first 273 nodes / 1,869 edges; second 256 / 1,785; third 165 / 1,077; fourth graph 409, report empty |
| Explicit focus fix | PASS | `test_explicit_focus_wins_over_discovery`; `test_deep_mock_pipeline_emits_fine_grained_events` | second run focus `竹产业`; discovery completion 838 < 2,048; API/worker path asserted |
| Region retrieval gate | PASS (live + offline) | `tests/test_region_relevance.py` (13 tests); fourth-run event | second-run recorded sources: 5 off-region dropped, 3 Anji kept; third run: 7 Anji / 1 false positive; fourth run: 27 kept / 4 dropped (3 other-region, 1 national) |
| Region gate live finding | FIXED (offline) | third run sources + reclassification | Guizhou plan with “安吉精铸/正安吉他” was kept; full-name rule now marks it `OTHER_REGION` (7 region / 1 other-region); fourth run did not complete the specific re-check |
| Backend suite after fixes | PASS | `PYTHONPATH=src python -m pytest --no-cov -q` | `795 passed in 37.07s` at the region-gate stage; `827 passed` after the 2024 fix; `830 passed` after the empty-result fix |
| Live research quality | FAIL | report verification | first 0/239 `NOT_COMPARABLE`; second 0/224; third 0/133; fourth no verification (job failed); 7/7/6 conflicts; 2 gaps in runs 1–3 |
| Cost gate | PASS | `docs/goal/LIVE_SMOKE_COST_GATE.md` | first ≤ $0.0578; second ≤ $0.0579; third ≤ $0.0585; fourth ≤ $0.0905; 0 guard violations in all four |
| Provider config | FINDING | root `.env` | Gemini endpoint/model configured with a DeepSeek key; smokes used process overrides, `.env` untouched |
| Live evaluation / semantic Judge | NOT_RUN | — | four smokes do not satisfy M5 |

The first three smokes prove the real provider adapters and job path, not
research quality. The first two runs returned off-region sources; the third run,
after the region gate, was Anji-centred and exposed one short-name false
positive (a Guizhou plan containing “安吉精铸”/“正安吉他”). The classifier was
fixed to require the full `安吉县` in content and a word boundary for the short
name; replaying the third run's stored sources now marks that plan
`OTHER_REGION` (7 region / 1 other-region).

The fourth run is the first live exercise of the 2024-window and adaptive
plumbing. It kept 27 and dropped 4 documents at the region gate, recorded
`target_years=["2024"]` with 1 in-window claim/source, and generated four
target-year follow-up queries. It then failed in `collect_adaptive`: all four
gov-channel queries returned zero whitelisted documents, and the pre-existing
`fail_fast` branch in `SearchCollector._run_tasks` raised `SearchError`, which
the worker reported as `ResearchStageError`. No verification, evidence
persistence, graph or report was produced. No code was changed for this run and
no fifth run was made. See `docs/goal/LIVE_SMOKE.md` for the root cause and
offline reproduction.

## Adaptive follow-up fix acceptance (2026-11-20)

Revision: `codex/finish-roadmap` after the fourth-run record.

| Check | Status | Command / artifact | Observed |
| --- | --- | --- | --- |
| Empty gov follow-up is not a failure | PASS | `pytest tests/test_search_collector.py` | `11 passed`; a gov query returning `[]` yields an empty result, not `SearchError` |
| All-provider errors still fail fast | PASS | same | `SearchError` with `failed_tasks == tasks_count` |
| Mixed empty/error is not all-failure | PASS | same | one empty success + one provider error returns `[]` |
| Full backend suite | PASS | `pytest --no-cov -q` | `830 passed in 23.53s` |
| Ruff | PASS | `ruff check src tests` | `All checks passed!` |
| Fifth Live run | NOT_RUN | — | needs fresh authorization |

The fix changes only the failure classification in `SearchCollector._run_tasks`;
it does not relax the verifier or change provider behavior.

## 2024 period coverage and claim region fix acceptance (2026-11-20)

Revision: `codex/finish-roadmap` @ `d186577`; `.venv` Python 3.13.7.
Details and code locations: `docs/goal/2024_PERIOD_COVERAGE_FIX_REPORT.md`.

| Check | Status | Command / artifact | Observed |
| --- | --- | --- | --- |
| Phase 1 claim region tests | PASS | `pytest tests/test_claim_region.py` | county claim allowed; Guizhou plan not county; mixed article yields two regions; UNKNOWN not promoted; cross-region conflict isolated; `region_present=false` blocks support |
| Phase 2 window propagation | PASS | `pytest tests/test_date_window_propagation.py` | contract → request → application → collector → QueryEngine; all three modes include the target year; 2025-published/2024-data page retained |
| Phase 3 adaptive period stop | PASS | `tests/test_adaptive_retrieval.py`, `tests/test_period_coverage_flow.py` | topical coverage alone does not set `quality_met`; period gap generates `2024年` query; event carries real query text and per-round coverage |
| Phase 4 claim period | PASS | `tests/test_measure_identity.py`, `tests/test_evidence_ledger.py`, `tests/test_evidence_graph.py` | local 2018 wins over document 2023; 2030 plan target wins over 2026; `2024-2025` stays a span and is rejected for a 2024 window; 2023/2025 rejected |
| Phase 5 provider dates/truncation | PASS | `tests/test_search_web.py`, `tests/test_deep_retrieval.py`, `tests/test_source_contract.py` | Tavily `published_date` parsed; `tYYYYMMDD` and `/YYYYMM/` URL dates; body-only date rejected; provider truncation sets `content_truncated=True` and original length |
| Targeted new regressions | PASS | 8 modules listed in the fix report | `85 passed in 1.10s` |
| P0 regressions | PASS | `test_evidence_store.py`, `test_evidence_graph.py`, `test_report_projection.py` | `49 passed in 2.96s` |
| Full backend suite | PASS | `python -m pytest -q` | `827 passed in 35.24s`; `830 passed` after the separate empty-result fix |
| Ruff (source and tests) | PASS | `python -m ruff check src tests` | `All checks passed!` |
| API compatibility | PASS | worker/contract tests | optional date fields default to `None`; existing callers unchanged |
| Real 2024 retrieval | PARTIAL | fourth Live `retrieval.period_coverage` | fourth run recorded target `2024` and 1 in-window claim/source, then failed in adaptive follow-up before verification; no completed 2024 research result |
| Live research quality | FAIL | fourth Live job `4f4d6610f48248a599e6b112ce5b9ee0` | `FAILED` (`execution_error`); no report verification; this fix does not claim a SUFFICIENT Live outcome |
