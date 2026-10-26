# AxiomScope — Resume Bullets

Only measured, defensible statements. Do not claim quality superiority over the
legacy baselines; the current offline sample does not support it.

## Variant 1 — Research / applied ML engineer

- Designed an evidence-native regional research pipeline that persists source
  snapshots, exact evidence spans, claims, and findings in an append-only SQLite
  graph, enabling finding → claim → quote → snapshot navigation after restart.
- Implemented deterministic claim verification (hash/offset integrity, value and
  unit presence, period/scope/caliber compatibility, requested date window) with
  disjoint `SUPPORTED` / `CONTRADICTED` / `INSUFFICIENT` / `NOT_COMPARABLE` /
  `OUTDATED` / `NEEDS_REVIEW` states and negative-control tests; 662 Python tests
  pass.
- Rebuilt multi-baseline evaluation over a frozen 48-run / 240-observation corpus
  with zero provider calls; reported an honest negative result (legacy group C
  trailed A/B) and marked unmeasured strategies explicitly instead of inferring
  them.

## Variant 2 — Backend / platform engineer

- Built a FastAPI research service (`/api/v1`) with durable SQLite job history,
  SSE event streaming, cancellation, explicit restart-resume, claim/source
  endpoints, and Markdown briefing; consistent error envelopes and path
  containment validated by integration tests.
- Designed disjoint finish outcomes so budget exhaustion or process restart can
  never be reported as sufficient evidence; verified with deadline and
  cancellation integration tests.
- Ran the API and built React workspace end-to-end offline (`MOCK`): 3 stored
  sources, 6 structured findings, 4.2 kB brief; surfaced enforced vs unenforced
  budget caps in the response.

## Variant 3 — Full-stack product engineer

- Delivered a React + Vite evidence workspace (task submission with budget and
  evidence thresholds, live timeline, quote-highlighted immutable source viewer,
  brief export) backed by a typed FastAPI service; TypeScript check, 4 Vitest
  tests, and production build pass.
- Converged legacy and new contracts through compatibility adapters while
  preserving the original CLI and three research modes; 662-test suite covers
  both paths.
- Documented architecture, ADRs, a 90-second demo script, evaluation design, and
  an acceptance ledger that records PASS / FAIL / BLOCKED_EXTERNAL statuses
  instead of overstating completion.
