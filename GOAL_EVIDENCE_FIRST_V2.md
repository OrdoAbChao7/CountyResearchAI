# CountyResearchAI Evidence-First v2 Goal

状态：`ENGINEERING_COMPLETE_RESEARCH_PENDING`

本文件是现有 `GOAL.md`（上一轮真实效能验证 Goal）的独立续作管理文件，不覆盖旧 Goal 历史。完整目标原文保留在用户提供的粘贴文件：

`D:\Dev\.codex\attachments\67fda3ad-b9ca-44e3-938c-aaa4b66716ea\pasted-text-1.txt`

## Objective

将 CountyResearchAI 从多阶段文档处理和 LLM 报告生成系统升级为结构化、可追溯、可验证、预算感知的县域产业研究引擎。优先级固定为：证据保真 > 证据选择 > 事实准确性 > 自适应检索 > 分析深度 > 性能优化 > 新 Agent 功能。

## Fixed baseline and development boundary

- Legacy comparison baseline: `52a6ed0f5164721cece221ffb9e7f67f73ac3dd7` on `codex/experiment-superiority`.
- Candidate hotfix audited from `origin/fix/evidence-preservation-20261019` at `b32470a40c1a042a8d386d15c248fb5e765bc60c`.
- Development branch: `codex/evidence-first-v2`.
- No existing experiment artifacts may be overwritten or deleted.
- No new paid Provider call is allowed without a fresh explicit cost gate.

## Phase ledger

| Phase | Objective | Status | Evidence |
| --- | --- | --- | --- |
| 0 | Baseline freeze, corpus inventory, reproducible loss audit | COMPLETE | `ARCHITECTURE_BASELINE_AUDIT.md`, `tests/test_evidence_preservation_regression.py` |
| 1 | Evidence preservation and unified Source Contract | COMPLETE | `PHASE1_EVIDENCE_PRESERVATION_REPORT.md`, `src/county_research_ai/evidence/source_contract.py`, `PHASE3_EVIDENCE_ARCHITECTURE.md` |
| 2 | Claim classification and independent metrics | COMPLETE | `PHASE2_EVALUATION_AUDIT.md`, `experiments/independent_comparison/claim_scores/continuation_matched_budget_deepseek_flash_20261019_v4_offline/` |
| 3 | Structured Evidence Ledger and contracts | COMPLETE | `PHASE3_EVIDENCE_ARCHITECTURE.md`, `src/county_research_ai/domain/research_contracts.py`, `src/county_research_ai/evidence/ledger.py` |
| 4 | QuestionSlot-driven adaptive retrieval | ENGINEERING_COMPLETE / REPLAY_INCONCLUSIVE | `PHASE4_ADAPTIVE_RETRIEVAL_REPORT.md` |
| 5 | Evidence-bound analysis and verification | ENGINEERING_COMPLETE / DETERMINISTIC_LIMITS | `PHASE5_EVIDENCE_BOUND_SYNTHESIS_REPORT.md` |
| 6 | Efficiency, architecture versions, long-history routing | ENGINEERING_COMPLETE / TOKEN_EFFECT_PENDING | `PHASE6_EFFICIENCY_OPTIMIZATION_REPORT.md` |
| 7 | Offline replay and authorized independent comparison | OFFLINE_REPLAY_PARTIAL / RESEARCH_ACCEPTANCE_NOT_MET | `PHASE7_EXPERIMENTAL_EVALUATION.md` |
| 8 | Final engineering/research acceptance | ENGINEERING_COMPLETE / RESEARCH_PENDING | `experiments/independent_comparison/reports/REFACTOR_FINAL_REPORT.md` |

## Phase 0 known facts

- Current candidate full test baseline: `pytest --no-cov -q` → `494 passed`, one Windows `.pytest_cache` permission warning.
- Full `ruff check src tests scripts` → 77 findings; most are historical verification scripts. Candidate-specific findings are recorded in `ARCHITECTURE_BASELINE_AUDIT.md`.
- Saved Deqing snapshot raw and processed artifacts contain `722.5亿元`, `300.6亿元`, `5.8%`, and `7.7%`; old formal C archives can contain only report metadata, so source-based scoring loses the actual evidence.
- Candidate hotfix has three focused regression tests and changes processor cleaning, long-text evidence segmentation, bounded context distribution, and C source persistence. The initial Source Contract serializer now covers new experiment writers, but the full Source Contract, truncation audit trail, and structured claim/version semantics required by this Goal remain unfinished.

## Phase 1 progress

- The real Deqing C replay now retains all four required values through RawDoc → ProcessedData → EvidenceStore → bounded LLM context, and the new serializer produces 2 source documents with 24 deterministic chunks.
- `RawDoc` records content length/truncation state; `ProcessedData` records context budget allocations, included/truncated/excluded documents, and exclusion reasons.
- The national GDP negative case is covered: national GDP is `全国范围`, while Deqing GDP is `县域本级`.
- Validation: `pytest --no-cov -q` → `502 passed` with one Windows `.pytest_cache` permission warning; scoped Ruff for changed files is clean.
- Phase 1 acceptance is complete: the deterministic Source Contract remains the archival JSON boundary, while Phase 3 adds the canonical Pydantic contracts and Ledger adapter without rewriting historical artifacts.

## Phase 2 progress

- Claim identity is compared on `(region, metric, period, administrative_scope, unit, version)`; `NON_COMPARABLE` is separate from `CONTRADICTED` and excluded from factual-error denominators.
- Twelve negative classification cases cover year, region, metric, unit, caliber, version, scope, wrong value, URL-only support, missing mention, disputed source, and percentage value mismatch.
- The frozen continuation corpus was rescored offline into `continuation_matched_budget_deepseek_flash_20261019_v4_offline`: 48 runs, 240 claim observations, 28 classification changes, 0 Provider calls, and 0 semantic Judge calls.
- Phase 2 acceptance is limited to deterministic/offline evaluation. It does not claim improved model quality or authorize a new real Provider experiment.

## Phase 3 progress

- Canonical Pydantic contracts now cover `ResearchSpec`, `SourceDocument`, `EvidenceChunk`, `AtomicClaim`, `QuestionSlot`, and `EvidencePack`; unknown offsets remain explicit.
- `EvidenceLedger` preserves source/chunk/claim relations, detects same-source reposts, selects EvidencePack content under budget, rejects evidence-free `verified`, and normalizes supported 亿元/万元 values for equivalence checks.
- The legacy application attaches the Ledger and EvidencePack on both cache-hit and fresh-processing paths. LLM context rendering and all three legacy report modes consume the selected pack and expose missing requirements/source mapping.
- Phase 3 focused validation: 18 tests passed with one Windows `.pytest_cache` permission warning; full suite is 527 passed; changed-file Ruff is clean. No Provider calls were made.

## Phase 4 progress

- Adaptive slot-based plans, explainable local/period/metric/reliability/novelty ranking, gap-linked follow-ups, budget and marginal-evidence stop conditions are connected to `DeepResearchCoordinator`; legacy Collector fallback remains intact.
- The result now exposes ResearchSpec, EvidencePacks, stop reason and observed Collector output counts. The Fetch budget records actual observed document counts instead of clipping over-budget usage.
- Offline archived replay (6 RawDocs across 3 modes) yielded top-3 required-metric recall of snapshot 19.44% vs 19.44%, rise-fall 21.67% vs 21.67%, and long-history 41.67% vs 41.67% for legacy vs slot-aware ranking. This isolates ranking only, uses extremely small samples, and shows no measured lift.
- Validation: focused adaptive/deep-research tests 13 passed; full suite 532 passed with one Windows `.pytest_cache` permission warning; changed-scope Ruff clean. No Provider/Judge calls.
- Engineering gate passes; research-effectiveness gate remains inconclusive and is explicitly not claimed as a gain. See `PHASE4_ADAPTIVE_RETRIEVAL_REPORT.md` and offline runner `scripts/evaluate_adaptive_retrieval_offline.py`.

## Phase 5 progress

- Evidence-bound verification is connected to the deep synthesizer and all three mode renderers. It checks region, metric/alias, exact value and unit, nearest preceding year, declared statistical caliber/series version, linked original chunk, canonical source URL, and recorded source credibility; numeric citations include original text and are idempotent.
- Non-numeric material statements are supported only by exact Claim → Chunk → Source mapping; unmapped statements are tagged, and gaps/recommendations receive explicit labels. Empty-evidence specialized analysis no longer emits generic factual claims or a fabricated positive executive summary.
- Validation: full suite 546 passed, 1 Windows `.pytest_cache` permission warning; changed-scope Ruff clean. No Provider/Judge calls.
- This deterministic verifier is conservative and not semantic entailment proof. Missing source quality or uncertain paraphrases remain unverified; no quality lift is claimed. Details: `PHASE5_EVIDENCE_BOUND_SYNTHESIS_REPORT.md`.

## Phase 6 progress

- Experiment manifests persist architecture version and reject new runs with an unspecified version; prior artifacts remain untouched.
- Architecture contracts normalize and validate the supported versions (`workflow_legacy`, `deep_legacy`, `evidence_first_v2`); experiment A/B/C specs are tagged as traditional-search baseline, general-AI baseline, and Evidence-First v2 respectively. Unknown experiment architecture labels are invalid.
- Long-history now builds six source-traced, year-aware period EvidencePacks from sentence children and exposes their IDs/URLs/gaps in the report audit appendix. Parsed extracted HistoricalPeriod windows now narrow task evidence routing, with fallback to the predefined period when extraction is absent/unparseable/non-overlapping; explicit task years boost matching passages. The rerun across three archives retained 2020 and 30/31 legacy-visible configured terms; 2000 remains outside the contemporary period boundary. First-seven-prompt characters are 52,215 vs 185,103 legacy (-71.8% weighted); this is not gold-evidence recall or provider token measurement, so no quality/token gain is claimed.
- Existing matched-budget long-history sample: 52,561 LLM tokens, 136.231s elapsed against a 120s cap (`BUDGET_EXHAUSTED`). No per-prompt token trace exists to support an old/new token comparison.
- Replaced hard-coded synthetic token usage in deterministic report synthesis with 0 actual LLM tokens.
- Validation before final review fixes: full suite 569 passed; dynamic-period routing, interrupted-checkpoint resume, and mode-level checkpoint option propagation tests pass; changed-file Ruff passes; full repository Ruff still reports 75 findings across existing/other-scope files; no Provider/Judge calls. Actual Usage comparison remains pending. See `PHASE6_EFFICIENCY_OPTIMIZATION_REPORT.md` and `scripts/evaluate_long_history_efficiency_offline.py`.

- Final defect review found ASCII decimal splitting in derived period chunks; fixed with a regression for decimal integrity and source offsets. Full suite is now 570 passed. The exact frozen excerpt retention replay is documented in Phase 7; it does not change the evidence that actual token comparison is pending.

## Phase 7 progress

- Frozen matched-budget corpus was rescored into a new v5 replay directory (48 valid runs / 240 observations / 0 Provider calls); compared against v4 by `(run_id, claim_id)`, all statuses, error types, and metrics match (0 differences). v4 remains unchanged.
- Reconfirmed the existing negative result: current valid C-group quality metrics trail the baselines and its observed LLM units/search/time are higher; six C long-history runs exceeded the 120s budget. This is small-sample evidence, not a statistical-significance claim.
- Adaptive ranking replay remains only 6 RawDocs with no measured top-3 recall lift; long-history prompt replay counts characters only. No complete module ablation or independent semantic judging has been performed; research acceptance remains unmet.
- Details and exact artifact paths: `PHASE7_EXPERIMENTAL_EVALUATION.md`.

- Frozen raw-input exact excerpt retention: 17/60 at RawDoc, ProcessedData, and period Ledger stages; 13/60 in both 6k/18k EvidencePacks. Four ledger-present excerpts are excluded as `period_only_fallback` because current metric-term matching does not recognize the frozen metric label; the 43 remaining excerpts are not exact matches in the available RawDocs.

## Phase 8 acceptance

- Engineering acceptance is complete for the scoped implementation and current deterministic checks: after correcting six review findings and two related decimal/empty-pack edge cases, full test suite 578 passed, changed-path Ruff passed, and diff whitespace checks passed. Public CLI and legacy models remain available through existing compatibility paths; no historical experiment data was overwritten.
- Added architecture and migration guides plus a final report. Research acceptance remains pending because quality metrics on the observed C sample trail baselines, retrieval replay is small and tied, long-history token/cost improvement is unmeasured, and no independent semantic Judge or complete ablation was run.
- No new Provider/Judge calls, commits, or merges were made. Continue only with offline metric-alias coverage work until a fresh real-provider cost gate is explicitly authorized.

## Milestone gate rule

每个 Phase 必须完成：`Implementation → Tests → Evidence → Acceptance`。未通过的阶段不得标记 Completed；历史实验结果、负面结果和资源失败必须保留。

## Working plan

详细任务、文件边界、接口和测试要求见 [`docs/superpowers/plans/2026-10-19-evidence-first-v2.md`](docs/superpowers/plans/2026-10-19-evidence-first-v2.md)。

