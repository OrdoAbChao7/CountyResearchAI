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
| Python suite | `.venv\Scripts\python.exe -m pytest --no-cov -q` | **659 passed**, 1 Starlette deprecation warning |
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

Source: frozen matched-budget corpus, 48 unique runs / 240 claim observations.
Report: `experiments/evaluation/20261026_multi_baseline_offline/summary.json`
(observations SHA-256 `4341ea07…2d5c1e`). Zero provider calls.

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
| Deterministic objective support (hash/offset + value/statement) | 1,243 |
| Deterministic `SUPPORTED` after conflict resolution | 173 |
| Withheld by a supported conflict (`NEEDS_REVIEW`) | 998 |
| Downgraded (legacy verified → not supported) | 417 |
| Upgraded (legacy unverified → supported) | 95 |

Reason counts: `conflicting_supported_evidence` 998, `statement_exact_in_span`
134, `numeric_value_without_period` 72, `value_and_span_verified` 39,
`statement_not_in_span` 30, `no_evidence` 2.

What this shows: the hash/offset/value layer passes most extracted claims, but
legacy claim identity is too coarse — many different statements share
metric/period/scope/caliber — so the conflict layer conservatively withholds
them. This is **not** a verifier quality win. It identifies claim-identity
extraction as the next bottleneck. The verifier is intentionally conservative
here; loosening the identity rule to raise the supported count would be a
metric-gaming change.

## What was not measured

| Item | Status | Why |
| --- | --- | --- |
| Strategy D on the same corpus | NOT_RUN | requires running the full v2 path on the frozen inputs; not done |
| 40–60 independent locked tasks | NOT_RUN | the inherited corpus is not a newly curated holdout |
| Live end-to-end retrieval/synthesis | BLOCKED_EXTERNAL | no fresh provider/Judge cost authorization |
| Ablations | PARTIAL | verifier ablation executed on C archives; no-graph, no-gap-research, BM25-vs-adaptive, single-vs-multi-agent NOT_RUN |
| Independent semantic Judge | NOT_RUN | not authorized/executed |
| Human rubric adjudication | NOT_RUN | not executed |
| Retrieval Recall@K on a real query | NOT_RUN | offline replay is 6 RawDocs and tied |
| Long-history token/cost improvement | NOT_RUN | only prompt characters were counted |
| Browser screenshots | NOT_RUN | no browser automation installed |

## Reproduction

```powershell
# Python tests
.venv\Scripts\python.exe -m pytest --no-cov -q

# Offline A/B/C aggregation (no provider calls)
.venv\Scripts\python.exe scripts\run_multi_baseline_offline.py

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
| M4 API + workspace | PASS functionally; screenshot inspection NOT_RUN |
| M5 multi-baseline research acceptance | FAIL / PARTIAL — design and offline A/B/C report exist; D, 40–60 tasks, ablations, live and Judge are missing |

## Outstanding work

1. Curate and lock a 40–60 task independent set with expected evidence quotes.
2. Run D on the same frozen inputs; then paired A/B/C/D offline.
3. Execute the pre-registered ablations on a dev split.
4. Obtain an explicit cost gate for a budgeted live run and a semantic Judge.
5. Capture screenshots/recording with installed browser automation.
