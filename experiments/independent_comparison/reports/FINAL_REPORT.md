# CountyResearchAI 真实效能验证最终报告

日期：2026-10-18  
实验模型：DeepSeek `deepseek-flash`  
搜索：DeepSeek Search  
正式结论：`NO_OVERALL_ADVANTAGE`，但 E2 的报告问答能力出现有限优势

## 1. 结论先行

在本次六地区、一次重复的真实联网对照中，没有证据证明 CountyResearchAI（C）整体优于传统网页检索（A）或通用联网 AI（B）。

E1 端到端研究中，A/B/C 对冻结 Ground Truth 的事实准确率、关键事实覆盖率和证据支持率均为 0；C 的平均耗时约 71.1 秒、11,231.8 tokens、6 次搜索，明显高于 A 的 29.9 秒、2,122.7 tokens、3 次搜索和 B 的 29.7 秒、1,948.0 tokens、3 次搜索。C 没有表现出可由质量指标抵消的成本优势。

E2 相同输入研究中，三组的事实准确率、关键事实覆盖率和证据支持率均为 1.0，错误率均为 0。C 的报告 QA 准确率为 0.667，高于 A/B 的 0.500；但 C 使用 4,344.5 tokens，高于 A 的 1,978.5 和 B 的 2,854.5，且分析深度均值 0.573，低于 B 的 0.600。因此，E2 只支持“C 可能提升报告对独立 AI 问答的支持能力”，不支持“C 整体质量更高”或“C 更高效”。

样本规模只有每组每地区一次，且每地区只有一条冻结 Claim；结论是方向性证据，不应解释为统计显著性证明。

## 2. 有效实验范围

正式地区为德清县、长汀县、于都县、攀枝花市、白山市、临泽县，覆盖 `snapshot`、`long-history`、`rise-fall` 三类任务。E1 与 E2 各完成 18 个运行，即 6 地区 × 3 组 × 1 次重复；36/36 个修正后运行均为 `VALID`，报告均非空，且修正批次审计全部通过。

纳入统计的批次：

- E1：`formal_target_deepseek_20261018_corrected_r2`
- E2：`e2_formal_target_deepseek_20261018_corrected_*`
- Ground Truth：6 条正式、双来源/双上下文核验后的冻结 Claim

旧的 512-token 批次以及 `corrected_r1` 不进入质量统计。它们保留为诊断证据：DeepSeek 在较低输出上限下可能把额度消耗在 reasoning，导致 A/B 正文为空；现在运行器会将空报告标为失败，客户端对 DeepSeek 默认关闭 thinking，并将正式输出预算设为 2048。

## 3. 核心指标

### E1：端到端联网研究

| 指标 | A 传统检索 | B 通用联网 AI | C CountyResearchAI |
| --- | ---: | ---: | ---: |
| 事实准确率 | 0.000 | 0.000 | 0.000 |
| 关键事实覆盖率 | 0.000 | 0.000 | 0.000 |
| 证据支持率 | 0.000 | 0.000 | 0.000 |
| 错误率 | 1.000 | 0.500 | 0.833 |
| 分析深度 | 0.537（n=6） | 0.600（n=6） | 0.568（n=5） |
| 平均耗时（秒） | 29.90 | 29.73 | 71.09 |
| 平均 LLM tokens | 2,122.7 | 1,948.0 | 11,231.8 |
| 平均搜索请求 | 3 | 3 | 6 |
| 报告 QA 准确率 | 0.000 | 0.000 | 0.000 |

E1 的 Claim 指标为 0，主要反映本次冻结 Claim 与 E1 研究题目之间的口径不匹配：研究报告聚焦产业现状/升级，冻结问题要求报告直接覆盖特定年度 GDP 初始发布值。该结果不能单独解释为三种研究器的全部事实能力，但三组之间也没有出现可支持 C 优势的相对差异。

### E2：相同冻结输入

| 指标 | A 固定输入 | B 固定输入通用 AI | C 固定输入 CountyResearchAI |
| --- | ---: | ---: | ---: |
| 事实准确率 | 1.000 | 1.000 | 1.000 |
| 关键事实覆盖率 | 1.000 | 1.000 | 1.000 |
| 证据支持率 | 1.000 | 1.000 | 1.000 |
| 错误率 | 0.000 | 0.000 | 0.000 |
| 分析深度 | 0.528（n=5） | 0.600（n=6） | 0.573（n=6） |
| 平均耗时（秒） | 14.13 | 17.40 | 17.22 |
| 平均 LLM tokens | 1,978.5 | 2,854.5 | 4,344.5 |
| 搜索请求 | 0 | 0 | 0 |
| 报告 QA 准确率 | 0.500 | 0.500 | 0.667 |

配对差异显示，E2 中 C 相对 B 的分析深度为 -0.027，报告 QA 为 +0.167，LLM tokens 增加约 1,490；C 相对 A 的报告 QA 为 +0.167，tokens 增加约 2,366。由于 n=6，不能据此宣称稳定或显著提升。

## 4. 资源与评审消耗

研究阶段实际账本：E1 使用 91,815 LLM tokens、72 次 DeepSeek Search；E2 使用 55,065 LLM tokens、0 次搜索。Claim、Judge、QA 的评审调用另行记账，E1 分别为 92,383、121,574、52,229 tokens，E2 分别为 46,926、89,570、36,811 tokens。合计 DeepSeek LLM tokens 为 586,373，搜索请求为 72。

本报告不把 tokens 换算成金额：账本记录了真实 Usage，但当前产物没有可靠的账户级价格结算字段。DeepSeek 付费调用使用了用户在本轮明确授权的 `USER_AUTHORIZED_PAID` 边界；没有把它描述成免费调用，也没有记录 API Key。

## 5. 有效性、失败样本与审计

- E1/E2 修正后 36 个研究运行均通过 Manifest、报告哈希、原始 LLM 响应、Usage 和资源租约审计。
- E1/E2 Claim Verification 均为 18/18 有效；E1 曾出现一个布尔字符串格式漂移，兼容修复后重算，旧失败记录保留。
- E1/E2 Judge 均为 17/18 有效；各有一个候选因单个 Judge 返回无效结构而保留为 `FAILED_JUDGE`，没有用另一份评分补齐，也没有启动 adjudicator。
- QA 均为 18/18 可解析；E1 均为 0 分，E2 平均为 0.556。
- 旧批次的空报告、预算超限和失败运行没有删除，且没有进入本报告的有效质量统计。
- 审计脚本对 E1 修正根目录和六个 E2 修正根目录均返回 `passed=true`、无错误或警告；该审计是确定性的产物/资源审计，不是另一个 LLM 评审 Agent。

## 6. 局限

1. 每组每地区只有一次重复，不能可靠估计方差或统计显著性。
2. Ground Truth 每地区只有一个最小 Claim，E1 题目与冻结 Claim 的覆盖关系不充分，导致三组 E1 事实指标同时为 0。
3. C 的搜索请求数和 LLM 调用数明显更多；本实验保留了这一真实成本差异，但不能把 C 与 A/B 解读成完全相同搜索预算下的纯架构消融。
4. 没有完成 QuestionTree、ResearchCritic、FactVerifier、Specialized Role Analysis 的可靠消融，因此不能归因到具体模块。
5. Judge 使用同一 DeepSeek 模型体系，虽然上下文和报告匿名隔离，仍可能存在模型相关评审偏差。
6. QA 衡量的是“报告能否支持独立 AI 回答冻结问题”，不等于真实人类理解能力。

## 7. 可复现证据

- [修正后 E1 运行根目录](E:\Projects\CountyResearchAI\experiments\independent_comparison\runs\formal_target_deepseek_20261018_corrected_r2)
- [E1 合并观测](E:\Projects\CountyResearchAI\experiments\independent_comparison\metrics\observations_formal_target_deepseek_20261018_corrected_r2_v2.jsonl)
- [E1 汇总统计](E:\Projects\CountyResearchAI\experiments\independent_comparison\metrics\summary_formal_target_deepseek_20261018_corrected_r2_v2.csv)
- [E1 配对统计](E:\Projects\CountyResearchAI\experiments\independent_comparison\metrics\paired_formal_target_deepseek_20261018_corrected_r2_v2.csv)
- [E2 汇总统计](E:\Projects\CountyResearchAI\experiments\independent_comparison\metrics\summary_e2_formal_target_deepseek_20261018_corrected.csv)
- [E2 配对统计](E:\Projects\CountyResearchAI\experiments\independent_comparison\metrics\paired_e2_formal_target_deepseek_20261018_corrected.csv)
- [E1 修正批次审计](E:\Projects\CountyResearchAI\experiments\independent_comparison\reports\audits_corrected_20261018\e1.json)
- [E2 修正批次审计目录](E:\Projects\CountyResearchAI\experiments\independent_comparison\reports\audits_corrected_20261018)
- [冻结正式协议](E:\Projects\CountyResearchAI\experiments\independent_comparison\protocol\protocol.yaml)
- [冻结 Ground Truth](E:\Projects\CountyResearchAI\experiments\independent_comparison\ground_truth\formal_ground_truth_20261018.jsonl)
- [冻结启动配置](E:\Projects\CountyResearchAI\experiments\independent_comparison\manifests\formal_launch_manifest_20261018.json)

## 最终判断

本 Goal 的工程验收和最小研究验收已完成，但研究结果不是“CountyResearchAI 显著胜出”。当前最可靠的结论是：C 在相同冻结输入下可能提高报告对独立 AI 问答的支持能力，但以更高 token 成本为代价；在端到端联网研究的事实/证据/效率指标上，本次数据不支持 C 相比 A/B 存在整体实质性提升。
