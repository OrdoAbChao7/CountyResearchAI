# ADR-005 — Single evidence core: productize the `/api/v1` job line, keep V2 experimental

Status: accepted (2026-11-26)
Baseline: `master` @ `eaa611e`

## 1. Context: two parallel backends on `master`

`master` carries two runtime stacks (plus a minimal `web/app.py` skeleton that only mounts system/meta routes):

| Dimension | `/api/v1` job line (`api/app.py`) | V2 LangGraph line (`api/main.py`) |
| --- | --- | --- |
| HTTP entry | `api/app.py` → `/api/v1/research/tasks/...` | `api/main.py` → `/api/research`, `/api/graph`, `/api/evidence`, `/api/reports`, `/api/simulations` |
| Frontend (`web/`) | **All frontend calls target `/api/v1`** | Not called by `web/` |
| Orchestration | `research_agent/coordinator.py` + `api/worker.py` (SQLite jobs, leases/fencing, SSE, cancel/resume) | `orchestration/` (supervisor, subgraphs, LangGraph SQLite checkpointer) |
| Evidence store | `evidence/graph.py`: persistent SQLite (schema v3), `finding → claim → span → snapshot`, many-to-many `finding_slots` | `services/evidence_service.EvidenceService`: per-run wrapper over `evidence/store.EvidenceStore` (in-memory / JSON snapshot) |
| 0.65 source credibility gate | Enforced (`source_contract.meets_source_credibility_threshold` in `graph`, `ledger`, `coordinator`) | Not wired |
| `date_window` / claim-level region / `NOT_COMPARABLE` | Enforced | **Zero references** across `services/`, `orchestration/`, `agents/` |
| Per-question contract evaluation (PR 4) | Designed for this path (`api/contract_coverage.py`) | Not present |
| Shared primitives | `search/collector.SearchCollector`, `evidence/store` extraction, `evidence/support.check_claim_evidence` | Same |
| Shining Stars | Evidence workbench, verified report, Cytoscape graph | Gap radar, digital twin, temporal graph, Neo4j |
| Paid Live smoke | All 12 bounded Live smokes ran here | None |

Core problem: the project's central guarantee is deterministic, auditable evidence verification, which is enforced only on the `/api/v1` job line, while the V2 stack bypasses those gates and has no frontend caller. Every new capability otherwise forces either duplicate implementation or split semantics.

## 2. Decision drivers

1. Every factual claim surfaced to users or downstream analytics must pass the same credibility threshold, deterministic verifier, `date_window`, and region rules.
2. There must be a single user-facing product surface.
3. Minimize throwaway rewrites; preserve existing tests, projection invariants, and Live audit records.
4. Keep an evolution path for Shining Stars (gap radar, digital twin, temporal queries) once upstream evidence coverage supports them.

## 3. Options considered

### Option A — `/api/v1` job line as the single evidence core; V2 frozen as experimental downstream consumer (Chosen)

- `evidence/graph.py` is the sole authoritative evidence store.
- `agents/`, `orchestration/`, `knowledge_graph/`, `shining_stars/`, and `api/main.py` are marked **experimental** and frozen to bug fixes until adapted.
- When Shining Stars are resumed, `services/evidence_service` becomes a read-only adapter over `evidence/graph.py` exposing only `SUPPORTED` findings that passed window and region checks; analytical outputs remain explicitly labeled `INFERRED` / `PENDING`.
- PR 4 (contract per-question evaluation) lands directly on the `/api/v1` job line as planned.

### Option B — V2 as the single core; port `/api/v1` guarantees into `orchestration/`

- Requires re-implementing `graph.py` persistence, window/region/credibility gates, contract evaluation, job leases/fencing, SSE projections, and rewiring `web/`.
- Invalidates all 12 Live smoke baselines without evidence that multi-agent planning improves end-to-end factual recall. Rejected for now.

### Option C — Shared evidence kernel with two active orchestrators

- Solves verification drift, but still leaves two job stores, two APIs, and double maintenance. Acceptable only as a transient step inside Option A, not as a target state.

### Option D — Status quo

- Rejected; perpetuates split invariants.

## 4. Decision & rollout order

Adopt **Option A** in five independently reversible steps:

1. **Freeze & label**: document `agents/`, `orchestration/`, `knowledge_graph/`, `shining_stars/`, `api/main.py`, and `web/app.py` as experimental / non-product in architecture docs and `README.md`; restrict changes there to bug fixes and compatibility maintenance.
2. **Complete PR 4 on `/api/v1`**: port `contract_coverage`, `enterprise_leads`, per-question worker outcomes, and projections onto `master`.
3. **Prioritize recall before new analytics**: address PDF body parsing and official statistical/government source acquisition, and evaluate across multiple counties/industries before resuming downstream features.
4. **Read-only evidence adapter**: adapt `services/evidence_service` to read verified (`SUPPORTED`) findings from `evidence/graph.py` with contract tests locking `verification_status`, `period`, and `region_id` pass-through.
5. **Entrypoint consolidation & Shining Stars gate**: keep `/api/v1` (`api/app.py`) as the sole product API (mounting any retained simulation/graph endpoints under `/api/v1/experimental/...` or retiring `api/main.py` / `web/app.py`), and gate Gap Radar resumption on achieving `SUPPORTED` enterprise coverage.

## 5. Consequences

- **Positive**: one set of verification invariants, one product API (`/api/v1`), one durable job store, and full continuity with PR 1–3, PR 4, `web/`, and historical Live audits.
- **Negative**: LangGraph multi-agent orchestration is not on the product path; external descriptions must distinguish the production evidence-first pipeline from experimental multi-agent/analytics modules.
- **Guardrail**: any future bridge from `evidence/graph.py` into `services/` or `shining_stars/` must carry deterministic tests proving unverified (`INSUFFICIENT`, `NOT_COMPARABLE`, `CONTRADICTED`, `OUTDATED`, `NEEDS_REVIEW`) claims cannot enter analytical inputs as facts.

## 6. Reversal criteria

Revisit Option B only if, on a locked multi-county holdout set sharing the exact same `evidence/graph.py` verification kernel, LangGraph orchestration demonstrates a statistically significant end-to-end recall gain (e.g., task-clustered bootstrap 95% CI lower bound > 0) within matched cost/latency budgets.
