# AxiomScope — Interview Q&A

Each answer points at the code that backs it and states the trade-off. Numbers
are the ones measured in `docs/evaluation/FINAL_REPORT.md`; do not inflate them.

## 1. What problem does AxiomScope solve?

County industry research reports mix retrieved facts with model prose, and a
reader cannot tell which numbers are supported. AxiomScope separates structured,
verifiable findings from presentation: claims are extracted, linked to exact
quotes in immutable snapshots, deterministically checked, and only then rendered
into a brief. Code: `application/research.py`, `evidence/ledger.py`,
`evidence/graph.py`, `api/brief.py`.

Trade-off: conservative verification loses paraphrase recall; that is preferred
over false support.

## 2. Snapshot vs span vs claim vs finding?

- `SourceSnapshot`: immutable captured content with URL, hashes, timestamps.
- `EvidenceSpan`: exact quote plus offsets inside one snapshot.
- `Claim`: region/metric/value/unit/period/scope/caliber/version.
- `Finding`: a structured conclusion persisted before Markdown, carrying a
  verification status and a chain to claims/spans/snapshots.
Code: `evidence/graph.py` tables and `ClaimChain`/`VerifiedFinding` models.

## 3. How do you prove a citation is real?

`_check_span_integrity` recomputes the snapshot and span hashes, then requires
`content[start:end] == quote` for exact spans. A quote not found in the snapshot
is `quote_not_in_snapshot`; an offset mismatch is `offset_quote_mismatch`.
Both force `INSUFFICIENT` with `false_or_broken_reference`.
Tests: `tests/test_evidence_graph.py::test_false_offset_reference_is_rejected`.

Trade-off: exact matching rejects whitespace-normalized reposts unless the
extractor preserves the original bytes. That is intentional.

## 4. Why append-only snapshots and spans?

Re-running a pipeline must not silently rewrite the evidence used by an earlier
finding. `_insert_snapshot`/`_insert_span` raise on id collisions with different
hash/quote. Claims are updatable because verification status legitimately
changes; identity fields are stable.
Test: `test_append_only_snapshot_rejects_changed_content`.

Trade-off: storage grows; no retention policy yet.

## 5. NOT_COMPARABLE vs CONTRADICTED?

`classify_claim_relation` compares the full identity tuple. Different period,
scope, caliber, or incompatible unit → `NOT_COMPARABLE`; same identity but
different normalized value → `CONTRADICTS`. `NOT_COMPARABLE` is excluded from the
factual-error denominator, so a 2023 value is not scored as a false 2024 value.
Tests: `test_claim_relation_classification`.

## 6. Two supported sources disagree — what happens?

Both are evaluated with the same objective support test. If both pass,
`_supported_claim_conflicts` marks each `NEEDS_REVIEW`; the brief puts them in the
conflict section and does not pick a winner. A baseless contradiction does not
override a supported claim.
Tests: `test_two_supported_conflicting_claims_need_review`,
`test_baseless_contradiction_does_not_override_supported_claim`.

## 7. Why not mark a claim verified because the source is credible?

Credibility is not proposition support. The verifier never reads a reputation
score to decide status; it requires the quote to resolve and the value/unit to
appear. Source type is retained for reporting, not proof.

## 8. How is the date window enforced?

`ResearchContract.date_window` is validated (`start <= end`) and passed into
`EvidenceGraphStore.save_ledger(window=...)` → `verify_claim`, where
`_window_issue` marks out-of-window or undated claims `NOT_COMPARABLE`. This was
added after a live smoke showed a 2027 planning target being falsely supported in
a 2024 run. Code: `domain/research_contracts.py`, `evidence/graph.py`.

## 9. What if offsets are unknown?

`offset_status` is explicit. If offsets are absent, the verifier accepts an exact
substring match but records `quote_substring_unknown_offset`; it never fabricates
offsets. The source contract keeps unknown as unknown.

## 10. Why SQLite, and when would you move to Postgres?

SQLite is stdlib, offline, Windows-friendly, and enough for single-node research.
Tables are explicit columns (no ORM), so a Postgres migration is mechanical.
Move when: multi-writer concurrency, remote workers, or corpora that exceed
single-file backup/maintenance needs. ADR: `docs/architecture/ADR-001-...`.

## 11. What happens if the process crashes mid-job?

Jobs and events are durable in SQLite. Startup `recover_interrupted()` marks
`RUNNING` jobs `INTERRUPTED` with `process_restarted`; `POST /resume` explicitly
re-queues. It does not auto-resume to avoid surprise provider spend and duplicate
side effects. Code: `api/jobs.py`, `api/app.py` lifespan.
Tests: `test_recover_interrupted_marks_running_jobs`,
`test_resume_requeues_and_resubmits`.

Trade-off: explicit resume is less convenient but more honest.

## 12. How does cancellation work, and what is the limitation?

`POST /cancel` sets `cancel_requested`; `JobRunner._ensure_active` checks it
between stages and raises `_Cancelled`, producing `CANCELLED`. A single long
provider call cannot be interrupted mid-flight. Documented in ADR-003.
Test: `test_cancel_requested_before_execution_stops_job`.

## 13. Which budget caps are actually enforced?

Enforced on the workflow path: `deadline_seconds` (between stages),
`max_documents` (search result cap), `max_tokens` (LLM client setting for live
mode). Not enforced: `max_steps`, `max_search_calls`, `max_cost` — there is no
pricing table or call counter in the legacy collector. The API reports
`not_enforced_on_workflow_path` in every task result instead of pretending.
Code: `api/worker.py::_budget_enforcement`.

## 14. How do you prevent "timeout = success"?

Outcomes are a disjoint enum: `SUFFICIENT`, `BUDGET_EXHAUSTED`, `NO_PROGRESS`,
`CONFLICT_UNRESOLVED`, `NEEDS_HUMAN_REVIEW`, `CANCELLED`, `FAILED`. A deadline
breach maps to `BUDGET_EXHAUSTED`; it cannot fall through to `SUFFICIENT`.
Test: `test_deadline_exhaustion_is_not_reported_as_sufficient`.

## 15. API security posture?

- No endpoint fetches a user-supplied URL, so no SSRF surface.
- IDs are regex-validated; report paths must resolve inside the reports root.
- Generic 500 responses; no stack traces or keys.
- CORS restricted to local dev origins by default.
- Live provider calls are opt-in (`AXIOMSCOPE_API_LIVE=true`); default is MOCK.
Code: `api/app.py`.

Trade-off: no authentication yet; it is a localhost demo. Do not expose it
publicly without auth, rate limiting, and a real queue.

## 16. Why SSE rather than WebSocket?

Events are server→client only. SSE works over HTTP, reconnects natively with
`Last-Event-ID`, and needs no protocol upgrade. The client also polls as a
fallback, so a missed frame cannot leave stale UI. Code: `_event_stream`,
`web/src/App.tsx`.
Trade-off: SSE is one-way; cancellation uses a POST.

## 17. How did you evaluate it?

Pre-registered design (`docs/evaluation/DESIGN.md`): A lexical, B legacy web AI,
C legacy pipeline, D full v2; paired tasks, fixed budgets, numerators and
denominators, negative controls, offline replay first, live only with a cost
gate. The executed offline report covers A/B/C only: 48 runs, 240 observations,
0 provider calls. C trails A/B; D and live are marked NOT_MEASURED /
BLOCKED_EXTERNAL.

## 18. Why keep a negative result?

Because the goal is truth, not a green dashboard. The frozen sample shows C at
3.3% GT recall vs A 16% and B 12.2%, with C consuming ~22.7k LLM units/run.
Reporting that prevents shipping a false superiority claim and tells us where to
invest next (retrieval and extraction, not more prose).

## 19. Biggest weaknesses?

1. No locked 40–60 task holdout, no D measurement, no ablations.
2. Verification is lexical/exact; paraphrases and metric aliases are lost.
3. Budget caps are only partially enforced on the legacy path.
4. Single-process worker; no auth; no distributed queue.
5. Frontend has no automated browser E2E or screenshots.
Next steps are listed in `docs/evaluation/FINAL_REPORT.md`.

## 20. Scaling to 1,000 concurrent jobs?

Replace the in-process executor with a durable queue (Celery/RQ/Arq) while
keeping the `JobStore` state machine; move from SQLite to Postgres; add per-tenant
auth, quotas, and rate limits; make provider calls idempotent with request keys;
partition evidence storage; and add worker heartbeats plus lease expiry. The
`JobRunner`/`JobStore` seam is designed for this replacement, not for pretending
SQLite is a cluster.
