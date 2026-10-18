# Project status and engineering notes

This document records the boundary between what this repository is intended to demonstrate, what has been verified in the repository, and what still needs evidence. It is deliberately more specific than a feature list.

## Current stage

**Deep Research Multi-Agent Architecture (Refactored Prototype)**

## Why this exists

I built this to make the first pass of county-level industry desk research reproducible: collect public material, preserve evidence links, and turn the material into a reviewable, traceable Markdown research report.

The architecture was upgraded from a linear single-pass retrieval pipeline to a deep, evidence-driven multi-agent research loop inspired by BettaFish and modern agentic research practices.

## Core Capabilities Added in Refactoring

1. **Dynamic Question Tree & Intent Planning**:
   - `QueryEngine` constructs mode-specific inquiry trees (formation, statistics, enterprise/chain, policy, bottlenecks, outlook).
   - Dynamic search query generation covering official gazettes, statistical yearbooks, and sector policies.
   - Administrative disambiguation (`disambiguate_region`) for counties, county-level cities, and prefecture-level cities.

2. **Reflection & Gap-Driven Supplemental Search**:
   - `ResearchCritic` evaluates initial evidence coverage against the question tree.
   - Generates targeted supplemental queries to close coverage, metric, or temporal gaps.

3. **Structured Evidence Store & Fact Verification**:
   - `EvidenceStore` ingests raw documents, extracts fine-grained numerical, policy, and historical claims with `(num, unit, indicator, period, scope)` attribution.
   - Detects metric conflicts and scope divergences across years and administrative boundaries.
   - `FactVerifier` performs bidirectional Claim → Evidence → Source checks with strict confidence thresholds to prevent LLM hallucinations.

4. **Specialized Multi-Agent Synthesis Matrix**:
   - `EconomicResearchAgent`, `PolicyResearchAgent`, `IndustryResearchAgent`, and `ResearchSynthesizer` collaborate under `DeepResearchCoordinator`.
   - Appends verifiable audit logs and conflict investigation records to every generated report.

5. **Objective Benchmark Suite**:
   - Covers Case A (Anji Bamboo), Case B (Xinfeng Navel Orange), Case C (Hegang Industrial Transition).
   - Metrics include Precision@K, Recall@K, Official Source Ratio, Evidence Support Rate, and Conflict Detection.

## Scope and known limitations

The generated report is an in-depth research draft, not an official policy determination.
- Public search coverage depends on the availability of indexed local government and statistical resources.
- In offline/mock test environments, deterministic golden datasets are used to evaluate retrieval recall and verification logic.
- When running in an environment without LLM API keys, the system safely falls back to rule-based heuristic analysis.

## Verification Record

- **Test Suite**: `451 passed` in the final full-suite run; pytest cache has a Windows permission warning.
- **Static Analysis**: the changed/new experiment files pass scoped `ruff check`; full-tree lint remains non-clean because legacy `scripts/_verify_*.py` files contain 73 pre-existing findings.
- **Resource safety regression**: settlement `overrun` usage is now included in subsequent capacity checks, so a run that exceeds its limit cannot reserve more work from the same persisted budget; covered by `test_overrun_usage_blocks_later_reservations`.
- **Historical Offline Benchmark** (not evidence for real efficacy):
  - Case A (Anji): Recall@K improved from 40% to 100%, evidence support rate at 100%.
  - Case B (Xinfeng): Recall@K improved from 20% to 100%, successfully detected 1 scope divergence.
  - Case C (Hegang): Recall@K improved from 20% to 80%, core facts 4/4 covered.

## Independent real comparison status

The real-provider comparison is complete for the minimum one-repeat target: corrected E1 has 18/18 VALID runs across six new regions, and corrected E2 has 18/18 VALID runs across six frozen input packs. The old 512-token and diagnostic batches remain preserved but are excluded because DeepSeek could return empty final content when reasoning consumed the output budget. The corrected batches use 2048 output tokens and DeepSeek thinking disabled, with empty-report rejection at the experiment boundary. Post-run candidate collection is prefix-scoped and requires `formal_target: true`, preventing historical development and invalid batches from entering final judging or QA.

The E2 fixed-input path includes deterministic document-pack hashing, strict no-search execution for all groups, and a real-resource path for C. Formal E1/E2 runners verify the frozen Ground Truth manifest before creating a batch or initializing business resources, and persist configuration-bound checkpoints for safe `--resume`. Claim verification, anonymous Judge batches, Report-Based QA, run-level summary/paired-difference statistics, SVG figures, and corrected-batch audits are now generated. Each final E1/E2 Judge batch has 17/18 valid candidates; failed candidates remain recorded and are not imputed.

The Ground Truth process now has six independent public-source verification logs. A six-claim, six-region minimum Ground Truth passes the two-source/two-context freeze validator, with version-scoped claims for 德清县 and 攀枝花市 and an amount-only claim for 长汀县; unresolved claims remain preserved in the verification matrix. The three-claim partial panel and four-claim industry supplemental panel remain historical non-formal panels. Formal QA and claim scoring now verify the frozen Ground Truth manifest `source_hash` before loading claims. Six bounded-excerpt E2 packs are referenced by a frozen formal manifest and have been consumed by the corrected E2 API batches.

The frozen E1 task schedule explicitly covers `snapshot`, `rise-fall`, and `long-history`; all six regions were executed once per group in the corrected batch. The final report concludes `NO_OVERALL_ADVANTAGE`, with a limited E2 report-QA advantage for C at higher token cost.

DeepSeek can now be selected by the normal search provider factory and by A/B baseline construction. `DEEPSEEK_API_KEY` is accepted as the provider-specific LLM/Search key, the LLM defaults to `https://api.deepseek.com/v1`, and formal calls use the user-authorized paid boundary with `DEEPSEEK_SEARCH_ENABLED=true`. The OpenAI-compatible client disables DeepSeek thinking by default unless a caller explicitly supplies another `extra_body` value, preventing empty report content under bounded output budgets.

The post-run scoring path now separates blind holistic judging, report-based QA, and Ground Truth claim verification. Claim verification writes declaration-level metrics observations while retaining verifier resource usage separately from the A/B/C research resource ledger.

The deterministic independent auditor passed the corrected E1 root and all six corrected E2 roots with no issues. Historical development/probe audit findings remain in `reports/AUDIT_REPORT.json`; they are not conflated with the corrected formal-batch audit.
