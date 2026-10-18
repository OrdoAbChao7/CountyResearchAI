# Continuation P0 Audit: Billing Boundary and First-Round Validity

日期：2026-10-18
分支：`codex/experiment-superiority`
状态：`INCONCLUSIVE_WITH_EFFICIENCY_REGRESSION`

## 结论

本轮续作在计费边界重新确认前关闭所有新的业务 API 调用。第一轮记录了真实 Provider Usage 和资源租约，但没有保存账户账单、金额、货币、订单或 Provider billing 回执，因此无法从仓库证实实际费用，也不能把本地 token 数换算为已发生费用。

第一轮 `USER_AUTHORIZED_PAID` 的来源是人工写入的预检记录，而不是账户级计费查询：

- `manifests/resource_precheck_20261018_deepseek.json` 的两个 billing evidence 都引用旧会话中的用户指令。
- `manifests/formal_target_gate_20261018.json` 将该 evidence 作为正式 Gate 的依据。
- `manifests/formal_launch_manifest_20261018.json` 将各类资源标记为 `user_authorized_paid`。

当前续作指令明确撤回“无限制付费”的解释。因此这些文件只作为第一轮历史证据保留，不作为当前调用授权。

## 费用与资源证据边界

| 项目 | 仓库能确认的内容 | 仓库不能确认的内容 |
| --- | --- | --- |
| 第一轮正式 E1/E2 研究与后处理 | 586,373 个 DeepSeek LLM tokens、72 次 Search 请求；资源租约均有 settled 记录 | 真实金额、货币、发票、账户余额、套餐状态 |
| 资源账本字段 | `reserved_units`、`consumed_units`、`usage_json`、`status`、`error` | 价格、账单 ID、扣费状态 |
| Provider 预检 | 模型可见性、请求成功与本地配置状态 | DeepSeek 账户免费资格或实际计费结果 |
| 资源类别 | 旧账本记录为 `paid_authorized` | 当前用户是否授权这些调用；当前答案为否，除非重新明确授权 |

所有历史 SQLite 账本共 37 个文件、1,014 个租约；其中 1,013 个 `settled`，1 个 `overrun`。这些数字是本地实验计量，不是账单。

## 资源管理器审计

`ResourceManager` 不会根据 API 返回自动从免费 Provider 切换到付费 Provider；它使用调用方传入的 `ResourceLimit.billing_class`。但是当前实现允许显式配置 `paid_authorized`，而正式 Gate 也接受 `USER_AUTHORIZED_PAID`。这对第一轮是可追溯的显式配置，对当前续作是不够保守的，因为旧人工 evidence 不能证明账户级授权或费用边界。

续作的安全策略是：当前 continuation gate 使用 `CLOSED_BILLING_UNCONFIRMED`，禁止所有新的业务 API 调用；只有重新取得明确、当前、按 LLM 与 Search/Fetch 分 scope 的授权和计费证据后，才允许重新打开 Gate。

## 第一轮 Benchmark 有效性审计

### Ground Truth 与任务不匹配

正式文件 `ground_truth/formal_ground_truth_20261018.jsonl` 只有 6 条 claim，每个地区 1 条，而且全部是 GDP 总量或增速。E1 任务要求产业结构、产业链、瓶颈、历史和政策；因此 E1 的三组事实指标为 0 不能解释为完整研究能力为零，只能说明报告没有命中这 6 个 GDP claim。

E2 使用冻结输入中的同一类 GDP 事实，三组事实指标全部为 1.0，属于单 claim、单主题带来的天花板效应，不能代表完整分析能力。

### 评价器分母不足

`claim_verification.py` 只核验预先给定的 Ground Truth claim，没有从报告中建立完整的实际事实声明集合。`MetricsCalculator` 的 `fact_accuracy` 只在匹配到的 Ground Truth evaluations 上计算，未匹配的报告事实不会进入精度分母。因此现有数值不是严格的 report-level Fact Precision。

### N/A 被压成数值

当前 `MetricsCalculator` 在没有可验证分母时返回 `0.0`。这会把“没有可测量分母”和“真实得分为零”混在一起。续作必须改为显式 `None`/N/A，并保存分子、分母和证据。

### Judge 与资源效率

第一轮最终 E1/E2 Judge 各有 17/18 个有效结果，失败样本没有被完全消除；C 的额外 token 和耗时优势没有被可靠质量分母抵消。第一轮正式结果应保留，但研究结论需降级为 `INCONCLUSIVE_WITH_EFFICIENCY_REGRESSION`。

## 当前禁止事项

- 不执行新的 DeepSeek LLM、Search、Fetch、Claim、Judge 或 QA 业务调用。
- 不修改或删除第一轮运行、评分、账本和最终报告。
- 不根据第一轮报告反向挑选有利 Ground Truth。
- 不把历史 `USER_AUTHORIZED_PAID` 标记当作当前授权。

## 解锁条件

1. 当前用户重新明确授权的计费范围，或取得可核验的免费资格证据。
2. 新的 rich Ground Truth 完成任务匹配、双上下文核查并冻结。
3. 离线评分控制样例证明 Precision、Recall、Evidence、Error 和 N/A 语义可区分。
4. Natural Execution 与 Matched Budget 协议分别冻结。
5. 低成本真实批次通过审计后，才可扩大规模。
