# AxiomScope Evaluation Design (pre-registered)

Status: design fixed 2026-10-26. This document is written **before** any new
measurement. It defines what would count as evidence and what must remain
unclaimed.

## Research questions

1. RQ1 — Does the full Evidence-First v2 pipeline retrieve and support more
   correct regional-industry facts than a lexical baseline and the legacy
   pipeline at comparable budgets?
2. RQ2 — Does claim-level verification reduce unsupported statements without
   hiding correct ones (precision/abstention trade-off)?
3. RQ3 — Do temporal and caliber checks correctly separate `NOT_COMPARABLE` from
   `CONTRADICTED`?
4. RQ4 — What are the latency, token, and cost differences per finished outcome?

## Strategies

| ID | Strategy | Implementation |
| --- | --- | --- |
| A | Lexical/direct search + single LLM synthesis | `search/lexical.py` BM25 over snapshots + one synthesis call |
| B | Preserved CountyResearchAI legacy pipeline | `codex/experiment-superiority` behavior |
| C | Adaptive research without the temporal graph/semantic verifier | adaptive retrieval + legacy synthesis |
| D | Full AxiomScope v2 | adaptive retrieval + temporal graph + deterministic verification + findings/brief |

All four must use the same model, time, and search quotas per paired case.

## Task set

Target: 40–60 real regional/industry tasks, split across:

- single-fact retrieval (point value + unit);
- cross-source corroboration/contradiction;
- temporal or statistical-caliber discrepancy;
- unavailable evidence (must abstain);
- multi-hop (value → derived comparison).

Each task needs: region, mode, question, date window, acceptable evidence set
(source URLs + exact quotes when available), expected claims, category, and
reviewer notes. Version the manifest and hash it. A smaller pilot is allowed
only with the exact reason recorded; the pilot is not described as
comprehensive.

Current corpus: the inherited frozen matched-budget set (48 runs / 240 claim
observations across 6 regions and 3 modes). It was **not** re-curated for this
design and is not a locked 40–60 task holdout. It can support RQ4 and a limited
RQ1 sanity check, not a full RQ1/RQ2 answer.

## Measurements

Report numerators and denominators, never only percentages:

- retrieval: `Recall@K` against expected evidence URLs/quotes; lexical baseline
  fingerprint recorded.
- citations: support precision = supported report claims / verifiable report
  claims.
- claim verification: supported/contradicted/insufficient/not-comparable counts;
  `NOT_COMPARABLE` precision on the temporal subset.
- abstention: correct abstentions / tasks with unavailable evidence.
- end-to-end: task-level rubric scored 0–2 by two independent reviewers, with a
  documented adjudication for disagreements.
- operations: p50/p95 latency, LLM units, search calls, retries, failures,
  recovery count.

Negative controls are mandatory: an unrelated query must return no evidence; a
changed metric term must change ranking; a tampered quote offset must be
rejected; a claim outside the date window must not be `SUPPORTED`.

## Pairing and ablations

- Pair A/B/C/D on identical task keys; report wins/ties/losses and paired deltas.
- Ablations: no graph, no deterministic verifier, no gap research, BM25-only vs
  adaptive, single-agent vs multi-agent.
- Fix random seeds and record provider/model versions.
- Use paired bootstrap confidence intervals; with the current n, report them as
  indicative only, never as proof.

## Leakage and honesty controls

- Lock the independent test set before any tuning; do not inspect holdout
  solutions during development.
- Offline replay isolates system quality from web churn; live runs are reported
  separately and marked `BLOCKED_EXTERNAL` when credentials/quota are absent.
- Fixtures and mocks are never described as live sources.
- No new paid Provider or Judge call without an explicit cost gate.
- If D underperforms, report it, investigate, tune on dev only, then run one
  locked evaluation. Never redefine the metric after seeing results.

## Artifact layout

```text
evaluation/results/<run-id>/
  manifest.json          # dataset hashes, configs, seeds, provider versions
  per_case.jsonl         # one row per task/strategy with metrics and traces
  ratings.csv            # human/rubric ratings and adjudication
  summary.json           # numerators, denominators, intervals
  summary.md             # human-readable report
  failure_taxonomy.md
```

## Current status

| Element | Status |
| --- | --- |
| Design fixed | PASS (this document) |
| Offline A/B/C aggregation on frozen corpus | PASS, `experiments/evaluation/20261026_multi_baseline_offline/` |
| Verifier ablation on C raw archives | PASS, `experiments/evaluation/20261026_verifier_ablation/` |
| D measured on the same corpus | NOT_RUN |
| 40–60 independent locked tasks | NOT_RUN |
| Live end-to-end evaluation | BLOCKED_EXTERNAL |
| Remaining ablations (no graph, no gap research, BM25 vs adaptive, agent count) | NOT_RUN |
| Independent semantic Judge | NOT_RUN |
| Human rubric/adjudication | NOT_RUN |
