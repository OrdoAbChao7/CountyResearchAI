# County Research Agent 设计规格

## 目标

在保留现有县域产业研究 Pipeline 和内容生产命令的前提下，新增一个可解释、可测试、可追踪的 Plan-and-Execute Agent Runtime。用户可以通过 `agent` 命令提交县域研究任务，Agent 根据当前状态选择研究工具，最终生成带执行轨迹和证据校验的 Markdown 研究报告。

该改造服务于两个目标：

1. 让项目在工程上具备清晰的 Agent 核心，而不是只在固定 Pipeline 外包一层 `Agent` 类。
2. 让项目适合作为教学和面试项目，能够清楚解释规划、工具调用、状态传递、校验、停止条件和失败降级。

## 当前上下文

现有项目已经具备以下能力：

- `SearchCollector` 负责 Web / 政府数据采集。
- `DocumentProcessor` 负责去重、清洗、质量过滤和证据包构造。
- `LLMAnalyzer`、`RiseFallAnalyzer`、`LongHistoryAnalyzer` 负责不同研究模式的分析。
- `ReportRenderer`、`RiseFallReportRenderer`、`LongHistoryReportRenderer` 负责报告渲染。
- `LocalFSStorage` 负责 raw / processed / report 三层本地存储。
- Mock search、Mock LLM 和现有测试支持无外部 API 的控制流验证。

当前工作区还包含用户未提交的内容生产改动。本设计不得覆盖或回退这些改动；Agent Runtime 首期只接入研究链路，内容生产链路继续作为独立的下游 Workflow。

## 设计原则

- 增量接入：新增 Agent 层，不重写已经通过测试的研究 Pipeline。
- 结构化通信：Planner、Runtime、Tool 和 Verifier 之间使用 Pydantic 模型，而不是隐式字符串约定。
- 工具受限：Planner 只能选择注册表中的工具，不能执行任意代码或构造任意外部请求。
- 有界执行：每次运行有最大步数、非法动作处理和明确终止条件。
- 证据优先：最终报告必须能够回溯到采集文档和 URL；Mock 数据只能证明控制流，不宣称事实正确。
- 可回放：保留每次规划、工具调用、观察结果和错误的 Agent Trace。
- 可替换：真实 LLM、Mock LLM、搜索 Provider、存储实现都通过已有抽象或新增接口注入。

## 方案选择

采用 Plan-and-Execute，而不是自由形式的 ReAct。

一次循环只处理一个结构化动作：Planner 根据目标、当前状态和工具描述选择下一步工具；Executor 执行工具；Runtime 记录 Observation；Verifier 检查结果；下一次循环继续或结束。

选择该方案的原因：

- 比固定 Pipeline 多出真实的动作选择和状态驱动；
- 比自由 ReAct 更容易限制范围、复现和测试；
- 对当前已有的搜索、分析、报告组件改动较小；
- 面试时能够清楚说明 Agent 与 Workflow 的边界。

## 架构

```text
CLI
  → AgentFactory
  → AgentRuntime
      ├── Planner
      ├── ToolRegistry
      ├── Executor
      ├── Verifier
      └── AgentState / AgentTrace
              │
              ├── SearchTool
              ├── FocusDiscoveryTool
              ├── EvidencePackTool
              ├── ResearchAnalysisTool
              └── ReportTool
                      │
                      └── 复用现有 research Pipeline 组件
```

### AgentState

`AgentState` 是单次 Agent 运行的可序列化状态，至少包含：

- `request: ResearchRequest`：县名、方向、研究模式和选项；
- `status`：`pending`、`running`、`completed`、`failed`；
- `plan`：当前和历史计划动作；
- `current_step`、`steps_used`：执行位置和步数；
- `raw_docs`：原始搜索文档；
- `processed`：处理后的证据包；
- `discovery`：自动发现结果；
- `analyses`：snapshot 模式分析结果；
- `report_path`：最终报告路径；
- `observations`：每一步工具的执行记录；
- `errors`：结构化错误信息。

状态模型只保存跨步骤需要的数据，不保存完整 Prompt；完整 Prompt 和 LLM 原始响应由 Trace 按配置决定是否保存，默认只保存摘要，避免泄露密钥或无边界扩大产物。

### AgentPlanStep

Planner 每次返回一个结构化动作：

```json
{
  "tool": "search_materials",
  "reason": "当前没有原始材料，需要先检索县域产业信息",
  "arguments": {
    "county": "安吉县",
    "focus": "竹产业",
    "mode": "snapshot"
  },
  "is_final": false
}
```

动作必须满足：

- `tool` 必须存在于 `ToolRegistry`；
- `arguments` 必须是 JSON 对象；
- `reason` 非空，用于可解释性和 Trace；
- `is_final=true` 时，Verifier 仍需检查最终状态，不能仅凭 Planner 宣布成功。

### Tool 接口

每个工具提供：

- 唯一 `name`；
- 面向 Planner 的 `description`；
- 参数说明；
- `execute(state, arguments) -> ToolResult`；
- 工具级输入校验和输出摘要。

`ToolResult` 至少包含：

- `tool_name`；
- `status`：`success` 或 `error`；
- `observation`：面向下一轮 Planner 的短文本；
- `state_patch`：允许写入 `AgentState` 的受控字段；
- `error`：失败时的结构化错误信息。

工具不得直接修改不属于自己的状态字段，也不得绕过 Runtime 写最终 Trace。

## 首期工具

### `search_materials`

复用 `SearchCollector`，按 `county`、`focus` 和 `mode` 生成并采集原始文档，写入 `state.raw_docs`。没有 focus 时允许只使用县名构造查询。

成功条件：返回文档列表，或明确记录“搜索为空”并交给后续 fallback。搜索 Provider 的真实 / Mock 选择继续沿用 `create_default_pipeline()` 的配置逻辑。

### `discover_focus`

仅当请求没有 focus 且搜索结果非空时可执行。复用 `LLMAnalyzer.discover_focus()`，写入 `state.discovery` 和 `state.request.focus`。发现失败时使用现有 `特色农业` fallback，并在 Observation 中标记降级原因。

### `build_evidence_pack`

复用 `DocumentProcessor` 完成去重、清洗、质量筛选、来源排序和证据包构造，写入 `state.processed`，同时使用 `LocalFSStorage` 保存 raw / processed 数据。

### `analyze_research`

根据 `request.mode` 选择现有分析器：

- `snapshot` / `industry` → `LLMAnalyzer`；
- `rise-fall` → `RiseFallAnalyzer`；
- `long-history` → `LongHistoryAnalyzer`。

结果写入专门的状态字段。分析器内部的多任务拆分仍然保留；Agent 层负责选择“开始分析”，不重复实现具体研究 Prompt。

### `render_report`

根据模式选择现有 Renderer，写入最终报告和 `state.report_path`。报告渲染成功后交给 Verifier 检查章节和证据。

## Planner

Planner 使用现有 `LLMClient` 接口，输入包括：

- 用户研究目标；
- 当前状态摘要；
- 已完成的工具和 Observation；
- 可用工具名称、描述和参数；
- 最大剩余步数。

Planner 要求只输出一个 JSON 动作。解析策略：

1. 先解析纯 JSON；
2. 再尝试从 Markdown code fence 中提取 JSON；
3. 最后使用确定性 `FallbackPlanner` 根据状态补齐标准研究链路；
4. 如果仍无有效动作，运行失败并保留 Trace。

`FallbackPlanner` 的默认顺序是：

```text
search_materials
  → discover_focus（仅无 focus 时）
  → build_evidence_pack
  → analyze_research
  → render_report
  → finish
```

这使 Mock 模式可以跑通控制流，也使真实 Planner 即使偶尔输出非法 JSON 仍然有可解释的安全降级路径。

## Runtime 循环

伪代码：

```python
state = AgentState.from_request(request)

while state.steps_used < max_steps:
    plan_step = planner.next_step(state, registry.describe())
    state.record_plan(plan_step)

    if plan_step.tool == "finish":
        verification = verifier.verify_final(state)
        if verification.ok:
            return finalizer.complete(state)
        state.record_error(verification.error)
        continue

    tool = registry.get(plan_step.tool)
    result = tool.execute(state, plan_step.arguments)
    state.apply(result)
    state.record_observation(plan_step, result)

    verification = verifier.verify_step(state, plan_step, result)
    if not verification.ok:
        state.record_error(verification.error)
        if verification.fatal:
            return finalizer.fail(state)

return finalizer.fail(state, reason="max_steps_exceeded")
```

Runtime 不允许工具直接调用 Planner，也不允许通过异常跳过 Observation 记录。

## Verifier

Verifier 分为步骤校验和最终校验。

步骤校验至少覆盖：

- 搜索工具是否产生可处理的结果；
- focus 是否在需要时被确定；
- evidence pack 是否包含县名、方向和文档列表；
- 分析结果是否非空或有明确降级信息；
- 报告路径是否存在。

最终校验至少覆盖：

- `report_path` 非空且文件存在；
- 报告包含县名和研究方向；
- 报告包含当前模式要求的基本章节；
- 报告中存在来源 URL 或明确的数据不足标记；
- Agent 状态为 `completed` 前不存在未处理的 fatal error。

Verifier 不判断事实本身是否真实；它只验证结构和证据链完整性。事实真实性仍属于人工审查边界，并在 README 中明确说明。

## CLI 和产物

新增命令：

```bash
python -m county_research_ai.cli agent \
  --county 安吉县 \
  --focus 竹产业 \
  --mode snapshot
```

新增选项：

- `--max-steps`：最大 Agent 步数，默认 8；
- `--no-trace`：不保存详细 Trace，仅输出报告；
- `--dry-run`：只验证参数和显示预期 Agent 路径。

现有默认研究命令、`content`、`story` 和 `topic` 命令保持兼容。

每次 Agent 运行成功后生成：

```text
reports/{county}_{focus}_{date}.md
agent_traces/{county}_{focus}_{date}.json
```

Trace 至少包含请求、最终状态、每一步工具、动作理由、输入摘要、输出摘要、耗时、错误和报告路径。默认不保存 API Key，也不保存未经截断的 Prompt。

## 错误处理

- Planner JSON 错误：使用 lenient parser 和 fallback planner；
- 非法工具名：记录 `invalid_tool`，不执行；连续达到限制后失败；
- 工具异常：包装为 `ToolResult(status="error")`，保留上下文；
- 搜索为空：允许继续，但 Verifier 要求最终报告标记资料不足；
- LLM 调用失败：沿用现有 `fail_fast` 配置和 Mock / fallback 机制；
- 超过最大步数：以 `max_steps_exceeded` 失败，不生成成功状态；
- 最终校验失败：不把报告标记为 Agent 成功，可保留报告作为中间产物供人工检查。

## 测试要求

新增测试必须覆盖：

1. `AgentState` 和 `AgentPlanStep` 的模型校验与序列化；
2. ToolRegistry 的注册、查找、重复注册和未知工具错误；
3. Planner 的纯 JSON、code fence、非法 JSON 和 fallback 行为；
4. 每个工具对状态字段的正确更新；
5. Runtime 按计划执行完整 snapshot 链路；
6. 无 focus 时插入 `discover_focus`；
7. Planner 重复动作或非法动作时不会无限循环；
8. 工具异常会进入 Trace 并按策略结束；
9. Verifier 拒绝没有报告、没有县名或没有证据的结果；
10. Agent CLI 的 dry-run、Mock 全流程和 max-step 失败路径。

现有 202 个测试必须继续通过。新增 Agent 测试不得依赖真实搜索 API 或真实 LLM。

## 非目标

首期不做：

- 任意代码执行工具；
- 自动浏览器操作；
- 多 Agent 互相通信；
- 向量数据库和长期用户记忆；
- 异步分布式任务调度；
- 自动发布政策建议或事实结论；
- 重写现有 `ResearchPipeline` 的内部实现；
- 把内容生产链路强行改成同一个 Agent。

## 成功标准

改造完成后应满足：

- `agent` 命令可在无 API Key 的 Mock 模式下完整运行；
- Planner、Tool Registry、AgentState、Executor、Verifier 和 Trace 都有独立代码边界；
- Agent 运行过程中至少发生一次由 Planner 选择工具的动作决策；
- 报告和 Trace 均能落盘；
- 达到最大步数或校验失败时不会伪装成成功；
- 原有研究、内容和测试行为不被破坏；
- README 能用一张架构图解释 Agent 与旧 Pipeline 的关系；
- 项目能够作为“可解释的研究型 Agent”而不是“固定 Prompt 包装器”进行面试演示。
