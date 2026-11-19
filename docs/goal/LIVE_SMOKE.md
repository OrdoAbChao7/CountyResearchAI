# Live Smoke Record — 2026-11-20

Status: `PASS_ENGINEERING` / `NO_SUPPORTED_CLAIMS`

This is **one** explicitly authorized Live run. It proves that the real
FastAPI job path, DeepSeek client, Tavily provider, event stream, evidence
graph and report projections work together. It is **not** a Live evaluation,
does not replace MOCK tests, and does not satisfy M5.

- Cost gate: [LIVE_SMOKE_COST_GATE.md](LIVE_SMOKE_COST_GATE.md)
- Script: `scripts/run_live_smoke.py`
- Artifacts: `experiments/quality/live_smoke_20261120/`
- Job: `d367c9b277cf47d086d28f9824d661e5`
- Command:

```bash
PYTHONPATH=src python scripts/run_live_smoke.py \
  --env-file E:/Projects/CountyResearchAI/.env --confirm-paid
```

## Provider configuration finding

The root `.env` currently says:

```text
LLM_PROVIDER=gemini
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-3.1-flash-lite
```

but the configured `LLM_API_KEY` is a DeepSeek key: a free `GET
https://api.deepseek.com/models` returned HTTP 200 and listed `deepseek-flash`
and `deepseek-v4-pro`, while the same key against the Gemini endpoint returned
HTTP 400 `Please pass a valid API key`.

The smoke therefore used process-level overrides and did **not** change the
root `.env` or the main workspace:

```text
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-flash
SEARCH_PROVIDER=tavily
```

The `.env` mismatch should be fixed deliberately by the owner; otherwise the
normal API path (without the smoke overrides) will fail authentication.

## Observed result

| Item | Observed |
| --- | --- |
| Job status | `SUCCEEDED` |
| Mode label | `LIVE` |
| Outcome | `NO_PROGRESS` / `no_supported_claims` |
| Job elapsed | 30.6 s |
| Events | 28, including question tree, agents, synthesis, report |
| LLM calls | 2 (1 preflight, 1 discovery) |
| Prompt / completion tokens | 2,848 / 771 |
| Tavily basic searches | 7 (6 results each) |
| Sources persisted | 8 |
| Graph | 273 nodes / 1,869 edges, returned 273 nodes / 800 edges, truncated |
| Report sections | summary, verified-facts, disputes, gaps, sources, method |
| Verified / unverified claims | 0 / 239 `NOT_COMPARABLE` |
| Conflicts / gaps | 7 / 2 |
| Guard violations | 0 |
| Estimated cost | $0.00089 model; $0.056 if Tavily credits are paid; ≤ $0.0578 total |

The job succeeded, so the existing `JobRunner` terminal-state semantics were
not altered by the live data. The report was generated programmatically, the
graph projection returned, and the SSE event log was persisted.

## What the live run exposed

1. **Discovery focus fell back.** The contract asked for `竹产业`, but the
   persisted question tree and `stage.discover.completed` say `特色农业`. The
   discovery LLM call produced exactly 768 completion tokens (the smoke cap),
   so the JSON was likely truncated and the parser returned no selected focus;
   the handler then used its default. The cap was a smoke budget choice, not a
   production setting. A future run needs a larger discovery allowance.
2. **Retrieval relevance is poor.** Persisted sources include national
   statistics, Fujian statistics, Luoyang planning and a Hunan Lanshan bamboo
   plan. The source list is not region-locked to Anji. The query generator plus
   Tavily basic search did not keep the result set on-topic.
3. **The verifier rejected every claim.** All 239 structured claims are
   `NOT_COMPARABLE`, mostly because their period is outside the requested 2024
   window (2022, 2023, 2025, 2026); a few have no usable period. This is the
   time-window guard working, but it means the live run produced no verified
   fact.
4. **One period attribution looks suspicious.** The report lists
   “2024 年竹产业产值为 6.855 亿元” as `outside_requested_window:2026`. The
   claim text says 2024 but the verifier attributed 2026, probably from the
   source publication date. This needs a focused period-extraction test before
   the next Live run; do not call it a false rejection until the source span is
   inspected.
5. **Graph scale is real.** A single live query set produced 273 graph nodes
   and 1,869 edges, which is already above the 400/800 display budget after
   edge truncation. The synthetic 400-node browser test remains a valid
   performance fixture, not a substitute for a real-investigation benchmark.

## What this does and does not prove

Proved:

- DeepSeek `deepseek-flash` authentication, chat completion and token usage;
- Tavily basic search with the existing provider adapter;
- real job execution through the existing SQLite `JobStore`/`JobRunner`;
- fine-grained events, evidence persistence, graph projection and report
  projection on live data;
- the retry/call caps and cost gate were respected (no violations).

Not proved:

- Live research quality or supported-claim coverage;
- that explicit `research_focus` is honored (it was not, in this run);
- regional relevance of the retrieval layer;
- a Live evaluation, semantic Judge, 40–60 sealed tasks, or human adjudication;
- that a second run is authorized.

## Next actions (not executed)

1. Fix the root `.env` provider/model mismatch, or make the override explicit in
   a local launch profile.
2. Raise the discovery output allowance (for example 2,048 tokens) and decide
   whether an explicit contract focus should override auto-discovery.
3. Add a region-relevance filter or query constraint before the next Live run.
4. Inspect the `2024 → outside_requested_window:2026` claim against its source
   span and add a regression if the period parser is wrong.
5. Ask for a fresh authorization before a second paid run; then repeat the
   bounded smoke and compare.
