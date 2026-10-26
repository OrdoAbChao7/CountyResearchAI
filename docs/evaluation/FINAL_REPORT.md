# AxiomScope v2 — Evaluation Report

Date: 2026-10-26
Branch: `codex/evidence-first-v2`
Evidence kinds: unit/integration tests, offline replay, `MOCK` end-to-end smoke.
Provider calls this session: **0**. Semantic Judge calls: **0**.

## Verdict

Engineering acceptance for M0–M4 is supported by passing tests and a live local
smoke run. **M5 research acceptance is not met.** The available small-sample
offline evidence shows the legacy C group trailing A and B, and strategy D has
not been measured on the corpus. No claim that AxiomScope v2 outperforms the
baselines is made.

## Verified engineering evidence

| Check | Command | Result |
| --- | --- | --- |
| Python suite | `.venv\Scripts\python.exe -m pytest --no-cov -q` | **692 passed**, 1 Starlette deprecation warning |
| Frontend typecheck | `cd web; npm run typecheck` | clean |
| Frontend tests | `cd web; npm test` | 4 passed |
| Frontend build | `cd web; npm run build` | 40 modules, 160.8 kB JS / 8.9 kB CSS |
| API live smoke | `python -m county_research_ai.api` on `127.0.0.1:8011` | health + capabilities + built UI + SSE 200 |
| End-to-end task | `MOCK`, 2024 window, 德清县 | `SUCCEEDED` / `SUFFICIENT`, 3 sources, 6 findings, 4,213-byte brief |
| Budget exhaustion | API test with `deadline_seconds=1e-6` | `BUDGET_EXHAUSTED`, never `SUFFICIENT` |
| Cancellation | API test after persisted cancel request | `CANCELLED` at stage boundary |
| Relocation regression | `tests/test_audit_path_resolution.py` | 4 passed |

The live smoke exposed and fixed a real defect: a 2027 planning target had been
`SUPPORTED` inside a 2024 window. Claims outside the requested window or without
a period are now `NOT_COMPARABLE`. In the smoke run, the 2025/2027 claims were
correctly excluded and only the 2024 claim remained supported.

## Offline multi-baseline comparison

Source: frozen matched-budget corpus, 48 unique runs / 240 claim observations
across 18 task keys. Report:
`experiments/evaluation/20261026_multi_baseline_offline/summary.json` and
`dataset_manifest.json` (observations SHA-256 `4341ea07…2d5c1e`). Zero provider
calls.

| Group | Valid runs | GT recall (mean) | Support precision (pooled) | Fact accuracy | Error rate | LLM units/run | Seconds/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A traditional retrieval + one synthesis | 18 | 0.1600 | 0.1875 (12/64) | 0.2267 | 0.7733 | 6,608 | 41.43 |
| B general web AI | 18 | 0.1222 | 0.1358 (11/81) | 0.1667 | 0.8333 | 6,895 | 42.12 |
| C CountyResearchAI legacy | 12 | 0.0333 | 0.0357 (2/56) | 0.0417 | 0.9583 | 22,652 | 77.68 |

Paired on the 12 keys available to C:

- A vs C: mean GT-recall delta +0.1667; 5 A wins / 6 ties / 1 A loss.
- B vs C: mean GT-recall delta +0.1500; 4 B wins / 7 ties / 1 B loss.

Interpretation: on this inherited sample, C is worse and more expensive. Six C
long-history runs exceeded the 120 s budget and are excluded from the means.
The sample is small, not re-curated, and not statistically conclusive.

## Verifier ablation on frozen C raw archives

Source: all 18 archived group-C runs with raw documents. Report:
`experiments/evaluation/20261026_verifier_ablation/summary.json`.
Both sides see the same extracted claims and source text. Zero provider calls.

| Metric | Value |
| --- | ---: |
| Runs / documents / spans | 18 / 34 / 295 |
| Extracted claims | 1,275 |
| Legacy `verified` | 495 |
| Deterministic objective support (single-span hash/offset + value/statement + region/period) | 985 |
| Deterministic `SUPPORTED` after conflict resolution | 113 |
| Withheld by a supported conflict (`NEEDS_REVIEW`) | 872 |
| Downgraded (legacy verified → not supported) | 465 |
| Upgraded (legacy unverified → supported) | 83 |

Reason counts: `conflicting_supported_evidence` 872, `statement_not_in_span`
216, `statement_exact_in_span` 84, `numeric_value_without_period` 72,
`value_and_span_verified` 29, `no_evidence` 2.

What this shows: the single-span hash/offset/value/region/period checks pass
985 claims, but legacy claim identity is too coarse — many different statements
share metric/period/scope/caliber — so the conflict layer conservatively
withholds 872. This is **not** a verifier quality win. It identifies
claim-identity extraction as the next bottleneck. The verifier is intentionally
conservative here; loosening the identity rule to raise the supported count
would be a metric-gaming change.

## What was not measured

| Item | Status | Why |
| --- | --- | --- |
| Strategy D on the same corpus | PASS (dev + pilot) | `experiments/quality/20261026_q3_strategy_d/`; D E2E 15/90 dev, 4/10 blind pilot |
| 40–60 independent locked tasks | PARTIAL | 2 blind tasks / 10 exact-quote facts; gap documented |
| Live end-to-end retrieval/synthesis | BLOCKED_EXTERNAL | no fresh provider/Judge cost authorization |
| Ablations | PARTIAL | no-verifier, BM25/adaptive, old/new grouping done; no-gap, single-vs-multi-agent NOT_RUN |
| Independent semantic Judge | NOT_RUN | not authorized/executed |
| Human rubric adjudication | NOT_RUN | not executed |
| Retrieval Recall@K on a real query | NOT_RUN | archived replay is tied; live recall not run |
| Long-history token/cost improvement | NOT_RUN | only prompt characters were counted |
| Browser screenshots / E2E | PASS | Playwright 2/2; `experiments/quality/20261026_q5_e2e/` |

## Reproduction

```powershell
# Python tests
.venv\Scripts\python.exe -m pytest --no-cov -q

# Offline A/B/C aggregation (no provider calls)
.venv\Scripts\python.exe scripts\run_multi_baseline_offline.py

# Quality Recovery: Q3 Strategy D, Q4 blind pilot, Q5 browser E2E
.venv\Scripts\python.exe -m scripts.evaluate_strategy_d_offline
.venv\Scripts\python.exe -m scripts.evaluate_blind_pilot
cd web; npm run test:e2e; cd ..

# API + built workspace
cd web; npm install; npm run build; cd ..
.\scripts\start_api.ps1
# open http://127.0.0.1:8000
```

## Gate status

| Gate | Status |
| --- | --- |
| M0 baseline/audit | PASS |
| M1 retrieval/snapshot/eval foundation | PARTIAL — contract, snapshots, BM25, negative controls done; live replay/Recall@K not run |
| M2 temporal evidence graph | PASS — persistence, navigation, conflict/temporal/false-reference tests |
| M3 durable orchestration | PASS for the workflow path — resume/cancel/deadline tested; agent-path durable checkpoints remain opt-in |
| M4 API + workspace | PASS — Playwright E2E, leases/fencing, per-job storage |
| M5 multi-baseline research acceptance | FAIL / PARTIAL — D measured on dev + 2-task blind; 40–60 tasks, live, Judge, no-gap ablation missing |

## Outstanding work

1. Curate and lock 38–58 additional independent tasks with expected evidence quotes.
2. Implement and measure gap-driven/temporal retrieval; retrieval remains 69/90 missing on dev.
3. Obtain an explicit cost gate for a budgeted live run and a semantic Judge.
4. Run a two-process lease/fencing stress test; current invariants are store-tested.
5. Label a false-support/false-rejection audit sample; current samples are unlabelled.
