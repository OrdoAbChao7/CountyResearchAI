# AxiomScope v2 — Goal State

Updated: 2026-10-26
Branch: `codex/evidence-first-v2`
Repository: `E:\Projects\AxiomScope` (formerly `E:\Projects\CountyResearchAI`)

## Verified baseline

| Item | Value |
| --- | --- |
| HEAD | `548016aa1224385e7bd5f6e7f81e39b79a61c59a` |
| Legacy baseline | `52a6ed0f5164721cece221ffb9e7f67f73ac3dd7` on `codex/experiment-superiority` (frozen) |
| Python | 3.13.7 (`.venv`) |
| pytest | 9.1.1 |
| Test suite at this checkpoint | `598 passed` (`pytest --no-cov -q`), 0 failed |
| Prior claim under review | `578 passed` — stale by 20 tests; earlier run also had 1 failure caused by a relocated absolute path in a frozen manifest |

The one pre-existing failure (`test_continuation_audit`) was a genuine portability defect, not a test artifact: frozen batch manifests store absolute paths from the old repo location. `scripts/audit_continuation_experiment.py` now resolves recorded paths against the current checkout without mutating the artifacts, and reports `path_source`/`recorded_path`. Regression coverage: `tests/test_audit_path_resolution.py`.

## Milestone gate map

| Milestone | Gate | Status | Evidence | Remaining work |
| --- | --- | --- | --- | --- |
| M0 legacy audit + freeze | mirror actual code, reproduce baseline, classify mock/fixture claims | **PASS** | `ARCHITECTURE_BASELINE_AUDIT.md`, `docs/architecture/EVIDENCE_FIRST_V2.md`, `docs/goal/*`, full suite green | keep audit current as code moves |
| M1 retrieval / snapshots / eval foundation | source snapshots with hashes+offsets, replay, query-aware lexical baseline, negative controls | **PARTIAL** | `evidence/source_contract.py`, `domain/research_contracts.py::SourceDocument/EvidenceChunk`, `search/adaptive_retrieval.py`, offline replay scripts, `PHASE4`/`PHASE7` | explicit `ResearchContract` with budget caps/deadline/date_window/thresholds; query-aware BM25 baseline with negative controls; snapshot replay runner |
| M2 temporal evidence graph + claim verification | persistent typed graph, navigable finding→claim→span→snapshot, conflict/temporal semantics | **PARTIAL** | in-memory `evidence/ledger.py`; deterministic `evidence/bound_verifier.py`; `evaluation/claim_verification.py` statuses | SQLite persistence; `EvidenceSpan`, `ClaimEvidenceEdge`, `ClaimRelation`, `VerificationRecord`; `OUTDATED`/`NOT_COMPARABLE` semantics; reload-equality tests |
| M3 durable orchestration | bounded loop, checkpoint/resume after restart, disjoint finish states | **PARTIAL** | `agent/runtime.py` bounded loop; long-history checkpoints; `search/adaptive_retrieval.py` stop reasons | runtime checkpoint/resume, cancellation, budget-exhausted vs sufficient separation, resume integration tests |
| M4 API + web workspace | FastAPI `/api/v1`, SSE, cancel/resume, evidence explorer, brief export, React app | **NOT_STARTED** | none | full vertical slice |
| M5 genuine multi-baseline evaluation + release docs | A/B/C/D paired eval, locked test set, ablations, final report, README/ADR/demo | **PARTIAL** | frozen matched-budget rescoring (`PHASE7`), honest negative results | evaluation design + 40–60 real tasks or documented pilot, A/B/C/D harness, ablations, `FINAL_REPORT`, rebranded README/ADR/demo/career docs |

## Constraints in force

- No new paid Provider or Judge calls without an explicit fresh cost gate.
- Historical experiment artifacts are immutable; new artifacts go to new directories.
- No destructive git operations, no force push, no external deployment.
- Mock / fixture / replay / live evidence must stay explicitly labeled.
- Public CLI and legacy modes must remain available.

## Next executable action

Implement M2 persistence: a SQLite evidence graph that serializes the existing
in-memory `EvidenceLedger` (sources, chunks, claims) into typed tables
(`source_snapshots`, `evidence_spans`, `claims`, `claim_evidence_edges`,
`claim_relations`, `verification_records`), reloads to an identical ledger, and
exposes finding→claim→span→snapshot navigation. Then M1 contract caps, then M4.
