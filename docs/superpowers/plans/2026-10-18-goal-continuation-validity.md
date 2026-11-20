# CountyResearchAI Benchmark Validity Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复第一轮 CountyResearchAI 对照实验的计量有效性问题，在禁止未经确认付费调用的前提下，建立可区分质量、成本和模块贡献的第二轮 Benchmark。

**Architecture:** 保留第一轮原始运行、评分和结论作为不可变历史证据；新增 continuation 状态、关闭付费 Gate、丰富 Ground Truth schema，并将报告声明级事实精度、Ground Truth recall、证据支持和不可判定项分开计算。所有新评分先通过离线控制样例，再允许低成本真实实验。

**Tech Stack:** Python 3.13, pytest, SQLite ResourceManager, JSONL/YAML frozen manifests, existing DeepSeek-compatible provider adapters, offline deterministic calibration fixtures.

**Spec:** User-pasted Goal Continuation file at `D:\Dev\.codex\attachments\2060caa9-1df1-4881-ab4d-d3367f6025ab\已粘贴的文本.txt`.

## Global Constraints

- Preserve all first-round raw runs, judgements, ledgers, reports, and hashes.
- Do not make any new DeepSeek/Gemini/Tavily business call until billing authorization and billing evidence are confirmed.
- Do not use the first-round reports to select favorable Ground Truth claims.
- Use TDD for production behavior changes: write a failing test, observe the expected failure, implement the minimum fix, then run the full suite.
- A metric with no valid denominator is `None`/N/A, never an artificial `0` or `1`.
- A failed judge remains visible and cannot be silently imputed or discarded.

## Review Focus

- Historical `USER_AUTHORIZED_PAID` evidence is not current billing evidence; test that the continuation gate rejects it.
- A report can contain correct facts outside Ground Truth; test that precision uses report-claim denominator while recall uses frozen Ground Truth denominator.
- An empty report, no source, and an unverified claim must not receive a numeric full score.
- A disputed or unavailable source must be separated from a proven factual error.
- A benchmark claim must carry task mode, expected answer, scope, dates, evidence, and two independent verification contexts.

### Task 1: Billing stop and first-round validity audit

**Files:**
- Create: `experiments/independent_comparison/reports/CONTINUATION_P0_AUDIT_20261018.md`
- Create: `experiments/independent_comparison/manifests/continuation_resource_gate_20261018.json`
- Modify: `GOAL.md`
- Test: `tests/test_experiment_gate.py`, `tests/test_evaluation_resource_manager.py`

**Interfaces:**
- The continuation gate records `CLOSED_BILLING_UNCONFIRMED` and `allow_paid_authorized: false`.
- Historical paid-authorized manifests remain evidence only and are not edited.

- [x] Record the source and scope of the historical paid label, ledger fields, missing billing evidence, and all confirmed token/request totals.
- [x] Add a failing gate test showing `USER_AUTHORIZED_PAID` is rejected under the current continuation policy.
- [x] Implement the current closed-gate policy without changing historical artifacts.
- [x] Verify no business API call is made when the continuation gate is closed.

### Task 2: Rich frozen Benchmark Claim schema

**Files:**
- Modify: `src/county_research_ai/evaluation/ground_truth.py`
- Create: `experiments/independent_comparison/protocol/benchmark_claim_schema.yaml`
- Test: `tests/test_ground_truth_and_judging.py`

**Interfaces:**
- Add task-aware claim fields: `research_mode`, `expected_answer`, `source_title`, `source_date`, `metric_year`, and `administrative_scope`.
- Preserve backward loading of first-round minimum claims, while rich continuation claims require these fields before freeze.

- [x] Add failing tests for missing task mode, expected answer, source evidence, scope, and cross-verification context.
- [x] Implement rich-claim validation and a separate continuation freeze status.
- [x] Add schema examples for snapshot, rise-fall, and long-history claims.

### Task 3: Distinct report precision, Ground Truth recall, and N/A semantics

**Files:**
- Modify: `src/county_research_ai/evaluation/metrics.py`
- Modify: `src/county_research_ai/evaluation/statistics.py`
- Modify: `scripts/score_independent_claims.py`
- Test: `tests/test_experiment_metrics.py`, `tests/test_experiment_statistics.py`

**Interfaces:**
- `MetricsResult` exposes `fact_precision`, `ground_truth_recall`, `evidence_support_rate`, `factual_error_rate`, and `unverifiable_rate` as optional numeric values.
- Legacy fields remain readable only as compatibility aliases while new reports use the distinct names.

- [x] Add failing control tests for correct extra report claims, missing Ground Truth claims, unverified claims, and zero denominators.
- [x] Implement denominator-aware metrics with explicit numerator/denominator evidence.
- [x] Ensure statistics omit `None` from means and render N/A rather than zero.

### Task 4: Offline Judge calibration and failure accounting

**Files:**
- Modify: `src/county_research_ai/evaluation/claim_verification.py`
- Modify: `src/county_research_ai/evaluation/judging.py`
- Create: `experiments/independent_comparison/fixtures/judge_calibration_cases.jsonl`
- Test: `tests/test_claim_verification.py`, `tests/test_ground_truth_and_judging.py`, `tests/test_judge_batch.py`

- [x] Add failing calibration cases for correct, contradicted, unsupported, missing, disputed, and scope-confused claims.
- [x] Implement deterministic checks for numeric/date/unit/scope cases before LLM semantic review.
- [x] Preserve failed judge observations and apply explicit retry/adjudication status.
- [x] Run offline calibration without any provider call; real-provider cost comparison remains blocked by the closed gate.

### Task 5: Independent Ground Truth builder and matched-budget protocol

**Files:**
- Create: `experiments/independent_comparison/protocol/continuation_protocol.yaml`
- Create: `experiments/independent_comparison/datasets/independent_regions_20261018.yaml`
- Create: `scripts/build_benchmark_ground_truth.py`
- Test: `tests/test_ground_truth_builder.py`, `tests/test_formal_runner.py`

- [x] Define independent holdout regions and task-to-claim quotas; final freeze remains pending authoritative Claim input.
- [ ] Build 15–20 task-matched claims per region from authoritative sources, with two independent verification contexts.
- [x] Define Natural Execution and Matched Budget as separate experiments and record budget exhaustion uniformly.
- [x] Do not launch real providers until the billing gate and offline calibration pass.

### Task 6: Second-round analysis and optional ablations

**Files:**
- Create: `experiments/independent_comparison/reports/SECOND_ROUND_REPORT.md`
- Modify: `scripts/generate_independent_stats.py`
- Test: `tests/test_final_report_inputs.py`, full suite

- [ ] Run only the smallest approved real batch after the gate is reopened.
- [ ] Produce quality/cost tables for Natural Execution and Matched Budget separately.
- [ ] Run module ablations only when each module can be disabled without fabricated output.
- [x] Report the current second-round state as `NOT_RUN_BILLING_GATE_CLOSED`, with uncertainty and retained historical failures.

## Verification Commands

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests scripts
```

The continuation cannot be marked research-complete until the offline calibration passes and the new benchmark has a valid denominator for each claimed quality metric.
