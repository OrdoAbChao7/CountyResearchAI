# 第二轮效能验证报告

## 状态

`AUDITED_WITH_NEGATIVE_RESULT_FOR_C`

第二轮真实对照已经完成并分开审计。Gemini 首次真实调用返回 HTTP 400
`INVALID_ARGUMENT` 后被熔断；本轮按用户授权改用 DeepSeek `deepseek-flash` 作为共同底层
LLM，Tavily 继续使用已确认的免费额度。DeepSeek LLM 的边界是
`USER_AUTHORIZED_PAID`；DeepSeek Search/Fetch 未启用；没有自动切换到付费搜索或把付费调用标记为免费。

本报告不支持“CountyResearchAI 优于传统检索或通用联网 AI”的总体结论。相反，当前可复核证据显示：
在冻结的 90 条事实任务上，C 没有取得有效 Ground Truth 命中，并且消耗更多 token、搜索请求和时间。
这是一轮真实负面结果，不是把任务错配或评分器缺陷当成零分；所有旧失败运行和旧评分输出仍保留。

## 冻结数据与有效性审计

- `FROZEN_CONTINUATION_BENCHMARK`：6 个地区 × 3 种模式 × 5 条声明，共 90 条。
- source hash：`a5fa504976b83c57334f36cc246ef2a3f73b706957a4c9a2725d222d0f4f1bdd`。
- 每个运行任务均与冻结的 `(region, research_mode)` 匹配；Stage A、Stage B Natural 和 Matched Budget 的审计均通过 Hash 与任务匹配检查。
- 确定性 Claim v3 已修复县级行政口径同义词和百分比/结构比例单位别名；旧 v1/v2 全零结果作为缺陷审计证据保留，不进入本报告结论。

## Stage A：两地区 Natural Smoke

批次：`continuation_natural_stage_a_deepseek_flash_retry_20261019`，18/18 `VALID`，90 条声明观测。

| 组别 | 事实准确率 | Ground Truth 覆盖率 | 证据支持率 | 错误率 | 平均时间 | LLM units | 搜索 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A 传统检索模拟 Agent | 0.200 | 0.200 | 0.200 | 0.800 | 43.69s | 6,180 | 3 |
| B 通用联网 AI Agent | 0.200 | 0.200 | 0.200 | 0.800 | 45.31s | 7,098 | 3 |
| C CountyResearchAI | 0.000 | 0.000 | 0.000 | 1.000 | 101.03s | 37,443 | 6 |

A/B 在德清 snapshot 任务中各覆盖 5/5 条冻结事实；C 在两个地区的所有任务均未覆盖对应冻结事实。
因此 Stage A 的 C=0 是真实运行结果，不是 Ground Truth 与任务不匹配造成的全零。

## Stage B：六地区 Natural Execution

批次：`continuation_natural_stage_b_deepseek_flash_20261019`，54/54 `VALID`，270 条声明观测。

| 组别 | 事实准确率 | Ground Truth 覆盖率 | 证据支持率 | 错误率 | 平均时间 | LLM units | 搜索 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A 传统检索模拟 Agent | 0.144 | 0.144 | 0.144 | 0.856 | 41.09s | 6,558 | 3 |
| B 通用联网 AI Agent | 0.189 | 0.189 | 0.189 | 0.811 | 42.82s | 7,148 | 3 |
| C CountyResearchAI | 0.000 | 0.000 | 0.000 | 1.000 | 97.62s | 37,604 | 6 |

C 在六地区 Natural Stage B 的全部有效运行中仍为零命中。典型原始报告明确记录来源文档被截断、
县级统计缺失；这解释了失败机制，但不能把失败改写为成功。

## Stage B：Matched Budget

批次：`continuation_matched_budget_deepseek_flash_20261019`。每个运行使用相同的
`deepseek-flash`、Tavily、90,000 LLM units、6 次搜索请求和 120 秒墙钟上限；自然运行结果不并入本节。

- 54/54 计划运行完成：48 个 `VALID`，6 个 `BUDGET_EXHAUSTED`，无 `FAILED` 或 `BLOCKED`。
- 6 个预算超时全部是 C 的 `long-history` 任务；A/B 的 36 个运行全部有效，C 的 snapshot/rise-fall
  12 个运行有效。
- 有效评分包含 240 条声明观测：A 90、B 90、C 60。C 有效观测的事实准确率、Ground Truth
  覆盖率和证据支持率均为 0.000；A 分别为 0.238、0.188、0.188，B 分别为 0.189、0.189、0.189。
- 有效运行的平均资源为：A 6,608 LLM units/3 搜索/41.43s，B 6,895/3/42.12s，C
  22,652/6/77.68s。C 的有效运行仍约为 B 的 3.3 倍 LLM units、2 倍搜索请求和 1.8 倍时间；
  另外 6 个长历史任务直接超过墙钟预算。

Matched Budget 审计状态为 `DATASET_AND_RESOURCE_AUDITED`：冻结 Hash 和任务匹配通过；非有效状态均
有明确的墙钟超时和资源使用记录，没有被静默丢弃或补值。

## 资源与失败记录

- Stage A DeepSeek LLM：304,320 units；Tavily 72 次。
- Stage B Natural DeepSeek LLM：923,585 units；Tavily 216 次。
- Matched Budget DeepSeek LLM：891,385 units；Tavily 216 次。
- Matched Budget SQLite 账本结算 378 个租约，活动租约 0；Tavily 预检时剩余 770 credits、PAYG=0。
- Gemini 失败、DeepSeek 模型身份不匹配、容量不足批次、评分器 v1/v2 输出和所有预算超时运行均保留。

本地 usage 是 Provider 返回的使用量，不等同于账户发票余额；资源管理器仍保留请求计数、并发、容量、
超额结算和熔断。后续若 Tavily 免费资格不再确认、余额耗尽或 PAYG 非零，应立即停止 Tavily；
不会自动切换付费搜索。

## 结论与限制

本轮没有发现 C 找到更多正确产业事实、补足 A/B 遗漏机制、解决统计口径冲突或产生更强证据因果分析的
证据。相反，在本冻结任务和当前实现下，C 的事实覆盖为零，且运行成本显著更高；通用联网 AI B 已经
完成了 C 在这些可评分事实任务上的全部有效命中能力，至少没有观察到 C 的增益。

这不是统计显著性结论：每个地区/模式目前只有一次重复，且 C 的长历史 Matched Budget 运行全部超时。
也没有完成可靠的模块消融，因此不能把差异归因到某一个专用模块。下一轮如继续，应先修复 C 对截断
来源和长历史任务的处理，再进行独立重复；在修复前不应扩大付费调用或宣称产品优越性。

## 产物索引

- 冻结 Ground Truth：`experiments/independent_comparison/ground_truth/continuation_ground_truth_20261019.jsonl`
- Stage A 审计：`experiments/independent_comparison/reports/CONTINUATION_STAGE_A_DEEPSEEK_AUDIT_20261019.json`
- Stage B Natural 审计：`experiments/independent_comparison/reports/CONTINUATION_STAGE_B_NATURAL_AUDIT_20261019.json`
- Matched Budget 审计：`experiments/independent_comparison/reports/CONTINUATION_MATCHED_BUDGET_AUDIT_20261019.json`
- Natural Stage B 指标：`experiments/independent_comparison/metrics/continuation_natural_stage_b_deepseek_flash_20261019_v3.csv`
- Matched Budget 指标：`experiments/independent_comparison/metrics/continuation_matched_budget_deepseek_flash_20261019_v3.csv`
- 中央资源状态：`experiments/independent_comparison/manifests/continuation_resource_manager_state_20261019.json`
