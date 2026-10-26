# AxiomScope v2 — Acceptance Ledger

Status values: `PASS`, `FAIL`, `BLOCKED_EXTERNAL`, `NOT_RUN`, `PARTIAL`.

## Evidence format

Every PASS needs: command, exit code, observed count, artifact path, revision.

## Baseline transport and tests

| Check | Status | Command / artifact | Observed |
| --- | --- | --- | --- |
| Full unit/integration suite | PASS | `python -m pytest --no-cov -q` | `598 passed in 4.36s`, exit 0 (2026-10-26) |
| Relocated manifest audit | PASS | `tests/test_audit_path_resolution.py` | 4 passed |
| Real frozen batch audit | PASS | `tests/test_continuation_audit.py` | 1 passed |
| Baseline freeze | PASS | `ARCHITECTURE_BASELINE_AUDIT.md` | legacy `52a6ed0` untouched |

## Milestone gates

| Milestone | Status | Why |
| --- | --- | --- |
| M0 audit/freeze | PASS | code-backed audit + reproduced suite + artifact taxonomy |
| M1 retrieval/snapshot/eval foundation | PARTIAL | snapshots/chunks exist; contract caps, query-aware BM25 baseline + negative controls, replay runner missing |
| M2 temporal evidence graph | PARTIAL | in-memory ledger + deterministic verifier; no persistence, spans/edges/relations/verification records |
| M3 durable orchestration | PARTIAL | bounded runtime + opt-in long-history checkpoints; no crash/restart resume, cancellation, disjoint finish-state contract |
| M4 API + web workspace | NOT_STARTED | no FastAPI, no frontend |
| M5 multi-baseline evaluation + release | PARTIAL | offline rescore and honest negative results; A/B/C/D harness, locked real task set, ablations, final report missing |

## Never claimed

- That Evidence-First v2 outperforms the baselines. Current small-sample offline
  results show the opposite for group C.
- Semantic entailment, token savings, or statistical significance.
- Screenshots or live-provider runs that were not actually executed.
