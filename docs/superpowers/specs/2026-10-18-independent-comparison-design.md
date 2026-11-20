# Independent Comparison 实验系统设计

## 1. 目的与判定原则

该系统比较三种自动化研究方式：A Traditional Search Researcher、B General-Purpose AI Researcher、C CountyResearchAI Researcher。D Ground Truth Builder、E Blind Judges、F Independent Auditor 是验证角色，不是被比较的研究组。

系统只报告可由原始运行产物重算的结果。Mock、静默回退、来源无法访问、Provider Usage 缺失、资源租约未结算、跨组输入泄漏和运行中途修改冻结配置都会使对应运行不进入质量主分析，并在失败统计中保留。

## 2. 实验分组

### Experiment 1：端到端研究能力

A/B/C 使用相同地区、任务、输出格式、截止条件、模型（可行时）和搜索资源预算，但自行规划和检索。A 只使用传统搜索脚本；B 使用通用联网研究脚本；C 使用项目真实研究流程。三组均不能读取 Ground Truth 或其他组报告。

### Experiment 2：相同输入下的分析能力

A/B/C 接收同一份冻结文档快照，比较事实抽取、口径识别、证据核验、综合和因果分析。该实验隔离检索质量，不能把搜索差异解释为架构增益。

正式地区至少 6 个、每组每地区计划 3 次；免费资源不足时优先完成少量完整可审计样本，不用模拟输出补齐规模。

## 3. 数据流

```text
Frozen Protocol
      |
      +--> D: independent source collection --> Ground Truth freeze
      |
      +--> A/B/C isolated runners --> RunManifest + raw docs + reports + usage
      |
      +--> anonymous report pack --> E1/E2 blind judges
      |
      +--> all manifests + hashes + failures --> F auditor
      |
      +--> metrics calculator --> figures --> FINAL_REPORT.md
```

每次运行建立独立目录，写入 `manifest.json`、请求记录、原始搜索/抓取内容、LLM 响应、最终报告、错误和 checkpoint。报告包只使用匿名组名。

## 4. Resource Manager

Resource Manager 提供 `reserve(request) -> Lease`、`settle(lease, usage)`、`fail(lease, reason)` 和 `snapshot()`。持久化使用 SQLite，事务内检查 Provider/Model/资源类型预算并写入 lease；所有多进程调用都通过数据库锁保证原子性。

资源账本至少包含 provider、model、kind、status、requested_units、settled_units、currency、billing_class、run_id、lease_id、started_at、finished_at 和 error。`billing_class` 取 `free_confirmed`、`paid`、`unknown`；`unknown` 默认拒绝真实调用，除非显式的探针策略允许且上限为 1。

Gemini 使用实际响应 usage；Tavily 使用请求类型对应的 credit 估算并把账户实时余额未知写入状态；DeepSeek 适配器实现接口但默认 `disabled_by_policy`。

## 5. Provider 与严格真实性

LLM Adapter 统一返回内容、模型、prompt/completion/total token、request id 和原始响应哈希。Search Adapter 返回 RawDoc、请求数、credit 计量、URL、来源元数据和原始响应快照。任何缺失 Usage 的真实响应标为 `usage_unknown`，不填充硬编码 token。

`StrictRealContainer` 在以下情况抛错并终止该运行：Key 缺失、Provider 初始化异常、HTTP 错误重试耗尽、实例类型为 Mock、配置模型与冻结模型不一致、发生未授权 Provider 切换。实验层不捕获后回退 Mock。

## 6. 隔离实现

A/B 每次使用独立 Python 子进程、独立临时工作目录、独立环境变量白名单、只读的冻结任务输入和独立输出目录。C 也使用独立进程，入口只接收冻结运行配置并调用 `CountyResearchAI` 的真实流程。禁止把 Ground Truth、评测标准或另一组报告放进进程环境和 Prompt。

Codex 子代理可用于开发审阅，但正式研究结果必须由可复现的运行器和保存的输入/输出产生，不能把同一 Prompt 内的多个角色称为独立实验代理。

## 7. Ground Truth 与盲评

Ground Truth 是逐 Claim 的 JSONL，字段包括 Claim、Source、URL、Date、Region、Metric、Unit、Evidence Excerpt、Confidence、Verification Status。两个独立核查上下文分别从公开权威来源提取和复核，争议项保留 `DISPUTED`，冻结后禁止按报告结果修改。

Blind Judge 只读取匿名报告和冻结 Rubric，至少两个独立评分上下文分别评估事实准确、关键事实覆盖、来源可靠、产业逻辑、历史解释、因果分析、结构完整、风险分析和无依据推断。差异超过预设阈值时启动第三个裁判。

## 8. 指标与统计

- 事实准确率：正确声明数 / 可核查声明数。
- 关键事实覆盖率：正确覆盖的 GT Claim 数 / GT Claim 总数。
- 证据支持率：有真实来源实质支持的声明数 / 需核验声明数。
- 错误分类：已证实错误、无来源、来源不匹配、行政区划错、统计口径错、无法核实。
- 深度：冻结 Rubric 的结构化评分，不使用模型自评作为唯一依据。
- 成本：端到端墙钟时间、实际 Provider token、Tavily credits、请求数、失败数。
- AI Report-Based QA：独立答题 Agent 只读取报告，结果不解释为人类理解能力。

报告同时输出有效运行、失败运行和排除理由；不只保留表现好的样本。小样本使用 bootstrap/配对差异并明确不确定性，不默认声称统计显著。

## 9. 消融

只有现有代码能以显式配置可靠关闭模块时，才运行 Full、Without QuestionTree、Without ResearchCritic、Without FactVerifier、Without Specialized Role Analysis。每个消融必须保留相同任务、模型和搜索预算；不能通过伪造退化输出模拟关闭。

## 10. 失败与恢复

运行状态为 `PLANNED -> RUNNING -> VALID/INVALID/FAILED/BLOCKED`。每个资源租约必须在正常结束、异常或进程中断时结算/保守扣除。Checkpoint 保存冻结配置哈希、已完成阶段、文件哈希和下一步动作，恢复时拒绝配置漂移。

## 11. 测试策略

新增组件遵循 TDD：先写失败测试，再实现最小行为。重点测试并发预留、超预算拒绝、重复结算、Provider Usage 解析、Mock 污染、匿名化、配置哈希漂移、恢复和指标边界。真实 API 只通过明确标记的集成测试执行，不让单元测试消耗配额。
