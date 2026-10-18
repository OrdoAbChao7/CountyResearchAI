# Smoke Test 中间报告

日期：2026-10-18

## 结论

本轮 Smoke Test 证明 CountyResearchAI 的严格真实运行链路可以完成：Gemini `gemini-3.1-flash-lite` 和 Tavily 被真实调用，Mock 回退被禁止，资源租约可结算，运行 Manifest、报告、来源和原始搜索数据可以落盘。

本轮不能回答 CountyResearchAI 是否优于 A/B 基线。原因是：开发集地区不属于正式样本；A/B 与 C 没有在同一预算和完整配置下形成公平有效的三组配对；没有冻结 Ground Truth、盲评或声明级质量指标。质量结论为 `INCONCLUSIVE`。

## 运行批次

### 批次 `smoke_20261018T095509Z`

目标为安吉县、信丰县各执行一次 A/B/C。中央账本实际结算：Gemini 4 次调用、39,061 tokens；Tavily 26 次请求。预算上限为 40,000 Gemini token，触发后续预留拒绝。

| 地区 | A | B | C | 说明 |
| --- | --- | --- | --- | --- |
| 安吉县 | `VALID` | `VALID` | `FAILED` | C 在分析阶段触发资源耗尽，旧 Runner 当时记录为普通失败 |
| 信丰县 | `FAILED` | `FAILED` | `FAILED` | 后续运行因中央 Gemini 预算不足；没有 Mock 回退 |

这批次只作为资源熔断和失败样本证据，不进入质量比较。

### 批次 `c_probe_20261018T180500Z`、`c_probe_20261018T181500Z`

两次低预算 C 运行都完成了真实 Tavily/Gemini 调用，但因为实验器把相对运行目录和绝对产物路径混用，在 Manifest 收尾时失败。它们保留为实验框架缺陷样本，不改写为有效结果。

### 批次 `c_probe_20261018T182500Z`

这是修复路径规范化后的最后一次低预算 C 探针：安吉县、snapshot、Tavily 每次最多 1 个返回结果、仅 `industry_status` 任务、每次 Gemini `max_tokens=512`。

| 项目 | 实际结果 |
| --- | --- |
| Manifest | `VALID` |
| Gemini | 2 次调用，实际 7,659 tokens |
| Tavily | 7 次搜索请求；账本按每次 1 credit 保守记录 |
| 租约 | 9/9 settled，无 active lease |
| 产物 | report、sources、generated report、raw docs、processed data；该历史批次没有 LLM 原始响应目录 |
| Ground Truth / Judge | NOT RUN |

运行目录：`experiments/independent_comparison/runs/c_probe_20261018T182500Z/`。

## 可信性检查

- 当前 C 运行未构造 Mock 实例，strict container 未静默降级。
- Provider model 与冻结配置一致。
- 资源账本记录实际 Provider Usage；预留 1,024 token 但实际结算 7,659 token，说明不能只看请求上限，必须保留 Provider 返回的真实用量。
- 报告当前只包含 1 个来源，且来源为较早的历史论文；这属于资料覆盖不足风险，不能用于证明当前产业现状完整或准确。
- API 账户实时免费余额、RPM/TPM/RPD 仍未由账户侧确认；本报告不声称绝对不会产生费用。

## 下一步

1. 为正式地区独立构建并冻结 Ground Truth，至少两个核查上下文交叉验证。
2. 实现报告声明提取、Blind Judge 和支持率计算，禁止只以 URL 数量评分。
3. 为 A/B/C 冻结相同模型、搜索请求预算、输出要求和截止条件，先完成一个公平配对，再决定是否扩展样本。
4. 保存每次 LLM 原始响应和请求元数据。当前代码已接入该归档；本历史 C 批次发生在接入前，因此仍保留为“归档缺失”审计警告。

## 于都县先导批次

`pilot_20261018T183000Z` 使用未参与开发调试的于都县，A/B/C 各尝试一次。A/B 的真实调用完成，但实际 Gemini Usage 合计 45,641 tokens，超过预设 24,000-token 本地批次容量；旧版结算逻辑未在实际 Usage 结算时熔断，故两份 Manifest 已更正为 `INVALID_RESOURCE_ACCOUNTING`。C 随后在预留阶段被 `BLOCKED`。这批次证明了资源超限缺陷及修复路径，不进入质量比较。
