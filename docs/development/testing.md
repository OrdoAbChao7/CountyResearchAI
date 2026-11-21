# 测试指南

## 1. 原则

- 测试不读取真实 API Key，不连接真实 Neo4j，不发起外网请求。
- 外部能力通过 `MockLLMClient`、静态搜索 provider、`InMemoryGraphStore` 注入。
- 新功能必须有对应测试；不为通过测试删除有价值断言。
- 测试只验证架构契约与确定性行为，不把 Mock 输出当研究结论。

## 2. 运行

```powershell
# 全量（pytest 配置默认带覆盖率）
python -m pytest

# 快速、无覆盖率
python -m pytest -q --no-cov

# 单个文件 / 单个用例
python -m pytest tests/test_orchestration.py -q --no-cov
python -m pytest "tests/test_api.py::TestResearchFlow::test_create_run_and_read_all_artifacts" -q --no-cov
```

标记：`integration`（需要真实 API，默认跳过）、`slow`。使用
`pytest -m "not integration"` 可在本地排除集成用例。

## 3. 测试地图

| 文件 | 覆盖 |
| :--- | :--- |
| `test_services_v2.py` | 定量算法（LQ/Shift-Share/HHI/CRn/CAGR）、证据、报告、Gap Radar、数字孪生、时序查询 |
| `test_agents_v2.py` | Agent 降级、工具循环、工具白名单、预算耗尽、证据校验、Supervisor、Critic、Report |
| `test_knowledge_graph.py` | 本体约束、写入门禁、实体/关系抽取、消歧、存储幂等/多跳/时点、GraphRAG、构建器 |
| `test_orchestration.py` | 路由 `Send`、事件存储、产物、检查点中断/恢复、完整运行、运行服务 |
| `test_api.py` | 健康检查、运行全流程、SSE 回放、恢复、证据/图谱/报告/仿真、错误码 |
| `test_shining_stars.py` | 数字孪生边界、时序快照/历史/差异、Star 导出契约 |
| `test_architecture_imports.py` | 分层依赖边界、旧模块已删除 |
| 既有测试 | `test_search_*`、`test_processor`、`test_evidence_store`、`test_reporting`、`test_storage`、`test_config`、`test_models`、`test_llm_*`、`test_evaluation_benchmark` 等 |

## 4. Mock 模式

- `tests/conftest.py` 提供共享 fixture：临时配置、Mock LLM、样例文档。
- 需要 `Settings` 的工厂测试显式注入 `SecretStr("test-key")`，不使用真实 Key。
- 图测试使用 `InMemoryGraphStore`；断言与 Neo4j 适配器共享同一组契约。
- API 测试用 FastAPI `TestClient`，运行在后台线程完成；SSE 用事件回放断言。
- 检查点测试使用 `InMemorySaver` + `interrupt_before=["report"]`，先中断再 `invoke(None, config)` 恢复，不依赖 SQLite 文件。

示例：构造运行上下文

```python
from county_research_ai.agents.base import AgentContext
from county_research_ai.bootstrap.container import create_services
from county_research_ai.services.evidence_service import EvidenceService

services = create_services()
ctx = AgentContext(
    run_id="run_test",
    county="安吉县",
    focus="竹产业",
    evidence=EvidenceService(),
    search=services.search,
    documents=services.documents,
    graph=services.graph,
    quant=services.quant,
)
```

## 5. 断言重点

- **Agent 自主性**：工具调用序列由脚本化 LLM 决定；越权工具被拒；预算耗尽后结果 `degraded=True`。
- **证据约束**：claim 的 `evidence_ids` 必须存在于运行证据库；伪造 ID 被清除且进入 gaps。
- **Supervisor**：任务数量、Agent 种类、去重、补充轮路由；不得出现固定流水线顺序断言。
- **Critic**：无证据结论、无效引用、覆盖缺口、弱来源；LLM 不能推翻确定性硬结论。
- **图谱**：`INFERRED/UNVERIFIED` 默认拒绝写入；`VERIFIED` 无证据拒绝；GraphRAG 默认不返回非 verified。
- **API**：202 创建、404/422、SSE 事件类型与 `stream_end`、报告下载、恢复幂等。
- **分层**：`domain` 无上层依赖；`agents` 不依赖 `orchestration`；旧模块不可导入。

## 6. 覆盖率

`pyproject.toml` 默认生成终端与 `htmlcov/` 报告。覆盖率不是唯一目标：新增 Agent/工具/图查询时，优先补行为断言而不是追求行数。

## 7. 失败排查

| 失败 | 常见原因 |
| :--- | :--- |
| `test_missing_api_key_raises` 失败 | 环境里存在真实 `LLM_API_KEY`，测试应清空环境 |
| 图谱用例找不到关系 | `as_of` 过滤或 `include_inferred` 未开启 |
| SSE 断言缺少事件 | 运行尚未完成；等待 `run_completed` 后再读 |
| 检查点恢复失败 | `thread_id` 与首次运行不一致 |
| 导入错误 | 使用了已删除的 V1 模块路径 |
