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
