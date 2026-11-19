# 开发环境

## 1. 前置条件

| 项 | 要求 |
| :--- | :--- |
| Python | 3.10+（CI 使用 3.12，本地验证使用 3.13） |
| 包管理 | `pip` + `venv`（项目未使用 Poetry） |
| 可选 | Neo4j 5.x（仅图谱后端为 `neo4j` 时需要） |
| 可选 | Node.js（本项目无前端，暂不需要） |

## 2. 安装

```powershell
git clone https://github.com/OrdoAbChao7/CountyResearchAI.git
cd CountyResearchAI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

需要真实 Neo4j 适配器时：

```powershell
python -m pip install -e ".[dev,graph]"
```

> Windows PowerShell 若提示脚本被禁止，可执行
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`，或直接使用
> `.\.venv\Scripts\python.exe -m ...` 调用解释器。

## 3. 配置

```powershell
Copy-Item .env.example .env
```

- `.env` 只放敏感信息与部署覆盖项；非敏感默认值在 `config/settings.yaml`。
- **全部留空也能启动**：`bootstrap/container.py` 会装配 Mock LLM、Mock 搜索与内存图存储，运行结果标 `degraded=True`。
- 真实运行需至少配置 `LLM_API_KEY` 与一个搜索 Key（`TAVILY_API_KEY` / `SERPER_API_KEY` / `BING_API_KEY`）。
- 关键变量：

| 变量 | 作用 |
| :--- | :--- |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` | OpenAI 兼容 LLM |
| `SEARCH_PROVIDER` + 对应 Key | 搜索 provider |
| `GRAPH_BACKEND` | `memory`（默认）/ `neo4j` |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` / `NEO4J_DATABASE` | Neo4j 连接 |
| `API_HOST` / `API_PORT` / `API_MAX_CONCURRENT_RUNS` | API 监听与并发 |
| `AGENT_MAX_STEPS` / `AGENT_MAX_LLM_CALLS` / `AGENT_MAX_ROUNDS` | Agent 预算覆盖 |
| `RUNS_DIR` | 运行产物与检查点目录 |
| `DATA_DIR` / `REPORTS_DIR` | 原始数据/历史报告目录 |

Neo4j 连接失败不会阻止启动：`create_graph_store` 会记录告警并回退到 `InMemoryGraphStore`，`/healthz` 的 `graph_backend` 会反映实际后端。

## 4. 启动 API

```powershell
uvicorn county_research_ai.api.main:app --reload --port 8000
```

- OpenAPI：<http://127.0.0.1:8000/docs>
- 健康检查：`GET /healthz`（LLM/搜索是否 Mock、图后端、检查点后端）

提交一次运行：

```powershell
$body = @{ county = "安吉县"; focus = "竹产业"; objectives = @("识别补链机会") } | ConvertTo-Json
$run = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/research/runs -ContentType "application/json" -Body $body
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/research/runs/$($run.run_id)"
```

订阅 SSE：

```powershell
curl.exe -N "http://127.0.0.1:8000/api/research/runs/$($run.run_id)/events"
```

## 5. 运行产物

```text
data/runs/
├── checkpoints.sqlite        # LangGraph 检查点（thread_id = run_id）
└── {run_id}/
    ├── run.json              # ResearchRunRecord
    ├── events.jsonl          # 事件流
    ├── evidence.json         # 证据快照
    ├── documents.json        # 文档快照
    ├── report.md / report.json
    └── opportunities.json
```

删除单个运行目录即可清理其产物；检查点文件会保留历史线程，按需整体删除。

## 6. 代码质量

```powershell
ruff check src tests
python -m pytest -q --no-cov
```

- Ruff 配置在 `pyproject.toml`；FastAPI 路由的 `B008` 已按目录豁免。
- 类型检查使用 `mypy src`（非严格模式，允许第三方缺失类型）。
- 提交前至少保证 Ruff 与测试通过；不要提交真实 Key、运行产物或 `data/runs/`。

## 7. 常见问题

| 现象 | 处理 |
| :--- | :--- |
| 启动后所有结果 `degraded` | 未配置 LLM/搜索 Key，属预期；填入 `.env` 后重启 |
| `graph_backend=memory` | 未设置 `GRAPH_BACKEND=neo4j` 或连接失败 |
| `checkpoint_backend=memory` | SQLite 文件不可写；检查 `RUNS_DIR` 权限 |
| SSE 立即结束 | 运行已完成，事件回放完毕后发送 `stream_end` |
| 导入旧模块报错 | V1 的 `cli`/`pipeline`/`application` 已删除，改用 API |
