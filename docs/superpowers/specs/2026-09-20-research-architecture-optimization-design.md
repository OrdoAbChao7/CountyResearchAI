# 默认分支研究架构优化设计

## 目标

默认分支 `master` 定位为纯县域研究产品，只提供固定 Workflow、研究 Agent、资料采集、证据处理、研究分析和 Markdown 报告。视频与短视频内容生产按《视频能力分支隔离设计》迁移到 `codex/video-content` 后，不再参与默认分支架构。

本次优化在保留外部行为的前提下重构内部边界，解决以下问题：

- `ResearchPipeline` 同时承担模式路由、阶段编排、错误处理、依赖访问和结果兼容，文件过大；
- Workflow 与 Agent 工具重复实现搜索、证据处理、模式分派和报告生成；
- 三种研究模式通过集中式条件分支扩展，新增模式需要修改多个位置；
- CLI 直接装配并调用多个业务组件，命令定义与应用逻辑耦合；
- 业务方法反复读取全局 Settings 和项目路径，不利于测试及替换基础设施；
- 单一 `models.py` 混合请求、证据、分析和报告模型，领域边界不清；
- 部分流程会原地修改请求模型，状态变化难以审计。

## 设计原则

1. 外部兼容优先：保留 CLI、环境变量、报告文件名、数据目录和常用 Python 导入路径。
2. 一个业务能力只有一个实现：Workflow 和 Agent 共享应用用例，不复制业务流程。
3. 依赖指向领域核心：应用层依赖端口，基础设施实现端口，领域层不依赖外部 SDK。
4. 渐进迁移：每一步保持测试可运行，不进行一次性整体重写。
5. 显式状态：请求归一化、阶段结果和错误上下文通过类型表达，不依赖隐式全局状态。
6. 模式开放扩展：研究模式通过注册表接入，不在多个模块增加条件分支。

## 非目标

本次不做：

- Web UI、HTTP API 或任务队列；
- 多 Agent 协作；
- 向量数据库和长期记忆；
- 云存储或数据库迁移；
- Prompt 内容重写；
- 报告章节和文件名改版；
- 搜索供应商或 LLM 供应商功能扩展；
- 视频和内容生产架构优化。

## 目标架构

```text
interfaces
└── cli
      │
      ▼
bootstrap
└── AppContainer / create_application
      │
      ├── WorkflowRunner ──────────────┐
      └── AgentRuntime                 │
                                      ▼
application
└── ResearchApplication
      ├── collect_materials
      ├── discover_focus
      ├── build_evidence
      ├── analyze
      └── render_report
              │
      ┌───────┴────────┐
      ▼                ▼
domain             ports
├── requests        ├── SearchPort
├── evidence        ├── AnalysisPort
├── analyses        ├── StoragePort
├── reports         └── ReportPort
└── modes
      │
      ▼
infrastructure
├── search
├── llm
├── storage
└── reporting
```

项目继续使用单个 Python 包，不引入多包仓库。目标是建立清晰依赖方向，而不是机械追求目录层级。

## 模块结构

建议的默认分支源码结构：

```text
src/county_research_ai/
├── interfaces/
│   └── cli.py
├── bootstrap/
│   └── container.py
├── application/
│   ├── research.py
│   ├── workflow.py
│   ├── context.py
│   └── results.py
├── domain/
│   ├── requests.py
│   ├── evidence.py
│   ├── analyses.py
│   ├── reports.py
│   └── modes.py
├── ports/
│   ├── search.py
│   ├── analysis.py
│   ├── storage.py
│   └── reporting.py
├── modes/
│   ├── base.py
│   ├── snapshot.py
│   ├── rise_fall.py
│   ├── long_history.py
│   └── registry.py
├── agent/
├── infrastructure/
│   ├── search/
│   ├── llm/
│   ├── storage/
│   └── reporting/
├── config.py
├── exceptions.py
├── cli.py
├── models.py
└── pipeline.py
```

迁移期保留顶层 `cli.py`、`models.py` 和 `pipeline.py` 作为兼容入口。它们只做重新导出或薄包装，不再承载核心实现。目录迁移可以分阶段完成，最终目录名以依赖边界清晰为标准。

## 领域层

领域层包含稳定的数据结构和规则，不读取 Settings、不访问文件系统、不调用 LLM 或搜索 API。

### 请求模型

`ResearchRequest` 保持现有 JSON 字段。新增统一的模式归一化函数，将 `industry` 等别名转换为标准模式。归一化返回新请求，不原地修改用户传入对象。

### 证据模型

`RawDoc`、`ProcessedData` 和来源元数据归入 evidence 模块。证据模型继续保留现有序列化结构，避免历史缓存失效。

### 分析与报告模型

snapshot、rise-fall、long-history 分析模型按职责拆分。`ResearchReport` 和 `ReportSection` 独立于具体 Renderer。

迁移期间，`county_research_ai.models` 重新导出这些类，现有导入保持可用。

## 应用层

### ResearchApplication

`ResearchApplication` 是 Workflow 和 Agent 共用的业务入口，提供细粒度用例：

```python
collect_materials(context) -> ResearchContext
discover_focus(context) -> ResearchContext
build_evidence(context) -> ResearchContext
analyze(context) -> ResearchContext
render_report(context) -> ResearchRunResult
```

每个用例：

- 只执行一个业务阶段；
- 接收显式上下文和注入的依赖；
- 返回更新后的上下文或最终结果；
- 不读取全局 Settings；
- 不直接决定下一阶段；
- 使用统一的领域异常附带阶段和上下文。

### ResearchContext

`ResearchContext` 保存单次运行的跨阶段状态：

- 归一化请求；
- 县名与研究方向；
- 原始文档；
- 自动发现结果；
- 处理后证据；
- 模式分析结果；
- 报告和报告路径。

它不保存 API Key、完整 Prompt 或外部客户端。

### WorkflowRunner

WorkflowRunner 按固定顺序调用 ResearchApplication：

```text
collect
→ discover（仅缺少 focus）
→ evidence
→ analyze
→ report
```

WorkflowRunner 只负责顺序、阶段开关和 fail-fast 策略。具体阶段逻辑不在 Runner 内实现。

## 模式注册表

每个研究模式实现统一 `ResearchModeHandler`：

```python
class ResearchModeHandler(Protocol):
    name: str
    default_focus: str

    def analyze(self, context: ResearchContext) -> ModeAnalysis: ...
    def render(self, context: ResearchContext) -> RenderedReport: ...
```

`ModeRegistry` 在启动时注册：

- `snapshot`；
- `rise-fall`；
- `long-history`。

搜索关键词中的模式差异通过标准模式名传给 SearchPort。应用层不再使用多个 `if request.mode == ...` 分支。未知模式在入口归一化阶段立即失败。

## Agent 集成

Agent Runtime、Planner、Registry、Verifier 和 Trace 保留现有边界。Agent 的五个工具改为 ResearchApplication 的薄适配器：

- `search_materials` → `collect_materials`；
- `discover_focus` → `discover_focus`；
- `build_evidence_pack` → `build_evidence`；
- `analyze_research` → `analyze`；
- `render_report` → `render_report`。

AgentState 与 ResearchContext 通过单一适配函数转换。工具不得再次实现缓存、模式路由、报告拼接或文件命名。

Planner 仍可决定下一动作，但不能修改用户请求的研究模式。已完成动作由状态校验和 fallback 防止重复执行。

## 端口与基础设施

### SearchPort

负责按县名、方向和标准模式返回 RawDoc 列表。现有 SearchCollector 作为基础设施实现。

### AnalysisPort

应用层只依赖模式 Handler。具体 LLMAnalyzer、RiseFallAnalyzer 和 LongHistoryAnalyzer 由 Handler 组合。

### StoragePort

统一 raw、processed 和 report 的加载与保存契约。LocalFSStorage 继续作为默认实现，现有目录结构不变。

### ReportPort

模式 Handler 使用具体 Renderer，但向应用层返回统一的 `RenderedReport`，包含兼容 ResearchReport、Markdown 和建议文件名所需数据。

### AppContainer

`AppContainer` 是唯一生产环境装配点：

- 加载一次 Settings；
- 创建 LLM 和 Search 客户端；
- 创建 Storage、Processor、Analyzers 和 Renderers；
- 注册模式 Handler；
- 构建 ResearchApplication、WorkflowRunner 和 Agent Runtime。

业务对象构造期间不再隐式调用 `get_settings()`。为兼容现有调用，旧工厂函数委托给 AppContainer。

## CLI

默认分支 CLI 只提供：

- 显式 `workflow`；
- 显式 `agent`；
- 兼容旧的无子命令 Workflow 调用。

CLI 负责：

- 参数解析；
- 请求归一化错误展示；
- 调用 AppContainer；
- 输出报告和 Trace 路径；
- 将领域异常映射为退出码。

CLI 不直接创建 Analyzer、Storage、Content Pipeline 或 Renderer，不读取报告内容生成业务预览以外的派生数据。

## 错误处理

保留 `CountyResearchAIError` 层级，统一阶段错误为带上下文的 `ResearchStageError`：

```text
code
stage
message
retryable
context
cause
```

规则：

- 配置错误和未知模式在运行前失败；
- 搜索、LLM 和存储错误保留原异常为 cause；
- fail-fast 由 WorkflowRunner 决定；
- Agent Runtime 将阶段错误转换为 ToolResult 和 Trace；
- 不把真实 API Key、完整请求头或未截断 Prompt写入错误上下文。

## 缓存和产物兼容

保持以下路径和格式：

- `data/raw/{county}/{date}/raw_docs.json`；
- `data/processed/{county}/{focus}.json`；
- `reports/{county}_{focus}_{date}.md`；
- `agent_traces/...`。

缓存读取继续兼容现有 Pydantic JSON。模式迁移不得使历史 processed 文件失效。报告文件名继续使用现有模板和日期逻辑。

## 兼容性契约

必须保持：

- 现有 Workflow 和 Agent CLI 参数；
- `industry` 作为 `snapshot` 别名；
- 三种研究模式；
- `.env` 和 `settings.yaml` 键名；
- 报告及数据路径；
- `county_research_ai.models` 的研究模型导入；
- `create_default_pipeline()` 和 `ResearchPipeline.run()` 的基本调用方式；
- 无 API Key 时 Mock 降级；
- Gemini/OpenAI 兼容客户端配置。

允许改变：

- 内部文件位置；
- 私有方法和未文档化内部导入；
- Pipeline 内部实现；
- 测试 fixture 的装配方式；
- 日志措辞，但保留阶段、模式和错误定位信息。

## 迁移阶段

### 阶段 0：视频分支隔离

按《视频能力分支隔离设计》保存视频源码并清理默认分支。只有 `master` 的纯研究测试通过后才开始架构重构。

### 阶段 1：行为锁定

增加 characterization tests，覆盖：

- 三种模式的请求到报告路径；
- 自动发现 focus；
- 缓存与 `--no-cache`；
- fail-fast；
- Workflow/Agent 同一阶段产物的一致性；
- CLI 兼容入口；
- Mock 和真实客户端装配选择。

### 阶段 2：领域和上下文

引入标准模式、ResearchContext 和 ResearchRunResult。拆分领域模型，并通过 `models.py` 兼容导出。

### 阶段 3：应用用例

从现有 Pipeline 和 Agent Tools 提取五个共享用例。先让旧 Pipeline 委托给用例，保持 API 不变。

### 阶段 4：模式注册表

将 snapshot、rise-fall、long-history 分派迁移到 Handler 和 Registry。删除 Pipeline 与 Agent Tools 的重复模式条件。

### 阶段 5：编排迁移

WorkflowRunner 使用共享用例；Agent Tools 变成薄适配器。验证两条入口在相同请求下使用同一模式 Handler。

### 阶段 6：统一装配

引入 AppContainer，集中构造生产依赖。旧工厂函数转为兼容委托。移除业务层隐式 Settings 读取。

### 阶段 7：CLI 和兼容层瘦身

拆分 CLI 命令定义和输出展示。顶层 `cli.py`、`models.py`、`pipeline.py` 保留兼容入口，删除重复实现。

### 阶段 8：清理和文档

删除死代码，更新 README 和架构图，运行全部验证。

## 测试策略

每个阶段使用测试先行：

1. 先增加会失败的行为或契约测试；
2. 实现最小迁移；
3. 运行相关测试；
4. 运行全量测试；
5. 再删除被替代代码。

测试层次：

- domain：模式归一化和模型兼容；
- application：五个用例的状态转换；
- modes：每个 Handler 的分析和渲染分派；
- orchestration：Workflow 固定顺序与阶段策略；
- agent：工具只委托应用用例、Runtime 停止和 Trace；
- infrastructure：LocalFS、SearchCollector 和兼容 LLM 客户端；
- CLI：显式入口、兼容入口、退出码和 dry-run；
- end-to-end：Mock 全流程，以及受控的真实 Gemini smoke test。

## 静态约束

在现有 Ruff、mypy 和 pytest 基础上增加架构约束：

- domain 不得导入 config、infrastructure、agent 或 Click；
- application 不得导入具体 Search/LLM/Storage 实现；
- Agent Tools 不得直接导入具体 Analyzer 或 Renderer；
- CLI 不得直接导入具体基础设施实现；
- Pipeline 兼容层不得新增业务逻辑。

这些约束优先通过简单的 import contract 测试实现，不新增大型架构检查依赖。

## 验证要求

- 默认分支不存在视频和内容生产引用；
- 全部默认分支测试通过；
- Ruff 通过；
- reporting 和新增 domain/application/ports 模块通过 mypy；
- Workflow 和 Agent dry-run 通过；
- snapshot、rise-fall、long-history 的 Mock 端到端测试通过；
- Gemini snapshot 和 Agent smoke test 至少各成功一次，外部 429/503 与代码失败分开报告；
- `git diff --check` 通过；
- README 架构、CLI 和实际代码一致。

## 完成标准

- Workflow 与 Agent 共用同一个 ResearchApplication；
- Agent Tools 不再复制缓存、处理、模式路由和报告逻辑；
- 三种模式全部通过 ModeRegistry 分派；
- Settings 只在装配边界加载，应用业务代码使用注入配置；
- `ResearchPipeline`、CLI 和 `models.py` 成为兼容薄层，不再是核心实现容器；
- 默认分支只包含县域研究产品；
- 外部兼容性契约全部通过测试；
- 文档能够清晰解释领域、应用、端口、基础设施、Workflow 和 Agent 的关系。
