# AxiomScope Architecture Overview

AxiomScope (formerly CountyResearchAI) is an evidence-native research
intelligence workspace for county and regional industry questions. The MVP
scope is regional industry research; medicine, law, securities advice, and
general-purpose agent use are out of scope.

Status: engineering slice through M4 plus the 2026-11-20 Finish Roadmap
(deep-research capture, fine-grained events, graph/report projections, Wizard).
Research acceptance is still open (`docs/goal/STATE.md`); M5's 40–60 task
holdout, live evaluation, semantic Judge and human labels remain unfinished.

## Components

| Layer | Location | Responsibility |
| --- | --- | --- |
| Domain contracts | `src/county_research_ai/domain/` | `ResearchContract`, `ResearchSpec`, `QuestionSlot`, claims, outcomes |
| Search | `src/county_research_ai/search/` | provider adapters, adaptive slot retrieval, BM25 lexical baseline |
| Evidence | `src/county_research_ai/evidence/` | source contract, in-memory ledger, SQLite temporal graph, deterministic verification |
| Application | `src/county_research_ai/application/` | collect → discover → evidence → analyze → report |
| Research agent | `src/county_research_ai/research_agent/` | question tree, Critic, economic/policy/industry agents, synthesizer |
| Modes | `src/county_research_ai/modes/` | snapshot, rise-fall, long-history |
| Observability | `src/county_research_ai/observability/` | ContextVar-bound event sink; no-op when unbound |
| Agent | `src/county_research_ai/agent/` | bounded plan/execute runtime (legacy-compatible) |
| API | `src/county_research_ai/api/` | FastAPI `/api/v1`, durable jobs, SSE, evidence, projections |
| Projections | `src/county_research_ai/api/projections/` | read-only graph, report, questions, evidence and citation views |
| Web | `web/` | React 18 + Vite 5 wizard, report studio, evidence drawer, Cytoscape graph |
| Evaluation | `src/county_research_ai/evaluation/`, `scripts/` | offline rescoring, replay, metrics |

## Research path

```text
ResearchContract (objective, regions, window, thresholds, caps)
        │
        ▼
ResearchRequest ──► collect ──► discover ──► build evidence
        │                                         │
        │  options.deep_research                  │
        ▼                                         ▼
DeepResearchCoordinator                    EvidenceLedger (selection)
  question tree                           EvidencePack + reasons/gaps
  adaptive retrieval / Critic                      │
  economic / policy / industry agents              ▼
  synthesizer                              EvidenceGraphStore (SQLite)
        │                                         │
        │ emit(EventDraft)                        │ findings
        ▼                                         ▼
JobEventSink ──► job_events (SQLite)      report render (Markdown)
                        │                         │
                        ▼                         ▼
                  SSE / events            jobs.result_json
                                                  │
                                                  ▼
                       projections: /graph /report.json /questions /evidence
                                                  │
                                                  ▼
                                    React wizard (step rail, graph, report,
                                    evidence drawer, agent timeline)
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

## Deep research capture

When `contract.options.deep_research` is true, each mode stores the complete
`DeepResearchResult` on the run context (`application/context.py:47`, and
`modes/snapshot.py`, `modes/rise_fall.py`, `modes/long_history.py`). The field is
excluded from context repr/serialization, so a context dump cannot leak raw
documents or the evidence store. After the analyze stage the worker reduces the
result to a JSON-safe projection (`api/worker.py:359`): question tree, coverage,
reflection/retrieval counters, evidence items, conflicts and gaps. That
projection is written into the existing `jobs.result_json`; there is no second
run store. Cancellation, lease/fencing and deadline checks still run between
stages exactly as before.

## Fine-grained events

`observability/events.py` defines `EventDraft`, a `ContextVar` sink, and an
`emit()` that swallows sink failures: observation can never abort research.
`contextvars` do not cross threads, so the runner binds the sink inside the
worker thread (`api/worker.py:122`) with `push_event_sink`, and resets it in
`finally`. `api/event_sink.py` adapts each draft to the existing
`JobStore.append_event`, which allocates a per-job monotonic `seq` in SQLite.
The SSE endpoint replays from `after` / `Last-Event-ID` and closes after a
terminal event.

The coordinator emits only real work: `question_tree.created`,
`retrieval.round.started/completed`, `evidence.ingested`,
`question_tree.coverage`, `reflection.started/completed`, `gaps.detected`,
`conflicts.detected`, `agent.started/completed`, `synthesis.started/completed`.
Stage events, `evidence.persisted`, `report.rendered` and `job.completed` come
from the worker. Every completed retrieval round has a matching started event.
There are no fabricated section-stream or token-usage events.

## Graph and report projections

`api/projections/` is read-only and derives everything from persisted data:

- `graph.py` builds county, question, evidence, source, topic, gap and conflict
  nodes plus typed edges. IDs are content/identity hashes, URLs are normalized,
  parallel edges get `:p{n}` suffixes, self-loops are dropped and counted, and
  every evidence/source relation points back to a snapshot and span. Conflicts
  get `conflicts_with` edges only when at least two claim URLs match persisted
  evidence; unmatched claims stay visible without fabricated edges. Defaults
  are 400 nodes / 800 edges; required question/gap/conflict nodes are kept and
  truncation grows a connected subgraph instead of returning isolated points.
- `report.py` generates six sections from structured facts: summary, verified
  facts, disputes, gaps, sources, method. Only `SUPPORTED` findings enter the
  verified table. Snapshot runs report `native_sections`; rise-fall/long-history
  use `markdown_split` and label the legacy narrative as background material.
  Citation numbers derive from real findings and deduplicated URLs. Source text
  is HTML-escaped, pipes are escaped in tables, and citation links are limited
  to `http(s)` with a host.
- `questions.py` and `evidence.py` expose the question tree/coverage and the
  drawer list. Runs without deep research return `409 artifacts_unavailable` /
  `deep_research_disabled` rather than empty artifacts. The wizard exposes
  report citations, the evidence drawer and the graph as one navigable chain;
  a citation can jump to graph evidence and back.

## Fact-integrity guards (P0)

1. **Conflicting numbers cannot stay verified.** `EvidenceStore` marks
   comparable conflicting items `conflicting` and remembers the original status,
   so repeated imports recompute the same unresolved conflict instead of
   clearing it (`evidence/store.py:406`). The verifier returns `NEEDS_REVIEW`
   when a supported claim also has supported contradicting claims
   (`evidence/graph.py:1344`), and `numeric_context_matches` binds direction,
   period, scope and unit to the same local clause
   (`evidence/numeric_support.py`).
2. **Entities need accurate evidence.** Enterprise evidence keeps the original
   source clause, rejects negated/uncertain mentions, and never synthesizes a
   company from a document-level keyword (`evidence/store.py:184`). The
   regression controls are in `tests/test_evidence_store.py`.
3. **Reports cannot rewrite verified facts.** Verified report rows are rendered
   programmatically from persisted claim fields, value/unit/period/caliber are
   copied rather than regenerated, and untrusted text is escaped before Markdown
   (`api/projections/report.py`). Valid evidence IDs cannot back an unrelated
   number because citations are built from the same finding chain. Malicious
   source regressions live in `tests/test_report_projection.py`.

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
| GET | `/research/tasks/{id}/claims` | all claim chains for the run |
| GET | `/research/tasks/{id}/claims/{claim_id}` | one claim chain + relations |
| GET | `/research/tasks/{id}/sources` | sources for this run |
| GET | `/research/tasks/{id}/questions` | question tree, coverage and gaps |
| GET | `/research/tasks/{id}/graph` | evidence graph projection (`max_nodes`, `max_edges`, `include_sources`, `topics`) |
| GET | `/research/tasks/{id}/evidence` | evidence drawer list with filters |
| GET | `/research/sources/{snapshot_id}` | full snapshot content |
| GET | `/research/tasks/{id}/brief` | Markdown decision brief |
| GET | `/research/tasks/{id}/report` | program-generated verified report |
| GET | `/research/tasks/{id}/report.json` | sections, citations, conflicts, gaps |
| GET | `/research/tasks/{id}/report/draft` | legacy Markdown, confined to the reports root |
| GET | `/capabilities` | mode label, schema versions, enforced caps |

Errors use a consistent shape: `{"error": {"code": "...", "message": "...",
"details": [...]}}`. IDs are validated; report paths must stay inside the
reports root; model keys and stack traces are never returned.

## Execution and durability

Jobs are stored in SQLite (`jobs`, `job_events`) and executed by a small
in-process thread pool. This is a local queue, not a distributed scheduler.
Execution uses a lease (`lease_owner`, `lease_expires_at`) plus a monotonic
`fencing_token`: a worker renews the lease from a heartbeat thread, terminal
writes require the matching owner/token, and a stale worker cannot overwrite a
newer attempt. Startup recovers only `RUNNING` jobs with an empty or expired
lease; live leases are left alone, so multiple API processes may share a job
database. Cancellation and deadline checks run between stages, not inside a
single provider call. A test-only `AXIOMSCOPE_MOCK_STAGE_DELAY_SECONDS` (MOCK
only, max 10 s) makes browser cancel/resume tests deterministic.

Outcomes never conflate budget exhaustion with sufficiency: `SUFFICIENT`,
`BUDGET_EXHAUSTED`, `NO_PROGRESS`, `CONFLICT_UNRESOLVED`,
`NEEDS_HUMAN_REVIEW`, `CANCELLED`, `FAILED`.

Terminal writes are idempotent: `JobStore.finish_job` only updates a job whose
current status is not terminal (`api/jobs.py:364`), so a duplicate completion
or a late worker returns `False` and appends no second `job.completed`.
Per-job event appends are serialized under the store lock; tests cover restart
recovery, sequence continuity and 40 concurrent appends.

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
- Graph/questions projections require `options.deep_research=true`; legacy runs
  return `409 artifacts_unavailable`. Graph relations are limited to evidence,
  topic and source links; no supply-chain relation is inferred.
- The wizard's post-completion section reveal is presentation only. Report
  rendering is one-shot; there is no section-level streaming or real token
  accounting, and the UI does not pretend otherwise.
- The 400-node truncation test exercises projection shape/time on synthetic
  data. A Playwright test also renders a synthetic 400-node/800-edge projection
  in the browser (about 0.5 s first canvas); neither is a browser benchmark of
  a real 400-node investigation.
- A single authorized Live smoke on 2026-11-20 proved the real DeepSeek/Tavily
  adapters and the job/event/graph/report path, but accepted zero claims (239
  `NOT_COMPARABLE`) and retrieved off-region sources. Its discovery call hit
  the 768-token cap and the contract focus `竹产业` fell back to `特色农业`.
  This is an engineering smoke, not Live evaluation. See
  `docs/goal/LIVE_SMOKE.md`.
