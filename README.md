# AxiomScope

**Evidence-Native Research Intelligence Platform** — 县域与区域产业研究。

AxiomScope 是本仓库 Public 产品名；项目原名为 **CountyResearchAI**。它把县域产业研究从“生成一篇报告”升级为“可追溯到精确引文的结构化证据链”：每条结论都要回到不可变来源快照中的 quote、偏移与哈希，未满足证据门槛的结论会被显式隐藏或标注，而不是被自然语言包装成事实。

> 这是一个研究原型。公开资料覆盖度取决于地区与搜索服务；MOCK 模式只验证产品链路与证据校验，不代表真实检索或模型质量。详见 [PROJECT_STATUS.md](PROJECT_STATUS.md) 与 [docs/goal/STATE.md](docs/goal/STATE.md)。

## 现在能做什么

| 能力 | 状态 |
| --- | --- |
| `ResearchContract`：目标、地区、时间窗、必答问题、证据门槛、预算上限 | 已实现并有校验测试 |
| 来源快照：canonical URL、观测/发布时间、内容哈希、精确偏移 | 已实现 |
| SQLite 证据图谱：snapshot → span → claim → finding | 已实现，重启后可重载 |
| 确定性校验：引文偏移/哈希、数值/单位、期间/范围/口径、时间窗 | 已实现；**不是语义蕴含** |
| 冲突与不可比：`SUPPORTED / CONTRADICTED / INSUFFICIENT / NOT_COMPARABLE / OUTDATED / NEEDS_REVIEW` | 已实现 |
| 本地 API：任务、SSE、取消/恢复、findings、sources、brief | 已实现 |
| React + Vite 工作台：任务提交、时间线、证据浏览器、简报下载 | 已实现 |
| 真实多基线质量结论 | **未完成**（见 [docs/evaluation/FINAL_REPORT.md](docs/evaluation/FINAL_REPORT.md)） |

## 快速开始（本地 Demo）

需要 Python 3.10+ 与 Node 20+。Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd web
npm install
npm run build
cd ..
Copy-Item .env.example .env
.\scripts\start_api.ps1
```

打开 <http://127.0.0.1:8000>。未设置 `AXIOMSCOPE_API_LIVE=true` 时，即使 `.env` 中有 Key，API 任务也强制走 **MOCK**，避免误触发付费调用。Linux/WSL 等价步骤见 [docs/demo/DEMO_SCRIPT.md](docs/demo/DEMO_SCRIPT.md)。

前后端分离开发：

```powershell
.\scripts\start_api.ps1     # API :8000
.\scripts\start_web.ps1     # Vite :5173，代理到 :8000
```

## 证据模型

```text
SourceSnapshot (append-only, content hash)
    └── EvidenceSpan (exact quote + offsets + span hash)
            └── ClaimEvidenceEdge (supports / contradicts / context)
                    └── Claim (region, metric, value, unit, period, scope, caliber, version)
                            └── Finding (structured, persisted before Markdown)
                                    └── Decision brief / API / UI
```

- 来源与 span 为 append-only；同 id 不同内容会报错而不是覆盖。
- 独立支持按 canonical URL 计数，转载不会放大证据。
- 结论数值必须出现在引文中；期间必须落在 `date_window` 内。
- 两条各自有支持的冲突结论标记 `NEEDS_REVIEW`；无支持的冲突不能推翻有支持的结论。
- 未支持的结论在决策简报中**只列 id 与原因，不复述内容**。

## API

`/api/v1`，OpenAPI 文档在 `/docs`，健康检查 `/health`。核心端点：

```text
POST /api/v1/research/tasks
GET  /api/v1/research/tasks
GET  /api/v1/research/tasks/{id}
POST /api/v1/research/tasks/{id}/cancel
POST /api/v1/research/tasks/{id}/resume
GET  /api/v1/research/tasks/{id}/stream        # SSE
GET  /api/v1/research/tasks/{id}/findings
GET  /api/v1/research/tasks/{id}/claims/{claim_id}
GET  /api/v1/research/tasks/{id}/sources
GET  /api/v1/research/tasks/{id}/brief
GET  /api/v1/research/sources/{snapshot_id}
```

错误统一为 `{"error": {"code", "message", "details?"}}`。API 不抓取用户提供的任意 URL，不返回模型密钥或堆栈；报告文件必须位于 reports 根目录内。端点与运行限制详见 [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md)。

## 保留的旧 CLI

原有 `county-research` CLI 与三种研究模式（`snapshot`、`rise-fall`、`long-history`）继续可用：

```powershell
county-research -c 安吉县 -f 竹产业
county-research -c 鹤岗市 --mode rise-fall
county-research agent -c 安吉县 --max-steps 8
```

## 验证与评测

```powershell
.venv\Scripts\python.exe -m pytest --no-cov -q          # Python 测试
cd web; npm run typecheck; npm test; npm run build      # 前端检查
cd web; npm run test:e2e                                # Playwright 浏览器 E2E
.venv\Scripts\python.exe scripts\run_multi_baseline_offline.py
```

当前实测：

- Python 测试 **692 passed**；前端 4 tests、`tsc` 与 Vite build 通过；Playwright 2/2 通过（创建/SSE/证据/简报、取消/恢复）。
- 本地 `MOCK` 端到端：任务 `SUCCEEDED` / `SUFFICIENT`，3 个来源、6 条结构化结论；2025/2027 结论在 2024 时间窗内被正确判为 `NOT_COMPARABLE`。
- 冻结 matched-budget 离线 A/B/C 复算：C 组在现有小样本上落后 A/B 且资源消耗更高。**不能**据此得出 v2 优于基线的结论。
- Quality Recovery dev-replay：measure-aware Strategy D 将 GT 端到端覆盖从 C 的 3/90 提升到 15/90；这是**开发集**结果（McNemar p=0.000488，仅 dev），检索仍缺 69/90。盲测 pilot 仅 2 任务/10 facts（D 4/10），不足以支持泛化结论。

完整、区分 offline/fixture/replay/live 的报告见 [docs/evaluation/FINAL_REPORT.md](docs/evaluation/FINAL_REPORT.md)，Quality Recovery 见 [Q3/Q4](docs/goal/Q3_Q4_REPORT.md)、[Q5](docs/goal/Q5_REPORT.md)、[Q6](docs/goal/Q6_FINAL_ACCEPTANCE.md)。评测设计见 [docs/evaluation/DESIGN.md](docs/evaluation/DESIGN.md)。

## 代码结构

```text
src/county_research_ai/
  domain/      契约、时间窗、结果枚举
  search/      搜索适配器、adaptive retrieval、BM25 基线
  evidence/    source contract、ledger、SQLite 图谱、确定性校验
  application/ collect → discover → evidence → analyze → report
  modes/       snapshot / rise-fall / long-history
  agent/       有界 Plan-and-Execute（兼容旧 CLI）
  api/         FastAPI、持久化任务、SSE、简报
  evaluation/  离线复算与指标
web/           React + Vite 工作台
docs/           架构、ADR、Demo、评测、目标状态
```

## 边界

- 范围是县域/区域产业研究；不提供医疗、法律、证券投资建议，也不是通用 Agent。
- `max_steps`、`max_search_calls`、`max_cost` 在旧 workflow 路径未强制执行；API 会如实报告 `not_enforced_on_workflow_path`。`max_tokens`/`max_documents` 是单次调用/单次采集上限，不是累计配额；只有 `deadline_seconds` 会触发 `BUDGET_EXHAUSTED`。
- 确定性校验不识别语义改写/别名；未命中的正确结论会保持 `INSUFFICIENT`。
- 任务执行带 SQLite lease、心跳与 fencing token；过期/空 lease 才会被恢复，陈旧 worker 不能覆盖新结果。每个 API 任务使用独立 raw/report 目录。仍是单机 SQLite，不是分布式队列。

## 许可

MIT。历史 CountyResearchAI 代码与实验工件保留在原分支与目录中，未改写。
