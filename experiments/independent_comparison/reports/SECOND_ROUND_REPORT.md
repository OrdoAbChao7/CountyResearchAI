# 第二轮效能验证报告

## 状态

`NOT_RUN_BILLING_GATE_CLOSED`

本报告不提供新的真实 Provider 质量结论。续作资源 Gate 为
`CLOSED_BILLING_UNCONFIRMED`，当前没有账户级账单或免费额度证据，因此没有发起新的
DeepSeek、Gemini、Tavily 业务调用，也没有把离线夹具结果伪装成真实实验结果。

## 已完成的可验证工作

- 历史第一轮原始运行、Judge、QA、账本和报告均保留；研究状态降级为
  `INCONCLUSIVE_WITH_EFFICIENCY_REGRESSION`。
- 新指标区分 `fact_precision`、`ground_truth_recall`、`evidence_support_rate`、
  `factual_error_rate` 和 `unverifiable_rate`；无有效分母返回 `N/A`（JSON 中为 `null`）。
- 离线 Judge 校准夹具覆盖正确、矛盾、不支持、未提及、争议和行政范围混淆六类情形。
- rich Benchmark Claim 必须包含任务模式、预期答案、来源标题/日期、指标年份、行政范围，
  并通过两个来源和两个独立上下文核验。
- 本地 Builder 会在输入不足、地区配额不满足或双重核验缺失时拒绝冻结，未生成虚假
  15–20 条/地区 Ground Truth。

## 未运行的实验

Natural Execution 和 Matched Budget 均未运行；模块消融也未运行。原因不是实验结果为零，
而是当前没有可合法、可审计的业务调用授权和成本证据。

## 解锁条件

1. 为 LLM 与 Search/Fetch 分别提供当前、可审计的账户计费或免费额度证据，重新生成 fresh precheck。
2. 冻结 `benchmark_claim_schema.yaml`、`continuation_protocol.yaml` 和独立来源 Claim JSONL，
   每个地区满足 15–20 条、每种任务满足配额、每条 Claim 通过双来源/双上下文核验。
3. 重新打开 continuation Gate 后，分别运行 Natural Execution 与 Matched Budget，保留预算耗尽、
   Provider 失败、Judge 失败和仲裁状态，不做隐式补值。
