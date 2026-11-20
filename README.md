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
| 深度研究捕获：问题树、证据项、冲突、缺口、反思/检索轮次，三种模式 | 已实现，投影后存入任务结果 |
| 细粒度事件：问题树、检索、证据摄入、覆盖率、Critic、Agent、综合、报告 | 已实现，写入现有 SQLite `job_events` 并走 SSE |
| 图谱投影：稳定 ID、URL 归一、多重边、400/800 截断、冲突/缺口 | 已实现，`GET /tasks/{id}/graph` |
| 报告投影：结构化章节、引用编号、冲突/缺口、`native_sections` vs `markdown_split` | 已实现，`GET /tasks/{id}/report.json` |
| Wizard + Report Studio + Evidence Drawer + Agent Timeline | 已实现，React 18 + Vite 5 |
| 冲突与缺口面板：多来源数值差异、未采信结论、结构化缺口 | 已实现，报告工作台标签页 |
| 报告 ↔ 证据抽屉 ↔ 图谱双向定位 | 已实现 |
| Cytoscape 证据图谱：懒加载、邻域聚焦、筛选、列表替代视图 | 已实现 |
| 本地 API：任务、SSE、取消/恢复、findings、sources、brief、graph、report | 已实现 |
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

面试/本地演示直接使用安吉县竹产业 MOCK 案例：

```bash
PYTHONPATH=src python scripts/run_finish_roadmap_demo.py
```

一键脚本使用真实 FastAPI/JobStore/证据图/投影，仅检索与 LLM 走 fixture；会输出
`summary.json`、事件序列、图谱计数和报告核验结果。浏览器演示步骤与截图见
[experiments/quality/finish_roadmap_demo/README.md](experiments/quality/finish_roadmap_demo/README.md)。

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
GET  /api/v1/research/tasks/{id}/events        # 持久化事件（seq 单调）
GET  /api/v1/research/tasks/{id}/findings
GET  /api/v1/research/tasks/{id}/claims
GET  /api/v1/research/tasks/{id}/claims/{claim_id}
GET  /api/v1/research/tasks/{id}/sources
GET  /api/v1/research/tasks/{id}/questions     # 问题树 + 覆盖率
GET  /api/v1/research/tasks/{id}/graph         # 证据图谱投影，400/800 上限
GET  /api/v1/research/tasks/{id}/evidence      # 证据抽屉列表
GET  /api/v1/research/tasks/{id}/brief
GET  /api/v1/research/tasks/{id}/report        # 程序生成的核验报告
GET  /api/v1/research/tasks/{id}/report.json   # 章节/引用/冲突/缺口
GET  /api/v1/research/tasks/{id}/report/draft  # 旧版 Markdown（需在 reports 根内）
GET  /api/v1/research/sources/{snapshot_id}
```

没有 `deep_research` 选项的运行，`questions` / `graph` 返回 `409 artifacts_unavailable`（`deep_research_disabled`），不会伪造空图或空问题树。

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

当前实测（2026-11-20，`codex/finish-roadmap`）：

- Python 测试 **795 passed**（`pytest --no-cov -q`，0 failed）；`ruff check src tests scripts/run_finish_roadmap_demo.py scripts/run_live_smoke.py` 通过。
- 前端 **20** 个 Vitest、`tsc --noEmit` 与 Vite build 通过；主包 208.2 kB，Cytoscape 懒加载 chunk 456.1 kB。
- Playwright **4/4**：完整 Wizard（创建 → 事件/Agent 时间线 → 图谱/列表 → 证据抽屉 → 报告引用 → 冲突与缺口 → 报告跳图谱）、取消/恢复、400 节点合成投影性能、axe WCAG A/AA 无障碍扫描；截图在 `experiments/quality/finish_roadmap_e2e/`。
- 合成 400 节点/800 边浏览器测试：首帧约 0.5 s，切换列表约 0.2 s；真实调查的 400 节点基准仍未运行。
- 安吉县竹产业 MOCK 演示：35 条事件、25 节点/33 边、6 条证据项、3 个独立来源、2 个冲突、3 个缺口；2024 时间窗下 1 条 `SUPPORTED`、5 条 `NOT_COMPARABLE`，证明 2025/2027 材料不会冒充 2024 事实。详见 `experiments/quality/finish_roadmap_demo/`。
- 2026-11-20 三次授权 **Live smoke**：DeepSeek `deepseek-flash` + Tavily basic，三次任务均 `SUCCEEDED` / `LIVE`。第一次 28 事件、273 节点/1,869 边、0 verified / 239 `NOT_COMPARABLE`；第二次修正版（2,048 token、显式 `竹产业` focus）28 事件、256 节点/1,785 边、0 verified / 224 `NOT_COMPARABLE`；第三次（区域闸门）28 事件、165 节点/1,077 边、0 verified / 133 `NOT_COMPARABLE`。这证明真实 provider 与现有任务/证据/投影链路可用，**不是** Live 质量验收。详见 [docs/goal/LIVE_SMOKE.md](docs/goal/LIVE_SMOKE.md)。
- 节点/边的截断为连通子图，不会返回大量孤立证据点；报告 Markdown 对来源文本做 HTML 转义，引用 URL 只允许 http(s)。
- 冻结 matched-budget 离线 A/B/C 复算：C 组在现有小样本上落后 A/B 且资源消耗更高。**不能**据此得出 v2 优于基线的结论。
- Quality Recovery dev-replay：measure-aware Strategy D 将 GT 端到端覆盖从 C 的 3/90 提升到 15/90；这是**开发集**结果（McNemar p=0.000488，仅 dev），检索仍缺 69/90。盲测 pilot 仅 2 任务/10 facts（D 4/10），不足以支持泛化结论。
- Q7 retrieval recovery：聚合所有归档 run 找回 26/69 缺失事实，D pooled dev E2E 33/90；免费公开网页在 long-history 找回 6/30（决策级仍 0/30）；oracle 探测显示 17/30 来源仍可访问，瓶颈是发现/抽取而非来源消失。Verifier 审计（assistant 标注）假支持 3/10、假拒绝 4/15；无 sealed 40–60 任务集，不能声称独立泛化。

完整、区分 offline/fixture/replay/live 的报告见 [docs/evaluation/FINAL_REPORT.md](docs/evaluation/FINAL_REPORT.md)，Quality Recovery 见 [Q3/Q4](docs/goal/Q3_Q4_REPORT.md)、[Q5](docs/goal/Q5_REPORT.md)、[Q6](docs/goal/Q6_FINAL_ACCEPTANCE.md)、[Q7](docs/goal/Q7_REPORT.md)。评测设计见 [docs/evaluation/DESIGN.md](docs/evaluation/DESIGN.md)。10 个知识点的代码走读见 [docs/interview/ARCHITECTURE_WALKTHROUGH.md](docs/interview/ARCHITECTURE_WALKTHROUGH.md)。本轮 Goal Mode 的执行记录和最终交付见 [EXECUTION_LOG.md](docs/goal/EXECUTION_LOG.md) 与 [FINAL_EXECUTION_REPORT.md](docs/goal/FINAL_EXECUTION_REPORT.md)。

## 代码结构

```text
src/county_research_ai/
  domain/      契约、时间窗、结果枚举
  search/      搜索适配器、adaptive retrieval、BM25 基线
  evidence/    source contract、ledger、SQLite 图谱、确定性校验、数值/来源身份
  application/ collect → discover → evidence → analyze → report
  research_agent/  问题树、Critic、经济/政策/产业 Agent、Synthesizer
  modes/       snapshot / rise-fall / long-history
  observability/  ContextVar 事件总线（无 sink 时静默）
  agent/       有界 Plan-and-Execute（兼容旧 CLI）
  api/         FastAPI、JobStore/SSE、事件适配器、图谱/报告/问题投影
  evaluation/  离线复算与指标
web/           React 18 + Vite 5：Wizard、Report Studio、证据抽屉、Cytoscape 图谱
docs/           架构、ADR、Demo、评测、目标状态、面试走读
```

## 边界

- 范围是县域/区域产业研究；不提供医疗、法律、证券投资建议，也不是通用 Agent。
- 切换 LLM provider 时必须同时匹配 `LLM_PROVIDER`、`LLM_BASE_URL`、`LLM_MODEL` 与对应 key；只换 key 会得到 401/400。只有 `AXIOMSCOPE_API_LIVE=true` 且 LLM/搜索 key 都存在时，API 才标记 `LIVE`；否则强制 `MOCK`。
- Live smoke 曾返回非目标县来源。现已加入确定性区域相关性闸门（`search/region_relevance.py`）：在排序与入库前丢弃其他省/市/县、国家级以及仅上级（省/市）的来源。第二次 Live 的 8 条记录来源回放保留 3 条、丢弃 5 条；第三次 Live 实测后来源已集中在安吉，并暴露一个短名误判（贵州规划中的“安吉精铸/正安吉他”），现已改为正文只认全称 `安吉县`、短名仅在标题/摘要/URL 且需词边界，回放该次来源为 7 region / 1 other_region。修复后的规则尚未再跑付费 Live；2024 时间窗仍会拒绝现有 2023/2025/2026 材料。
- `max_steps`、`max_search_calls`、`max_cost` 在旧 workflow 路径未强制执行；API 会如实报告 `not_enforced_on_workflow_path`。`max_tokens`/`max_documents` 是单次调用/单次采集上限，不是累计配额；只有 `deadline_seconds` 会触发 `BUDGET_EXHAUSTED`。
- 确定性校验不识别语义改写/别名；未命中的正确结论会保持 `INSUFFICIENT`。
- 图谱只投影已持久化的问题、证据、来源、冲突与缺口；没有证据支持的供应商/客户/原材料关系不会生成。默认 400 节点/800 边，截断时保留关键节点并尽量维持连通。
- 报告的事实表只来自 `SUPPORTED` finding；`NOT_COMPARABLE / NEEDS_REVIEW / INSUFFICIENT` 进入冲突/缺口章节。旧版 Markdown 只作背景材料，`markdown_split` 会明确标注。
- 前端只展示真实的持久化事件；报告渲染完成后逐节展示是视觉编排，不是章节级流式生成；界面不展示编造的 token 消耗。
- 任务执行带 SQLite lease、心跳与 fencing token；过期/空 lease 才会被恢复，陈旧 worker 不能覆盖新结果。每个 API 任务使用独立 raw/report 目录。仍是单机 SQLite，不是分布式队列。

## 许可

MIT。历史 CountyResearchAI 代码与实验工件保留在原分支与目录中，未改写。
