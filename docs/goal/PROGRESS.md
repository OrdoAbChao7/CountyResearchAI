# AxiomScope v2 — Progress Log

Each entry is a measured checkpoint. Commands are run from the repository root
with `.venv\Scripts\python.exe` on Windows.

## 2026-10-26 — session resume and baseline repair

- Inspected `git status`: branch `codex/evidence-first-v2`, HEAD `548016a`, 45 modified
  tracked files and ~20 untracked files from the prior evidence-first phases, no commits.
- Read `GOAL_EVIDENCE_FIRST_V2.md`, `PHASE7_EXPERIMENTAL_EVALUATION.md`,
  `ARCHITECTURE_BASELINE_AUDIT.md`, `docs/architecture/EVIDENCE_FIRST_V2.md`.
- Ran the full suite before changes: `594 collected, 593 passed, 1 failed`.
  The failure was `tests/test_continuation_audit.py` expecting resource status
  `CLOSED` but receiving `MISSING`.
- Root cause: `batch_manifest.json` records
  `E:\Projects\CountyResearchAI\experiments\...\continuation_resource_manager_20261019.sqlite`.
  The checkout was renamed to `AxiomScope`, so the recorded absolute path no longer
  exists even though the ledger is present. The stale traceback path is only a
  `.pyc` built at the old location.
- Fix: `scripts/audit_continuation_experiment.py` resolves frozen absolute paths
  against the current checkout (`recorded` → `relative_to_cwd` →
  `relocated_repo_relative` → `relocated_by_name` → `missing`) and records
  `path_source` / `recorded_path` in the audit result. Artifacts are not rewritten.
- Added `tests/test_audit_path_resolution.py` (4 tests) covering both relocation
  strategies, fail-closed behavior, and the reported metadata.
- Full suite after fix: `598 passed in 4.36s`, 0 failed.

## 2026-10-26 — M1/M2 contract and persistent evidence graph

- Added `ResearchContract` (objective, regions, inclusive date window, required
  questions, evidence thresholds, budget caps, output spec, domain adapter) with
  field-specific validation and ResearchSpec adapters. 9 tests.
- Added deterministic BM25 `LexicalIndex` with CJK bigram/ASCII tokenization,
  canonical-URL/content dedupe, stable corpus fingerprints, and negative-control
  tests (unrelated query → no results; metric term changes ranking). 10 tests.
- Added `EvidenceGraphStore` in SQLite: append-only `source_snapshots` and
  `evidence_spans`, `claims`, `claim_evidence_edges`, `claim_relations`,
  `verification_records`, `findings`, `run_snapshots`. Reload equality is
  tested; snapshot id collisions with different content raise.
- Deterministic verification: hash/offset integrity, value/unit presence,
  region/period/scope/caliber/version compatibility, independent-source count by
  canonical URL, disjoint statuses, symmetric conflict resolution. 18 tests.
- Full suite: `616 passed`.
- Commit: `b2c933f` (graph) and `a79a8fb` (contract + BM25).

## 2026-10-26 — M4 API, web workspace, and window fix

- Added FastAPI `/api/v1`: tasks, cancel, resume, JSON events, SSE stream, findings,
  claim chains, sources, brief, report, health, capabilities. Consistent error
  envelope; ID validation; report-path containment; CORS for Vite.
- Durable `JobStore` (jobs + events) and `JobRunner` (bounded in-process pool).
  Startup marks abandoned `RUNNING` jobs `INTERRUPTED`; resume is explicit.
  Disjoint outcomes prevent budget exhaustion from becoming `SUFFICIENT`.
- Added React + Vite workspace with task form, live timeline, evidence explorer
  (quote-highlighted immutable snapshot), and brief download.
- Live smoke exposed a false `SUPPORTED` 2027 planning target inside a 2024
  window. Verification now enforces the contract date window; claims outside the
  window or without a period are `NOT_COMPARABLE`.
- Reinstalled the editable package at the current checkout after discovering the
  venv `.pth` still pointed at the pre-rename path.
- Results: 659 Python tests, 4 Vitest tests, `tsc` clean, Vite build 160.8 kB JS;
  live API on :8011 returned `SUCCEEDED`/`SUFFICIENT` (MOCK), 3 sources, 6
  findings, 4,213-byte brief, and SSE frames.
- Commit: `e8a3304`.

## 2026-10-26 — M5 evaluation harness and release docs

- Added `scripts/run_multi_baseline_offline.py`, which aggregates the frozen v5
  matched-budget observations (48 runs / 240 observations, 0 provider calls)
  into per-group metrics with numerators/denominators and paired A/B vs C
  comparisons. Output: `experiments/evaluation/20261026_multi_baseline_offline/`.
- Result unchanged and negative: C trails A and B on GT recall/support precision
  and costs more. D, live, ablations, Judge, and the 40–60 task holdout are
  explicitly NOT_RUN / BLOCKED_EXTERNAL.
- Added `docs/evaluation/DESIGN.md`, `docs/evaluation/FINAL_REPORT.md`,
  rebranded `README.md`, `docs/career/RESUME_BULLETS.md`, and
  `docs/career/INTERVIEW_QA.md`.


## Prior phases (inherited, uncommitted)

Summarized from `GOAL_EVIDENCE_FIRST_V2.md`; see the phase reports for detail.

- Phase 1: source contract serializer, truncation audit, real Deqing replay.
- Phase 2: claim identity/equivalence classification, 12 negative cases, offline rescore.
- Phase 3: Pydantic contracts (`ResearchSpec`, `SourceDocument`, `EvidenceChunk`,
  `AtomicClaim`, `QuestionSlot`, `EvidencePack`) and in-memory `EvidenceLedger`.
- Phase 4: QuestionSlot adaptive retrieval; offline replay showed no measured lift
  (6 RawDocs; top-3 recall tied) — negative result retained.
- Phase 5: deterministic evidence-bound verification; not semantic entailment.
- Phase 6: architecture version tagging, long-history period packs, character-level
  prompt reduction (-71.8%), token effect unmeasured.
- Phase 7: frozen matched-budget rescore reproducible (0/240 field differences);
  current C-group metrics trail baselines on a small, non-significant sample.
