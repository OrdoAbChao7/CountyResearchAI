# 第二轮效能验证报告

## 状态

`STAGE_A_BLOCKED_GEMINI_PROVIDER_CONFIGURATION`

本报告仍不提供新的真实 Provider 质量结论。续作资源授权已根据当前用户人工确认改为
Gemini/Tavily 免费-only；Tavily usage 预检显示剩余 770 credits、PAYG=0。Stage A 首个真实
Gemini LLM 调用返回 HTTP 400 `INVALID_ARGUMENT`（需要有效 API key），ResourceManager 随即
停止本批次并保留失败 Manifest；没有切换到 DeepSeek，也没有产生付费调用。

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
- Stage A 计划为 2 个地区 × 3 个模式 × A/B/C = 18 个运行；实际只启动首个 A 运行，状态为
  `FAILED`，Tavily 3 次搜索成功、Gemini 1 次调用失败并结算 2,048 个预留 token 单位。

## 未运行的实验

Natural Execution 和 Matched Budget 尚未产生有效结果；模块消融也未运行。Stage A 的首个
Gemini 调用已证明当前 `.env` 的通用 `LLM_API_KEY` 对 Gemini 无效，Gate 已将 Gemini 熔断。
Tavily 仍有免费资格，但 A/B/C 必须使用同一个有效底层 LLM。

## 解锁条件

1. 只需配置有效的 `GEMINI_API_KEY`（或替换 `LLM_API_KEY`），不要提供 DeepSeek 付费授权。
2. 重新生成 Gemini/Tavily free-only precheck，并确认 `continuation_resource_gate_20261018.json`
   重新打开；用户不需要重复提交额度证明。
3. 使用已冻结的 `benchmark_claim_schema.yaml`、`continuation_protocol.yaml` 和
   `continuation_ground_truth_20261019.jsonl`，先完成离线评分校准与输入 hash 复核。
4. 重新打开 formal Gate 后，分别运行 Natural Execution 与 Matched Budget，保留预算耗尽、
   Provider 失败、Judge 失败和仲裁状态，不做隐式补值。
