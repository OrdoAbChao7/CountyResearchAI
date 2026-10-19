# Evidence-First v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 CountyResearchAI 升级为结构化、可追溯、可验证、预算感知的 Evidence-First 县域研究引擎，并用离线回放和真实产物证明改进是否有效。

**Architecture:** 保留旧 `RawDoc`、`ProcessedData`、CLI 和 legacy workflow，通过 adapter 接入新的 Research Contract、Evidence Ledger 和 EvidencePack。先修复证据保真与评价链路，再接入任务驱动检索、证据绑定分析和 long-history 分段调度；每个阶段以真实回放产物和确定性测试作为 gate。

**Tech Stack:** Python 3.10+, Pydantic v2, pytest, Ruff, existing OpenAI-compatible providers, JSON/JSONL/SQLite experiment artifacts.

**Spec:** `GOAL_EVIDENCE_FIRST_V2.md` and the user-provided Evidence-First v2 goal at `D:\Dev\.codex\attachments\67fda3ad-b9ca-44e3-938c-aaa4b66716ea\pasted-text-1.txt`.

## Global Constraints

- 保留 `52a6ed0` 旧实验基线，不覆盖或删除已有实验产物。
- 在 `codex/evidence-first-v2` 分支上开发；不把未验证修改合并到默认分支。
- 旧 CLI、旧研究模式和 legacy workflow 继续可运行。
- 每个缺陷先有可复现失败测试，再实现最小修复。
- 不使用 Mock 数据进入真实实验统计，不硬编码真实 Usage，不重新调用付费 Provider 直到费用边界明确。
- 研究结论必须区分工程验证、离线回放和真实独立实验；负面结果保留。

## Review Focus

- 单行超长统计公报仍应保留指标、数字和单位的关系；由 Phase 1 长文本回放测试覆盖。
- 全国背景文档不能挤掉后续县级文档；由 `ProcessedData` / `EvidencePack` 预算测试覆盖。
- 同值不同指标、不同地区、不同年份和不同统计口径不能互相支持；由 Phase 2/3 Claim 测试覆盖。
- C 组来源归档必须具有 A/B 同样的来源和 chunk 映射；由 Source Contract round-trip 测试覆盖。
- 预算耗尽、截断、缺来源和未知 Usage 必须成为可见状态而不是静默成功；由资源与端到端回放测试覆盖。

---

### Task 0: Phase 0 baseline freeze and audit

**Files:**
- Create: `GOAL_EVIDENCE_FIRST_V2.md`
- Create: `ARCHITECTURE_BASELINE_AUDIT.md`
- Create: `docs/superpowers/plans/2026-10-19-evidence-first-v2.md`
- Create: `experiments/independent_comparison/reports/REFACTOR_AUDIT.md`
- Test: existing `tests/` suite and a deterministic Deqing replay test

**Interfaces:**
- Consumes: baseline commit `52a6ed0`, candidate commit `b32470a`, saved Deqing raw/processed/report/source artifacts.
- Produces: branch/commit ledger, reproducible failure location, preserved regression corpus manifest, and phase gate status.

- [x] Record current branch, commit, dirty state, candidate ref, Python/dependency versions, test command, Ruff scope, and artifact inventory.
- [x] Add a failing replay assertion that identifies the first stage where each Deqing fact disappears or loses source linkage.
- [x] Run the replay on the saved raw and processed files; record RawDoc → ProcessedData → EvidenceStore → context → report/score counts.
- [x] Write `ARCHITECTURE_BASELINE_AUDIT.md` with root cause evidence, candidate-patch review, known limitations, and exact commands/results.
- [x] Run `pytest --no-cov -q` and scoped/full Ruff; preserve historical failures separately from new failures.
- [x] Mark Phase 0 only when the replay, baseline SHA, branch, corpus, test results, and audit evidence are linked.

### Task 1: Phase 1 evidence preservation and source contract

**Files:**
- Modify: `src/county_research_ai/processor.py`
- Modify: `src/county_research_ai/models.py`
- Modify: `src/county_research_ai/evidence/store.py`
- Modify: `scripts/run_independent_smoke.py` and fixed-input artifact writers
- Create/Modify: `tests/test_evidence_preservation_regression.py`, `tests/test_source_contract.py`
- Create: `PHASE1_EVIDENCE_PRESERVATION_REPORT.md`

**Interfaces:**
- Consumes: legacy `RawDoc` and `ProcessedData`.
- Produces: paragraph-aware `EvidenceChunk`-compatible segments, explicit truncation metadata, stable source identifiers, and A/B/C-compatible source archives.

- [x] Write failing tests for newline preservation, compressed one-line input, long paragraph extraction, metric/value/unit adjacency, and explicit truncation reasons.
- [x] Write failing tests that require `doc_id`, `content_hash`, fetch/provider metadata, document timestamp, and chunk mapping in every group’s `sources.json`.
- [x] Implement minimal cleaning/chunking changes while preserving legacy model fields and CLI behavior.
- [x] Make `render_for_llm` budget-aware by task/source priority and return an auditable exclusion/truncation record rather than silently slicing.
- [x] Re-run the full Deqing chain and assert 100% retention of the four required facts plus source URLs; assert nationwide GDP is not substituted.
- [x] Generate `PHASE1_EVIDENCE_PRESERVATION_REPORT.md` with before/after counts and remaining limits.

### Task 2: Phase 2 evaluation audit and offline rescoring

**Files:**
- Modify: `src/county_research_ai/evaluation/claim_verification.py`
- Modify: `src/county_research_ai/evaluation/metrics.py` and scoring scripts as needed
- Create/Modify: `tests/test_claim_verification.py`, `tests/test_evaluation_metrics.py`
- Create: `PHASE2_EVALUATION_AUDIT.md` and versioned offline rescore outputs

**Interfaces:**
- Consumes: archived reports, unified sources, frozen claims, and existing score outputs.
- Produces: independent Ground Truth Recall, Report Fact Precision, Evidence Support Rate, Factual Error Rate, and Unverifiable Rate with claim-level change logs.

- [x] Add at least 12 negative tests covering different year, region, metric, unit, caliber, revised value, missing mention, and URL-only support.
- [x] Implement comparison on `(region, metric, period, scope, unit, version)` and classify non-comparable claims without calling them contradictions.
- [x] Re-score historical artifacts offline without Provider calls; preserve old outputs and write a new version.
- [x] Audit denominator independence and report every classification change and its cause.

### Task 3: Phase 3 structured evidence architecture

**Files:**
- Create: `src/county_research_ai/domain/research_contracts.py`
- Create: `src/county_research_ai/evidence/ledger.py`, adapters, and focused tests
- Modify: `src/county_research_ai/evidence/store.py`, `src/county_research_ai/models.py`, `src/county_research_ai/research_agent/coordinator.py`
- Create: `PHASE3_EVIDENCE_ARCHITECTURE.md`

**Interfaces:**
- Produces Pydantic contracts for `ResearchSpec`, `SourceDocument`, `EvidenceChunk`, `AtomicClaim`, `QuestionSlot`, and `EvidencePack`.
- Provides adapter functions from legacy `RawDoc`/`ProcessedData` and a ledger path that is actually consumed by the research workflow.

- [ ] Write schema and round-trip tests first, including unit normalization, multiple sources, same-source repost detection, missing evidence, and versioned/revised values.
- [ ] Implement the contracts with explicit unknown/limited-offset states; never fabricate source offsets.
- [ ] Implement ledger insertion, relation lookup, verification status, and EvidencePack selection under a token budget.
- [ ] Integrate one real legacy workflow path and prove the ledger output reaches analysis/report generation.

### Task 4: Phase 4 task-driven adaptive retrieval

**Files:**
- Modify: `src/county_research_ai/search/query_engine.py`, `collector.py`
- Modify: `src/county_research_ai/research_agent/tree.py`, `critic.py`, coordinator
- Create: retrieval/coverage tests and `PHASE4_ADAPTIVE_RETRIEVAL_REPORT.md`

**Interfaces:**
- Consumes `ResearchSpec`/`QuestionSlot` and EvidencePack coverage.
- Produces mode-specific query plans, relevance/diversity scores, gap-linked follow-up queries, and stop reasons with resource usage.

- [ ] Add offline tests showing different plans for `snapshot`, `rise-fall`, and `long-history`.
- [ ] Add deterministic ranking tests for task relevance, region/period/metric match, reliability, novelty, and repost deduplication.
- [ ] Implement feedback-driven follow-up and stop conditions for quality, budget, and zero marginal evidence.
- [ ] Replay saved searches and compare task-relevant recall against the legacy plan without new Provider calls.

### Task 5: Phase 5 evidence-bound analysis and verification

**Files:**
- Modify: `src/county_research_ai/research_agent/specialized/`, coordinator, verifier, mode analyzers, report renderers
- Create: evidence-bound generation tests and `PHASE5_EVIDENCE_BOUND_SYNTHESIS_REPORT.md`

**Interfaces:**
- Consumes EvidencePack and verified AtomicClaims.
- Produces findings tagged as fact, supported fact, inference, hypothesis, or gap; every material conclusion maps to Claim → Chunk → Source.

- [ ] Add failing hallucination tests for unsupported county attributes, unsupported numbers, same-value/different-metric citations, and low-confidence missing evidence.
- [ ] Implement claim-bound generation and conservative uncertainty rendering while keeping legacy output available.
- [ ] Verify reports and sources through the archived evidence graph, not URL presence alone.

### Task 6: Phase 6 efficiency and mode routing

**Files:**
- Modify: mode routing, long-history analysis, resource/usage instrumentation, manifests
- Create: efficiency tests and `PHASE6_EFFICIENCY_OPTIMIZATION_REPORT.md`

**Interfaces:**
- Supports `workflow_legacy`, `deep_legacy`, and `evidence_first_v2` with manifest-visible architecture versions.
- Records actual Search/Fetch/LLM usage, latency, retries, new evidence, and budget stop state.

- [ ] Add tests for architecture-version routing, missing/unknown Usage, budget exhaustion, and long-history checkpoint reuse.
- [ ] Implement timeline/period EvidencePacks and independent period analysis with one final synthesis.
- [ ] Replay long-history inputs and report actual token/call changes; treat 30% reduction as a target, not an assumption.

### Task 7: Phase 7/8 offline replay, independent evaluation, and delivery

**Files:**
- Create/Modify: replay/evaluation scripts, experiment reports, `docs/architecture/EVIDENCE_FIRST_V2.md`, `docs/architecture/MIGRATION_GUIDE.md`, `experiments/independent_comparison/reports/REFACTOR_FINAL_REPORT.md`
- Modify: `GOAL_EVIDENCE_FIRST_V2.md`

**Interfaces:**
- Produces reproducible legacy vs Evidence-First replay tables, optional authorized smoke-test records, module ablations, engineering acceptance, research acceptance, known limitations, and next actions.

- [ ] Run all offline replays before any new real Provider call; compare fact retention, claim precision/recall, evidence support, error rate, calls, tokens, and latency.
- [ ] Run real Provider smoke tests only when an explicit current cost gate permits them; preserve every failure and usage record.
- [ ] Audit public CLI compatibility, unused modules, hard-coded usage, source traceability, and actual ledger participation.
- [ ] Complete final documents and mark the Goal `ENGINEERING_COMPLETE_RESEARCH_PENDING` when independent research evidence is insufficient.

