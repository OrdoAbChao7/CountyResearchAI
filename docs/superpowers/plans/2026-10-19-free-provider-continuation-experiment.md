# Free Provider Continuation Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在用户确认的 Gemini/Tavily 免费额度边界内，使用已冻结的 90 条 continuation benchmark 完成真实 A/B/C Natural Execution，并在审计通过后扩大到六地区与 Matched Budget。

**Architecture:** 保留历史 DeepSeek E1/E2 产物和旧结论；新增当前任务的免费资源授权记录、Gemini/Tavily fresh precheck、独立 continuation runner 和按地区+模式的声明级评分入口。所有真实调用继续通过同一个 SQLite ResourceManager，统一记录请求、token、并发租约、超额和熔断；付费/超免费不自动切换。

**Tech Stack:** Python, pytest, SQLite ResourceManager, Gemini OpenAI-compatible client, Tavily SearchProvider, frozen JSONL/YAML manifests.

**Spec:** 用户当前消息中的 CountyResearchAI Goal；冻结 benchmark 为 `experiments/independent_comparison/ground_truth/continuation_ground_truth_20261019.jsonl`。

## Global Constraints

- 仅允许 Gemini、Tavily 的已确认免费额度；DeepSeek 不属于本轮授权。
- 免费额度耗尽、PAYG/超额风险出现或 Provider 资格无法确认时立即停止对应 Provider。
- 不修改或重生成冻结的 90 条 Ground Truth；必须先校验 source hash、任务匹配和离线校准。
- Natural Execution 与 Matched Budget 分开运行、分开统计。
- A/B/C 使用同一底层 LLM、搜索 Provider、地区、任务模式和输出要求。
- 所有成功、失败、超额、空报告、Judge/Provider 错误均保留，不做隐式补值。

## Review Focus

- 用户确认免费额度但 API 不返回账户余额：授权记录必须明确是人工确认，不能伪造自动账单证据。
- Tavily 余额为零或 PAYG 非零：gate 与 ResourceManager 必须拒绝后续调用。
- 90 条 benchmark 每个地区和模式各 5 条：评分不能再覆盖成每地区一条。
- Stage A 只包含两个地区：扩展 Stage B 前必须通过 hash、任务匹配、运行状态和评分输入审计。
- A/B/C 任一真实 Provider 失败或 usage 缺失：该运行可见但不进入有效质量均值。

### Task 1: 免费资源授权与当前 Gate

**Files:**
- Create: `experiments/independent_comparison/manifests/resource_authorization_20261019.json`
- Modify: `experiments/independent_comparison/manifests/continuation_resource_gate_20261018.json`
- Modify: `scripts/precheck_independent_resources.py`
- Test: `tests/test_resource_precheck.py`, `tests/test_experiment_gate.py`

- [ ] Record current user confirmation separately for Gemini and Tavily with `FREE_CONFIRMED`, `free_only=true`, `paid_overage_allowed=false`, and `auto_switch_paid=false`.
- [ ] Refresh Gemini model visibility and Tavily usage without business model/search calls; use the user confirmation as the explicit free-qualification evidence when automated account balance is unavailable.
- [ ] Open only the continuation formal gate for Gemini/Tavily and retain ResourceManager capacity, concurrency, reservation, settlement, and circuit-breaker behavior.
- [ ] Add tests proving user-attested free-only authorization opens the scoped gate and any overage/PAYG or stale evidence closes it.

### Task 2: Frozen benchmark and scoring contract

**Files:**
- Modify: `scripts/score_independent_claims.py`
- Modify: `scripts/run_independent_judges.py`
- Modify: `scripts/run_independent_report_qa.py`
- Test: `tests/test_ground_truth_and_judging.py`, `tests/test_claim_verification.py`

- [ ] Verify the frozen file and manifest hash plus 6×3×5 task quotas before any business call.
- [ ] Resolve claims by `(region, research_mode)` and score all five claims for each valid report.
- [ ] Keep Judge and QA inputs task-scoped and exclude Ground Truth from report generation.

### Task 3: Continuation Natural runner

**Files:**
- Create: `scripts/run_continuation_experiment.py`
- Test: `tests/test_continuation_runner.py`

- [ ] Build specs from the frozen region file and three modes, with `formal_target=true`, common Gemini/Tavily configuration, and explicit `natural` policy.
- [ ] Run Stage A for two regions through existing A/B/C researchers and the shared ResourceManager.
- [ ] Persist per-run reports, sources, LLM responses, manifests, usage, search request counts, and failures.

### Task 4: Stage A audit and Stage B expansion

**Files:**
- Create: `scripts/audit_continuation_experiment.py`
- Create: `experiments/independent_comparison/reports/CONTINUATION_SECOND_ROUND_20261019.md`
- Modify: `GOAL.md`, `PROJECT_STATUS.md`, `experiments/independent_comparison/reports/SECOND_ROUND_REPORT.md`
- Test: `tests/test_continuation_audit.py`

- [ ] Audit Stage A for hash, task mapping, valid/invalid manifests, metric denominators, and resource ledger closure.
- [ ] If Stage A is valid, run six-region Natural Execution using remaining local free-resource capacity.
- [ ] Run Matched Budget only in a separate batch with identical per-pair budgets; never merge it with Natural results.
- [ ] Generate the second-round report with positive, negative, and inconclusive findings, including cost/quality tradeoffs and Provider stop reasons.

