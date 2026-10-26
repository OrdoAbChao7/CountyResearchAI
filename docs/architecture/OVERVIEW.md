# AxiomScope Architecture Overview

AxiomScope (formerly CountyResearchAI) is an evidence-native research
intelligence workspace for county and regional industry questions. The MVP
scope is regional industry research; medicine, law, securities advice, and
general-purpose agent use are out of scope.

Status: engineering slice through M4. Research acceptance is still open
(`docs/goal/STATE.md`).

## Components

| Layer | Location | Responsibility |
| --- | --- | --- |
| Domain contracts | `src/county_research_ai/domain/` | `ResearchContract`, `ResearchSpec`, `QuestionSlot`, claims, outcomes |
| Search | `src/county_research_ai/search/` | provider adapters, adaptive slot retrieval, BM25 lexical baseline |
| Evidence | `src/county_research_ai/evidence/` | source contract, in-memory ledger, SQLite temporal graph, deterministic verification |
| Application | `src/county_research_ai/application/` | collect → discover → evidence → analyze → report |
| Modes | `src/county_research_ai/modes/` | snapshot, rise-fall, long-history |
| Agent | `src/county_research_ai/agent/` | bounded plan/execute runtime (legacy-compatible) |
| API | `src/county_research_ai/api/` | FastAPI `/api/v1`, durable jobs, SSE, findings, briefs |
| Web | `web/` | React + Vite workspace |
| Evaluation | `src/county_research_ai/evaluation/`, `scripts/` | offline rescoring, replay, metrics |

## Research path

```text
ResearchContract (objective, regions, window, thresholds, caps)
        │
        ▼
ResearchRequest ──► collect ──► discover ──► build evidence
                                                  │
                         SourceDocument / EvidenceChunk / AtomicClaim
                                                  │
                                       EvidenceLedger (selection)
                                                  │
                                       EvidencePack + reasons/gaps
                                                  │
                          analyze ──► report; findings persisted first
                                                  │
                        EvidenceGraphStore (SQLite, append-only)
                                                  │
                       findings ──► decision brief (Markdown)
```

## Verification semantics

The deterministic verifier (`evidence/graph.py`) checks:

- snapshot content hash and span content hash;
- exact offsets resolve to the quote (`offset_quote_mismatch` otherwise);
- claimed numeric value + unit appear in the quote;
- region, period, scope, caliber, and series version are compatible;
- the requested `date_window` contains the claim period;
- independent support is counted by canonical URL, so reposts do not inflate it.

Statuses are disjoint: `SUPPORTED`, `CONTRADICTED`, `INSUFFICIENT`,
`NOT_COMPARABLE`, `OUTDATED`, `NEEDS_REVIEW`. A credible source alone never
produces `SUPPORTED`. A baseless contradictory claim cannot override a supported
one; two independently supported conflicting claims become `NEEDS_REVIEW`.
This is **not** semantic entailment.

## API

Base path `/api/v1`. Interactive docs at `/docs`, health at `/health`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/research/tasks` | create a task from a `ResearchContract` |
| GET | `/research/tasks` | list task history |
| GET | `/research/tasks/{id}` | status, contract, result, budget enforcement |
| POST | `/research/tasks/{id}/cancel` | request cancellation |
| POST | `/research/tasks/{id}/resume` | re-run an interrupted/failed/cancelled job |
| GET | `/research/tasks/{id}/events` | JSON event log |
| GET | `/research/tasks/{id}/stream` | SSE event stream |
| GET | `/research/tasks/{id}/findings` | findings with claim + spans + snapshots |
| GET | `/research/tasks/{id}/claims/{claim_id}` | one claim chain + relations |
| GET | `/research/tasks/{id}/sources` | sources for this run |
| GET | `/research/sources/{snapshot_id}` | full snapshot content |
| GET | `/research/tasks/{id}/brief` | Markdown decision brief |
| GET | `/research/tasks/{id}/report` | legacy Markdown report |
| GET | `/capabilities` | mode label, schema versions, enforced caps |

Errors use a consistent shape: `{"error": {"code": "...", "message": "...",
"details": [...]}}`. IDs are validated; report paths must stay inside the
reports root; model keys and stack traces are never returned.

## Execution and durability

Jobs are stored in SQLite (`jobs`, `job_events`) and executed by a small
in-process thread pool. This is a single-node demo queue, not a distributed
scheduler. If the process dies, startup marks `RUNNING` jobs `INTERRUPTED`;
`POST /resume` re-queues them explicitly. Cancellation and deadline checks run
between stages, not inside a single provider call.

Outcomes never conflate budget exhaustion with sufficiency: `SUFFICIENT`,
`BUDGET_EXHAUSTED`, `NO_PROGRESS`, `CONFLICT_UNRESOLVED`,
`NEEDS_HUMAN_REVIEW`, `CANCELLED`, `FAILED`.

## Modes and labels

- `MOCK`: search and LLM adapters are fixtures. The default for the API.
- `LIVE`: only when `AXIOMSCOPE_API_LIVE=true` and both provider keys exist.
- `FIXTURE` / `REPLAY`: offline evaluation artifacts.

The API's `mode_label` is visible on every task and in every brief.

## Known limits

- `max_steps`, `max_search_calls`, and `max_cost` are not enforced on the legacy
  workflow path; the API reports them as `not_enforced_on_workflow_path`.
  `max_tokens` and `max_documents` are per-call/per-collection bounds, not
  cumulative quotas; only `deadline_seconds` can produce `BUDGET_EXHAUSTED`.
- The deterministic verifier does not recognize semantic paraphrase or aliases.
- Long-history period routing can exclude evidence outside the contemporary
  boundary (documented in `PHASE6_EFFICIENCY_OPTIMIZATION_REPORT.md`).
- Offline matched-budget results currently do not show quality superiority over
  the baselines; the sample is small and not statistically conclusive.
