# CountyResearchAI V2 架构

> 状态：V2 主架构已落地并通过测试。本文记录设计决策、模块边界与已知边界；逐阶段迁移记录见 [MIGRATION_V2.md](MIGRATION_V2.md)。

## 1. 从 V1 到 V2

| 维度 | V1 | V2 |
| :--- | :--- | :--- |
| 业务入口 | Click CLI + `WorkflowRunner` | FastAPI（唯一业务入口） |
| 编排 | 固定 `ResearchPipeline` / 模式分支 | LangGraph `StateGraph` + Supervisor 动态路由 |
| 「Agent」 | 固定函数序列与角色化分析器 | 独立子图、独立提示词/工具/结构化输出，可自主选工具与结束 |
| 证据 | 报告脚注与松散的 evidence store | 运行级 `EvidenceService`，结论必须绑定 Evidence ID |
| 图谱 | 无 | Neo4j/InMemory + 本体 + GraphRAG + 证据写入门禁 |
| 机会发现 | 无 | Star A `GapRadarService` |
| 仿真 | 无 | Star B 契约 + 确定性基线引擎（Mesa 明确不可用） |
| 时序 | 无 | Star C as-of / diff / history 接口 |
| 运行恢复 | 无 | SQLite 检查点 + 运行产物快照 |

**删除的旧业务模块**：`cli.py`、`interfaces/`、`application/`、`modes/`、`pipeline.py`、`agent/`（旧版 Plan-and-Execute）、`research_agent/`。`.github/workflows/` CI 保留，未作为业务 Workflow 删除。

**保留并复用的能力**：搜索源/适配器、深度检索与消歧、原始采集、文档处理、证据存储、兼容 OpenAI 的 LLM 客户端、报告渲染、本地存储、领域模型、评测基准。

## 2. 分层

```text
api/            业务入口与传输契约（FastAPI、SSE）
bootstrap/      组合根：Settings → 服务 → 图存储 → 运行服务
orchestration/  LangGraph 装配、状态、监督、路由、节点、检查点
agents/         专业 Agent、Critic、Report、工具白名单
services/       可复用能力（搜索/证据/文档/发现/图谱/定量/机会/报告）
knowledge_graph/本体、抽取、消歧、存储适配器、GraphRAG、时序
shining_stars/  Star A/B/C 的领域契约与确定性实现
domain/         共享模型与事件
infrastructure/ 搜索端口适配器
search/ llm/ reporting/ storage/   既有能力层
```

依赖方向：`api → orchestration → agents → services → knowledge_graph/domain`。`domain` 不依赖任何上层；`knowledge_graph` 不依赖 agents/orchestration；`services` 不依赖 api/orchestration。以上边界由 `tests/test_architecture_imports.py` 自动检查。

## 3. 多 Agent 运行流

1. **intake**：`SearchService.collect` 采集资料；无 focus 时由 `DiscoveryService` 发现方向；`EvidenceService.ingest` 抽取结构化证据；`seed_core_graph` 写入县域/产业种子节点；`RunArtifacts` 持久化文档与证据。
2. **supervise**：`Supervisor.plan` 读取自然语言目标、问题树、上一轮结果与 Critic 缺口，输出 `ResearchPlan`。LLM 不可用时退化为确定性问题树/关键词路由，并标注 `planner_source="deterministic"`。
3. **并行分发**：`dispatch_specialists` 为每个任务生成 `Send(node, {"task": ...})`，每个专业 Agent 是一个编译后的 `StateGraph` 子图。子图 `results` 通过 `operator.add` reducer 汇入父图。
4. **aggregate**：清洗、去重、汇总 `AgentResult`。
5. **critic**：确定性审计 + 可选 LLM 审计。校验每条 claim 的证据 ID、弱来源、未知证据、覆盖维度、证据冲突；LLM 不能推翻确定性审计的硬结论。
6. **supplement**：若审计不充分、仍有轮次预算且存在补充查询，执行定向检索、证据入库并回到 supervise；否则进入图谱构建。
7. **build_graph**：`KnowledgeGraphBuilder` 只写入通过证据门禁的 `verified` 关系；`allow_inferred=False`（默认）时推断关系拒绝入库。
8. **opportunity**：机会 Agent 调用 `gap_radar_scan`，叠加 Critic 审计结果；所有机会强制为 `PENDING` / `INFERRED`，不会标为 `VERIFIED`。
9. **report**：`ReportAgent` 只组织既有结论，不引入新事实；确定性模板可在无 LLM 时生成完整报告；写入 `report.md`、`report.json`、`opportunities.json`。
10. **finalize**：写入运行状态、证据数量与完成事件。

### 状态与检查点

`ResearchState`（TypedDict）只保存 JSON 可序列化数据；运行期服务、证据库、事件发射器放在 `RunnableConfig.configurable`，不进入检查点。`thread_id = run_id`，SQLite 检查点位于 `{runs_dir}/checkpoints.sqlite`。`RunArtifacts` 单独保存证据/文档/报告，恢复时重新绑定证据库。

## 4. 专业 Agent

| Agent | 职责 | 典型工具 | 输出模型 |
| :--- | :--- | :--- | :--- |
| `macro` | 经济总量、增长、财政、人口 | `search_industry`、`evidence_search`、`graph_query` | `MacroFindings` |
| `industry` | 产业结构、环节、链条、集群 | `search_industry`、`graph_supply_chain`、`graph_clusters` | `IndustryFindings` |
| `enterprise` | 龙头企业、规上企业、企业关系 | `search_web`、`graph_enterprise_relations`、`graph_multi_hop` | `EnterpriseFindings` |
| `policy` | 规划、政策、补贴、扶持 | `search_web`、`graph_policy_links`、`evidence_summary` | `PolicyFindings` |
| `innovation` | 技术、专利、研发平台、产学研 | `search_web`、`graph_multi_hop`、`evidence_search` | `InnovationFindings` |
| `geo` | 园区、土地、交通、区位 | `graph_clusters`、`graph_park_enterprises`、`search_web` | `GeoFindings` |
| `quantitative` | 区位熵、Shift-Share、HHI、CRn | `quant_*`、`quant_from_evidence` | `QuantFindings` |
| `opportunity` | 缺失环节、弱配套、外部依赖 | `gap_radar_scan`、`graph_supply_chain` | `OpportunityFindings` |

每个 Agent：
- 有独立 `system_prompt`，明确职责边界与「不得编造」约束；
- 只能调用 `AgentSpec.tools` 白名单中的工具，越权调用会被拒绝并记录 `tool_not_allowed`；
- 有 `max_steps` / `max_llm_calls` 预算，超限后使用已有观察生成降级结果；
- 输出统一为 `AgentResult { summary, claims, evidence_ids, findings, gaps, confidence, degraded }`；
- LLM 循环输出单个 JSON 动作（`tool` / `finish`），解析失败会重试，预算耗尽则降级；
- 降级结果仍引用真实 Evidence ID，无证据 claim 标为 `unverified` 并进入 gaps。

`quantitative` 的所有数学由 `QuantService` 的 Python 算法完成；LLM 只能选算法、给参数与解释。

## 5. 知识图谱

- 13 类实体：County、Industry、IndustrySegment、Enterprise、Product、Material、Technology、IndustrialPark、Policy、Institution、Patent、Indicator、Evidence。
- 13 类关系：HAS_INDUSTRY、CONTAINS、BELONGS_TO、LOCATED_IN、PRODUCES、USES_INPUT、SUPPLIES_TO、COOPERATES_WITH、COMPETES_WITH、SUPPORTS、DEVELOPS、APPLIED_IN、OWNS。
- 每条关系支持 `source/target` ID、`source_evidence_id`、`evidence_ids`、`confidence`、`verification_status`、`valid_from/valid_to/observed_at`、`quote`。
- `GraphWritePolicy`：`VERIFIED` 必须有证据；`INFERRED/UNVERIFIED` 默认拒绝写入（`allow_inferred=True` 才能显式开启）。
- 默认 `InMemoryGraphStore`；Neo4j 适配器使用参数化 Cypher，未配置时自动退回内存实现。
- GraphRAG 查询默认只读 `verified` 关系；需要时可显式 `include_inferred`。
- 完整设计见 [docs/architecture/knowledge-graph-design.md](docs/architecture/knowledge-graph-design.md)。

## 6. 降级与失败策略

| 场景 | 行为 |
| :--- | :--- |
| 无 LLM Key | `MockLLMClient`；Agent 走确定性工具序列并标 `degraded` |
| 无搜索 Key | Mock/静态搜索；`SearchOutcome.degraded=True` |
| Neo4j 不可用/未配置 | `InMemoryGraphStore` |
| SQLite 检查点不可用 | `InMemorySaver`，`checkpoint_backend="memory"` |
| LLM 输出无法解析 | 重试/降级，不伪造结论 |
| Agent 抛异常 | 该 Agent 返回失败 `AgentResult`，运行继续 |
| 报告 LLM 失败 | 确定性报告草稿 |
| 仿真引擎未校准 | 明确 `SimulationEngineUnavailable`，不返回伪结果 |

所有降级都在事件流与结果中可见，不静默掩盖。

## 7. 质量门禁

- 不复制旧代码伪造新架构：删除模块均有调用图审计记录（见 MIGRATION_V2.md）。
- 不建立空目录/空类：每个 Agent、服务、适配器都有实际实现与测试。
- Agent 不是普通函数改名：每个 Agent 是独立子图节点，有自主工具循环、预算与结构化输出。
- Supervisor 不承载业务：只做问题拆解、任务分配与轮次控制。
- Agent 不能自由写图：所有图写入经过 `GraphWritePolicy` 与 `KnowledgeGraphBuilder`。
- 不破坏既有采集/证据：`search/`、`evidence/`、`processor`、`storage` 保留并复用。
- 量化由 Python 完成；LLM 不参与计算。
- 新功能有测试；Mock 测试不依赖真实 Key/Neo4j。

## 8. 已知边界与下一步

- Star B 只提供会计基线；Mesa/系统动力学/CGE 需要校准数据、行为规则与验证方案。
- Star C 目前基于关系时效字段做 as-of 查询；完整版本链需要 Neo4j 版本节点或 Graphiti。
- 机会评分是可解释的启发式，不是经训练的预测模型；需实地调研与专家复核。
- 企业级数据、专利数据、园区企业名录的接入仍是数据覆盖瓶颈。
- 多进程部署时 SQLite 检查点需要替换为 PostgreSQL/Redis 检查点；当前按单进程多线程设计。

路线图见 [docs/roadmap/shining-stars.md](docs/roadmap/shining-stars.md)。
