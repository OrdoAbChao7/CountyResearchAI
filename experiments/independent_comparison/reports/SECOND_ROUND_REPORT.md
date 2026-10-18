# 第二轮效能验证报告

## 状态

`BENCHMARK_FROZEN_SECOND_ROUND_NOT_RUN`

本报告仍不提供新的真实 Provider 质量结论。A/B/C 的正式实验 Gate 仍为
`CLOSED_BILLING_UNCONFIRMED`，因此 Natural Execution、Matched Budget 和模块消融均未运行。
本轮只在当前用户明确授权的任务级 Ground Truth Gate 下调用 DeepSeek，完成了真实来源采集和
Benchmark 冻结；这些调用的 Usage 与原始响应已留存，但不等同于账户级账单。

## 已完成的可验证工作

- 历史第一轮原始运行、Judge、QA、账本和报告均保留；研究状态降级为
  `INCONCLUSIVE_WITH_EFFICIENCY_REGRESSION`。
- 新指标区分 `fact_precision`、`ground_truth_recall`、`evidence_support_rate`、
  `factual_error_rate` 和 `unverifiable_rate`；无有效分母返回 `N/A`（JSON 中为 `null`）。
- 离线 Judge 校准夹具覆盖正确、矛盾、不支持、未提及、争议和行政范围混淆六类情形。
- rich Benchmark Claim 必须包含任务模式、预期答案、来源标题/日期、指标年份、行政范围，
  并通过两个来源和两个独立上下文核验。
- 真实续作采集已完成 6 个地区 × 3 种模式 × 5 条声明：共 90 条；每个地区 15 条，
  每种模式 5 条。90/90 条均有两个不同 URL、两个上下文和逐条原文摘录。
- 本地 Builder 已生成 `FROZEN_CONTINUATION_BENCHMARK`，source hash 为
  `a5fa504976b83c57334f36cc246ef2a3f73b706957a4c9a2725d222d0f4f1bdd`。

## 未运行的实验

Natural Execution 和 Matched Budget 均未运行；模块消融也未运行。原因是正式实验 Gate
仍未打开，不能把 Ground Truth 采集授权扩大为整轮 A/B/C 研究授权，也不能把本地 Usage
记录直接换算为账户费用。

## 解锁条件

1. 为正式 LLM 与 Search/Fetch 分别提供当前、可审计的账户计费或免费额度证据，重新生成 formal fresh precheck。
2. 使用已冻结的 `benchmark_claim_schema.yaml`、`continuation_protocol.yaml` 和
   `continuation_ground_truth_20261019.jsonl`，先完成离线评分校准与输入 hash 复核。
3. 重新打开 formal Gate 后，分别运行 Natural Execution 与 Matched Budget，保留预算耗尽、
   Provider 失败、Judge 失败和仲裁状态，不做隐式补值。
