# V2 迁移记录

> 范围：从固定 Workflow/CLI 报告生成器迁移为 LangGraph + FastAPI 的 Agentic Industrial Intelligence Platform。迁移在独立 worktree 中执行，未提交、未推送；原工作区未提交修改未被覆盖。

## 阶段记录

| 阶段 | 工作 | 结果 |
| :--- | :--- | :--- |
| Phase 0 · 审计 | 检查 git 状态、目录树、`pyproject.toml`、配置、核心模块与测试；按真实 import/调用关系确认旧入口 | 确认 `cli.py`、`interfaces/cli.py`、`application/workflow.py`、`pipeline.py`、旧 `agent/`、`research_agent/` 为业务 Workflow 链路；`.github/workflows/` 是 CI，保留 |
| Phase 1 · 去 Workflow | 删除 CLI/Pipeline/Workflow 与模式分支；移除 Click 与 `[project.scripts]`；保留并解耦搜索、处理、证据、LLM、报告、存储、领域模型 | 新服务层 `services/` 承接检索/证据/文档/发现/图谱/定量/机会/报告；旧能力通过 Adapter 复用 |
| Phase 2 · LangGraph | 新建 `orchestration/`：state、graph、supervisor、routing、nodes、subgraphs、checkpoint、events、artifacts、runner | `StateGraph` + `Send` 并行 + 编译子图；SQLite/InMemory 检查点 |
| Phase 3 · Multi-Agent | 新建 `agents/`：8 个专业 Agent + Critic + Report + 工具注册表 + 降级辅助 | 每个 Agent 独立提示词、工具白名单、结构化输出、预算与自主工具循环 |
| Phase 4 · 知识图谱 | 新建 `knowledge_graph/`：本体、抽取、消歧、InMemory/Neo4j 存储、GraphRAG、时序 | 13 实体 + 13 关系；证据四态；默认拒绝推断入库；GraphRAG 工具接入 Agent |
| Phase 5 · API | 新建 `api/`：FastAPI、路由、依赖、Schema、SSE | 研究/图/证据/报告/仿真 API；`uvicorn county_research_ai.api.main:app` 独立启动 |
| Phase 6 · Stars | 新建 `shining_stars/`：Gap Radar、数字孪生契约+基线、时序查询 | Star A 可用；Star B/C 契约与确定性实现落地，未校准部分明确拒绝 |
| 测试与文档 | 新增 V2 测试；更新配置、打包、容器；重写 README；补齐架构/开发/路线图文档 | 318 passed / 0 failed；Ruff 全通过；所有模块可导入 |

## 删除的旧模块

| 路径/依赖 | 原因 |
| :--- | :--- |
| `src/county_research_ai/cli.py` | 旧 Click CLI 业务入口 |
| `src/county_research_ai/interfaces/` | CLI 接口层 |
| `src/county_research_ai/application/` | `WorkflowRunner`、研究上下文与结果汇总 |
| `src/county_research_ai/modes/` | 固定 snapshot / rise-fall / long-history 模式 |
| `src/county_research_ai/pipeline.py` | `ResearchPipeline` 固定流水线 |
| `src/county_research_ai/agent/` | 旧版 Plan-and-Execute Agent（非 LangGraph，未真正并行/独立子图） |
| `src/county_research_ai/research_agent/` | 旧版 coordinator/specialized/critic 函数式「多 Agent」 |
| `click`、`[project.scripts]` | CLI 依赖与入口点 |

**未删除**：`.github/workflows/`（CI）、`search/`、`evidence/`、`processing/processor`、`llm/`、`reporting/`、`storage/`、`evaluation/`、`config/sources.yaml`、历史报告、数据目录。

## 保留与重构

| 原能力 | V2 位置 | 处理 |
| :--- | :--- | :--- |
| 搜索 provider / 深度检索 / 消歧 | `search/` + `services/search_service.py` + `infrastructure/search_adapter.py` | 保留；增加 `SearchOutcome` 降级标记与统一端口 |
| 原始采集与文档处理 | `search/collector.py`、`processing/`、`services/document_service.py` | 保留并接入 intake/supplement |
| 证据库 | `evidence/` + `services/evidence_service.py` | 增加运行级实例、快照持久化、prompt 渲染 |
| LLM 客户端与分析器 | `llm/` | 保留；V2 新增结构化 JSON 循环与 Mock 降级 |
| 报告渲染 | `reporting/` + `services/report_service.py` | 新增 `platform_report.md.j2`；保留历史模板 |
| 本地存储 | `storage/local_fs.py` | 保留；运行产物写入 `runs/` |
| 领域模型 | `domain/intelligence.py`、`domain/events.py` | 新增 V2 运行/计划/结果/批评/机会/报告模型 |
| 容器 | `bootstrap/container.py` | 重写为 `AppContainer` + `create_services` + `create_app_container` |

## 新增核心模块

```text
api/                main, dependencies, routes/{research,graph,evidence,reports,simulations}, schemas
agents/             base, tools, fallbacks, findings, registry, critic, report,
                    macro, industry, enterprise, policy, innovation, geo, quantitative, opportunity
orchestration/      state, graph, supervisor, routing, nodes, subgraphs,
                    checkpoint, events, artifacts, services, runner, question_tree
knowledge_graph/    ontology/{entities,relations,schema}, extraction/{entity,relation},
                    entity_resolution/resolver, graph_store/{base,mock_store,neo4j_store},
                    graph_rag/{retriever,query_engine}, temporal/models
services/           search, evidence, document, discovery, analytics, report,
                    graph_builder, graph_service, quant, opportunity
shining_stars/      gap_radar, digital_twin/{models,baseline_engine,service}, temporal
```

## 重大冲突与取舍

1. **旧 `research_agent` 是函数式流水线，不是真正 Agent**：没有保留其「Coordinator」外壳，而是把有价值的能力（问题树、Critic、检索）重构为 LangGraph 节点/独立 Agent；不复制旧代码冒充新架构。
2. **旧 CLI 是唯一入口，但 V2 要求 FastAPI**：直接移除 CLI 与 Click，不保留「兼容 CLI」双入口，避免业务逻辑再次耦合到命令行。
3. **图谱写入与 LLM 推测冲突**：采用「默认拒绝推断关系」的严格策略；需要推断关系时必须显式 `allow_inferred=True`，且 GraphRAG 默认不返回。
4. **Neo4j 未配置**：提供 `InMemoryGraphStore`，接口与 Neo4j 适配器一致；测试不依赖真实数据库。
5. **无 API Key**：`MockLLMClient` / Mock 搜索 / 内存图谱，全链路可运行，但输出明确标 `degraded`。
6. **机会评分不是预测模型**：Star A 用可解释启发式（缺失 0.78、弱配套 0.62、外部依赖 0.55、低 LQ 0.5，证据加减分），并在报告中注明「分析推断」。
7. **数字孪生不做未校准的大模拟器**：只提供显式假设的会计外推；Mesa 请求直接抛 `SimulationEngineUnavailable`。
8. **时序历史过滤**：修复 `InMemoryGraphStore.get_relations`，只有显式传入 `as_of` 才做时点过滤，与 Neo4j 适配器一致，历史关系可被 `entity_history` 读取。

## 测试结果

执行：

```powershell
python -m pytest -q --no-cov
```

结果（2026-11-19）：

```text
318 passed in 4.62s
```

新增测试文件：

- `tests/test_services_v2.py`（20）：定量算法、证据、报告、缺口雷达、数字孪生、时序。
- `tests/test_agents_v2.py`（19）：Agent 降级、工具循环、白名单、预算、证据校验、Supervisor、Critic、Report。
- `tests/test_knowledge_graph.py`（31）：本体约束、写入门禁、消歧、抽取、存储、GraphRAG、构建器。
- `tests/test_orchestration.py`（11）：路由、事件、产物、检查点中断/恢复、完整运行、运行服务。
- `tests/test_api.py`（13）：健康检查、运行全流程、SSE、证据、图谱、报告、仿真、错误码。
- `tests/test_shining_stars.py`（9）：数字孪生边界、时序快照/历史/差异、Star 导出契约。

保留并修复的旧测试：`test_deep_retrieval`、`test_llm_analyzer`、`test_search_web` 等在无真实 Key 环境下改为显式注入测试 Key 或补足 Mock 候选，未删除有价值断言。

## 未完成事项

- Neo4j 真实集群的集成测试（当前仅有适配器与 InMemory 等价测试）。
- 多进程/分布式检查点（当前 SQLite 单进程多线程）。
- Mesa/系统动力学/CGE 仿真校准与验证。
- Graphiti 版本链接入；当前仅预留时序接口。
- 企业名录、专利、园区企业的稳定数据源接入。
- 前端界面（V2 保留 API，未新增前端）。

## 下一步

1. 接入真实县域名录与企业/专利数据源，提升企业 Agent 与图谱覆盖。
2. 用标注数据校准 Gap Radar 评分与 Critic 阈值。
3. 将 SQLite 检查点抽象为可插拔后端（PostgreSQL/Redis），支持多副本 API。
4. 为 Star B 建立校准数据集与情景验证协议，再决定是否引入 Mesa。
5. 为 Star C 增加版本节点/双时态存储，支持「某年某关系首次出现/消失」查询。
