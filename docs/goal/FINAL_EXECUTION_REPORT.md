# Goal Mode 最终执行报告

日期：2026-11-20
分支：`codex/finish-roadmap`
Worktree：`E:\Projects\CountyResearchAI-finish-roadmap`
基线：`codex/quality-recovery` @ `144f4c8`
最终 HEAD：见 `git log -1`（本报告随文档提交）

## 1. 改造前后架构

**改造前（`144f4c8`）**

- 已有 Evidence-Native v2 后端：`ResearchContract` → 检索/采集 → `EvidenceLedger`/SQLite 证据图 → claim/span 确定性校验 → finding → 旧版 Markdown。
- 已有 FastAPI `/api/v1`、SQLite `jobs`/`job_events`、`JobRunner`（线程池 + lease/fencing/heartbeat）、SSE、取消/恢复。
- 已有 React 18 + Vite 5 工作台，但只有基础任务列表、时间线、证据视图与简报，没有 Wizard、报告工作台、Cytoscape 图谱或图谱/报告投影 API。
- 深度研究（问题树、Critic、专业 Agent）只在运行时存在，运行结束后不能完整查看；事件粒度停留在 stage 级。

**改造后**

```text
ResearchContract
   │
   ├─ collect → discover → EvidenceLedger/EvidenceGraphStore
   │                              │
   │                              ├─ 确定性校验（P0）
   │                              └─ finding → 报告投影
   │
   └─ options.deep_research=true
          └─ DeepResearchCoordinator
                ├─ question tree / retrieval rounds / Critic
                ├─ economic / policy / industry agents
                ├─ synthesizer
                ├─ emit(细粒度事件) → job_events → SSE
                └─ projection → jobs.result_json
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
        /graph 投影          /report.json 投影      /questions /evidence
              │                    │                    │
              └──────────── React Wizard 01–04 ────────┘
                     StepRail · RunStep · GraphPanel
                     ReportStudio · EvidenceDrawer · ContextPanel
```

保留不变：FastAPI `/api/v1`、SQLite JobStore、`JobRunner`、SSE、确定性校验器、React 18/Vite 5、旧 CLI 与三种研究模式。没有第二套 RunManager、任务队列、JSONL 存储、`/api/v1/runs` 或 `frontend/` 重写。

## 2. 实际完成的功能

| 任务 | 状态 | 交付 |
| --- | --- | --- |
| P0 事实可信度 | PASS | 冲突数值不授权 VERIFIED；企业实体绑定准确原文；报告程序生成且不改写已核验事实 |
| T2 深度研究捕获 | PASS | 三种模式保存完整 `DeepResearchResult`，worker 投影进现有 `jobs.result_json`，取消/lease/deadline 不变 |
| T3 细粒度事件 | PASS | 问题树、检索轮次、证据摄入、覆盖率、Critic、Agent、综合、报告事件写入现有 SQLite/SSE；顺序、重放、幂等、异常隔离有测试 |
| T7 图谱/报告投影 | PASS | 稳定 ID、URL 归一、多重边、自环丢弃、400/800 连通截断；六章节报告、引用编号、冲突/缺口投影 |
| T10 报告与证据工作台 | PASS | Report Studio、Evidence Drawer、Agent Timeline、引用联动、冲突与缺口面板、加载/空/错误状态 |
| T12 知识图谱 | PASS | Cytoscape 懒加载、节点/关系筛选、邻域聚焦、冲突高亮、证据抽屉、报告 ↔ 图谱双向定位、400 节点自适应布局 |
| T13 工程硬化 | PASS | 780 Python、Ruff、TypeScript、20 Vitest、Vite build、4 Playwright、axe WCAG A/AA、XSS 与三个 P0 回归 |

本轮新增的交互：

- 报告页新增“冲突与缺口”标签页：多来源数值冲突、已核验结论冲突、结构化缺口，含来源数值/年份/范围表和核验建议。
- 报告引用 → 证据抽屉 → “在图谱中定位” → 图谱选中对应证据节点；ContextPanel 同时提供“报告定位”和“图谱定位”。
- 大于 240 节点的图谱自动切换同心布局，低缩放隐藏标签、放大恢复，并弱化边以保持交互。

## 3. 新增和修改的文件

本轮（`88f210c..HEAD`）：

| 文件 | 变化 |
| --- | --- |
| `web/src/App.tsx` | 图谱焦点状态、报告/图谱/抽屉互相定位 |
| `web/src/components/ReportStudio.tsx` | 冲突与缺口面板、ARIA tabpanel、引用联动 |
| `web/src/components/ContextPanel.tsx` | 证据/节点的图谱定位 |
| `web/src/components/EvidenceDrawer.tsx` | “在图谱中定位” |
| `web/src/components/GraphPanel.tsx` | `focusClaimId`、大图谱说明 |
| `web/src/components/GraphCanvas.tsx` | 自适应布局、缩放感知标签、密集图样式 |
| `web/src/components/AgentTimeline.tsx` | 可聚焦滚动事件日志 |
| `web/src/graphLayout.ts` | 布局选择阈值（新增） |
| `web/src/graph.test.ts` | 布局选择单测（新增） |
| `web/src/styles.css` | 冲突/缺口面板、对比度修复、图谱说明 |
| `web/tests/e2e/workspace.spec.ts` | 报告→图谱联动、400 节点性能、axe 扫描 |
| `web/package.json` / `web/package-lock.json` | `@axe-core/playwright` devDependency |
| `experiments/quality/finish_roadmap_e2e/01–12*.png` | 更新/新增 E2E 截图 |

此前 Finish Roadmap 提交新增的核心文件：`observability/events.py`、`api/event_sink.py`、`api/projections/{graph,report,questions,evidence}.py`、Wizard 组件、`scripts/run_finish_roadmap_demo.py`、`docs/interview/ARCHITECTURE_WALKTHROUGH.md` 等。

## 4. Git Commit 列表

```text
0adc236 perf(web): bound large-graph layout and add accessibility coverage
46112d0 feat(web): add dispute panels and report-graph linkage
88f210c docs: record the finish-roadmap architecture and acceptance
16efd5f test: record full-wizard Playwright evidence
464e03c docs: add a reproducible Anji bamboo MOCK demo
182e48c fix: enforce the formal gate before any report QA work
3a246cf test: harden events, projections, and the wizard E2E path
8d24491 feat(web): ship evidence-native wizard workbench
1a61223 fix: keep conflicting evidence out of verified conclusions
f88321c feat: add run-scoped graph and verified report projections
002e4f2 feat: stream fine-grained research events into the job store
f72b9a0 feat: capture deep research results in the run context
3adfc94 fix: port deterministic reliability hardening
```

文档提交（本报告、`EXECUTION_LOG.md`、`STATE.md`、`ACCEPTANCE.md`、README）紧随其后。未 push、未部署、未合并主线。

## 5. 全量测试结果

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| P0 回归 | `pytest --no-cov -q tests/test_evidence_store.py tests/test_evidence_graph.py tests/test_report_projection.py` | `47 passed in 2.96s` |
| Python 全量 | `pytest --no-cov -q` | `780 passed in 24.63s` |
| Ruff | `ruff check src tests scripts/run_finish_roadmap_demo.py` | `All checks passed!` |
| TypeScript | `npm run typecheck` | exit 0 |
| Vitest | `npm test` | 4 files / `20 passed` |
| Vite build | `npm run build` | main `208.21 kB`，GraphCanvas `456.11 kB`，CSS `35.98 kB` |
| Playwright | `AXIOMSCOPE_E2E_PORT=8040 npx playwright test` | `4 passed (28.2s)` |
| 400 节点性能 | 同上 | 首帧 `505ms`，列表切换 `204ms` |
| 无障碍 | 同上，axe WCAG A/AA | 六个界面 0 violations |
| MOCK 演示 | `PYTHONPATH=src python scripts/run_finish_roadmap_demo.py` | `SUCCEEDED/SUFFICIENT`，35 事件，25 节点/33 边，1 SUPPORTED / 5 NOT_COMPARABLE，2 冲突，3 缺口 |

## 6. 三个 P0 验收结果

| 约束 | 结果 | 代码 | 回归测试 |
| --- | --- | --- | --- |
| 数值冲突不能继续授权 VERIFIED | PASS | `evidence/store.py` 冲突标记与原始状态保留；`evidence/graph.py` 对两个独立支持冲突返回 `NEEDS_REVIEW`；`evidence/numeric_support.py` 绑定方向/期间/口径/单位 | `test_repeated_imports_keep_conflicting_items_out_of_verified_state`、`test_two_supported_conflicting_claims_need_review` |
| 实体必须有准确原文证据绑定 | PASS | `evidence/store.py` 企业证据保留原始条款，拒绝否定/不确定表述，不合成不存在企业 | `test_enterprise_evidence_is_the_source_clause_not_a_synthesized_fact`、`test_negated_or_uncertain_enterprise_mentions_are_not_extracted` |
| 报告不能篡改已核验事实 | PASS | `api/projections/report.py` 仅从 `SUPPORTED` finding 生成事实表；value/unit/period/caliber 原样复制；来源文本 HTML 转义；引用只允许 http(s) | `test_report_escapes_malicious_source_text_without_dropping_facts`、`test_verified_report_uses_only_supported_facts` |

## 7. 前端实际截图

均在 `experiments/quality/finish_roadmap_e2e/`，由真实 FastAPI + MOCK 数据 + 浏览器 Playwright 生成：

| 截图 | 内容 |
| --- | --- |
| `01-define.png` | Wizard 定义页 |
| `02-run.png` | 运行页与 Agent 时间线/事件流 |
| `03-graph.png` | 真实 MOCK 调查的 Cytoscape 图谱 |
| `04-evidence.png` | 证据抽屉、精确引文、来源内容 |
| `05-verified-report.png` | 核验报告与章节导航 |
| `06-report-citation.png` | 报告引用联动 |
| `07-narrative.png` | 旧版叙述与 provenance 标注 |
| `08-cancel-resume.png` | 取消/恢复 |
| `09-disputes.png` | 冲突与缺口面板 |
| `10-report-graph-link.png` | 报告引用 → 图谱定位 |
| `11-large-graph.png` | 400 节点/800 边**合成投影**性能测试画布 |
| `12-large-graph-list.png` | 同一合成投影的 400 行列表视图 |

`11/12` 是合成性能夹具，不是真实调查；真实 MOCK 调查的图谱见 `03-graph.png`。

## 8. 尚未完成的功能

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 40–60 个独立密封任务集 | NOT_MET | M5 仍未完成；不得用 2 个 pilot 任务替代 |
| Live 端到端评测 / 语义 Judge | BLOCKED_EXTERNAL | 需要单独付费 cost gate；本轮按规则未调用任何付费 API |
| 人工标注与裁决 | BLOCKED_HUMAN_ANNOTATION | 无人工标签 |
| 真实调查的 400 节点浏览器基准 | NOT_RUN | 本轮只验证合成 400 节点/800 边投影 |
| 章节级流式生成 / 真实 token 核算 | NOT_RUN | 报告一次性生成，界面不伪造 |
| 供应链/客户/原材料关系 | NOT_RUN | 图谱只投影已持久化的证据、问题、来源、冲突、缺口 |
| 屏幕阅读器人工走查 | NOT_RUN | 已完成 axe WCAG A/AA 自动扫描 |

## 9. 当前项目运行方式

```powershell
# 后端依赖（主工作区已有 .venv 时可直接复用）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 前端
cd web
npm install
npm run build
cd ..

# 启动 API（默认 MOCK）
.\scripts\start_api.ps1
# 打开 http://127.0.0.1:8000
```

Linux/WSL / 演示脚本：

```bash
PYTHONPATH=src python scripts/run_finish_roadmap_demo.py
```

测试：

```bash
PYTHONPATH=src python -m pytest --no-cov -q
ruff check src tests scripts/run_finish_roadmap_demo.py
cd web && npm run typecheck && npm test && npm run build
cd web && AXIOMSCOPE_E2E_PORT=8040 npx playwright test
```

根目录 `.env` 已确认存在 `LLM_*` 与搜索服务配置。本轮依据 Goal 规则第 9 条未调用真实付费 LLM/搜索；默认仍为 MOCK。

## 10. 后续建议

1. 在单独 cost gate 下用 DeepSeek/搜索跑一次受预算约束的 Live smoke，再决定是否进入 Live 评测；不要在默认路径开启。
2. 先补齐 40–60 个密封任务与预期引文（`docs/evaluation/DESIGN.md`），再做 Live + 语义 Judge；不要用 pilot 调参。
3. 用真实调查数据做 400 节点浏览器基准，记录首帧、筛选、聚焦与内存；当前数字只代表合成夹具。
4. 若需要章节级流式，单独设计“报告已完成、前端逐节展示”与“真实流式生成”的区分，避免把视觉编排说成流式。
5. 供应链关系应来自新的领域对象与证据，而不是从关键词推断；在此之前保持图谱边界诚实。
6. 无障碍在 axe 自动扫描之外，补一次键盘 + 屏幕阅读器人工走查。
