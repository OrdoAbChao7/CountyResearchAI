# Evidence-First v2 Final Engineering Report

Date: 2026-10-19  
Disposition: `ENGINEERING_COMPLETE_RESEARCH_PENDING`

## Outcome

The implementation establishes an inspectable evidence pipeline integrated with existing research paths, mode-specific adaptive retrieval, evidence-bound deterministic checks, long-history period packs, opt-in task checkpoints, and offline evaluation records. A fresh review identified six important correctness issues; all six were fixed with regression coverage, along with decimal fallback splitting and empty-pack fallback edge cases. The final full suite passed **578 tests**. Scoped Ruff checks for all changed implementation and test files passed. `git diff --check` reported no whitespace errors; Git emitted only line-ending normalization warnings.

No new Provider or Judge calls were made. Historical experiment artifacts were preserved. No merge or commit was performed.

## Acceptance

| Area | Result | Evidence / remaining limit |
| --- | --- | --- |
| Evidence preservation and source contracts | Engineering pass | `PHASE1_EVIDENCE_PRESERVATION_REPORT.md`; regression corpus retains four Deqing values and source URLs. |
| Evaluation and claims | Offline engineering pass | Phase 2 rescoring and versioned outputs; deterministic classifications are not semantic judgment. |
| Evidence Ledger and contracts | Engineering pass | `PHASE3_EVIDENCE_ARCHITECTURE.md`; source/chunk/claim linkage and EvidencePack contracts. |
| Adaptive retrieval | Inconclusive | Six RawDocs; top-3 recall tied across modes. |
| Evidence-bound synthesis | Engineering pass with conservative limits | Exact/structured linkage; paraphrase entailment and source credibility remain limited. |
| Long-history efficiency | Partial | Prompt characters 185,103→52,215 on three archives (-71.8% weighted); actual new-vs-old token usage and quality not measured. |
| Frozen evidence retention | Negative diagnostic | 17/60 exact excerpts in RawDocs, rendered context and period Ledger; 13/60 selected into both 6k and 18k EvidencePacks. Four ledger hits were excluded as `period_only_fallback` because current metric-term matching did not recognize the frozen metric label; 43 excerpts were not exact matches in available RawDocs. |
| Independent research quality | Not accepted | Current valid matched-budget C metrics trail A/B on the observed sample; six C long-history runs exceeded the 120-second cap. Sample size is insufficient for broad or significant claims. |
| Full independent semantic Judge / ablation | Not run | No Judge calls or complete module ablation. |
| Cost/usage comparison | Not accepted | Archived data lacks per-call prompts/tokens for comparable long-history replay; character counts do not establish token/cost reduction. |

## Defect fixed in final replay

Period-ledger sentence splitting previously treated an ASCII decimal point as a sentence boundary, potentially separating values such as `300.6`. `_sentence_spans` now preserves a period between digits as part of the same passage. The regression verifies both decimal fact integrity and exact source offsets. On the matched frozen excerpt replay this did not change the aggregate 17/60 exact-retention count; it prevents corruption in the derived period chunks.

## Review findings fixed

- Collector no longer deducts already-reserved adaptive queries a second time; invalid architecture versions terminate before invoking the executor.
- Numeric evidence matching now binds each number to the nearest recognized metric and rejects incompatible broad administrative scopes. Numeric Markdown tables and bold/link-wrapped factual statements are audited rather than skipped.
- Period-derived Ledgers remap claims only to matching derived passages; fallback sentence splitting shares the decimal-safe scanner.
- EvidencePack rendering now fits complete evidence when possible, records per-chunk `budget_truncated`/`budget_exceeded` outcomes, and does not fall back to unselected RawDocs when a pack is empty.

## Decision and next evidence

Engineering delivery is complete for the scoped Evidence-First v2 implementation, but research acceptance is pending. The immediate measurable improvement opportunity is metric alias/requirement matching in EvidencePack selection, followed by a frozen offline replay that reports exact and semantic evidence coverage separately. Further efficiency claims require per-call token and latency traces. Any new real-provider experiment remains subject to a fresh explicit cost/resource gate.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m pytest --no-cov -q
.\.venv\Scripts\ruff.exe check src/county_research_ai/llm/long_history_analyzer.py tests/test_long_history_context.py
git diff --check
```

Offline evaluation details and source limitations are recorded in [Phase 7](../../../PHASE7_EXPERIMENTAL_EVALUATION.md). The architecture and migration notes are in [`docs/architecture/EVIDENCE_FIRST_V2.md`](../../../docs/architecture/EVIDENCE_FIRST_V2.md) and [`docs/architecture/MIGRATION_GUIDE.md`](../../../docs/architecture/MIGRATION_GUIDE.md).
