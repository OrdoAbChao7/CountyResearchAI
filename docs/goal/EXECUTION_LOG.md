# Goal Mode 执行日志

更新时间：2026-11-20
Worktree：`E:\Projects\CountyResearchAI-finish-roadmap`
分支：`codex/finish-roadmap`
本轮起点：`88f210c`
本轮代码提交：`46112d0`、`0adc236`

## 1. 执行前复核

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 独立 Worktree | PASS | 当前目录为 `CountyResearchAI-finish-roadmap`，`git status` 干净 |
| 分支 | PASS | `codex/finish-roadmap` |
| 主工作区未改动 | PASS | 仍为 `codex/quality-recovery` @ `144f4c8`；`git status --porcelain` 62 条（37 modified + 25 untracked） |
| 主工作区字节级校验 | PASS | 当前 `git diff --binary` 的 SHA256 为 `a770faad06f64ee89c56a3402e582b0f9901049af4a1e3cbfccf496fed3ecd05`，与备份 `20261120-main-wip/tracked.patch` 完全一致；37 个 tracked blob 哈希全部匹配；3 个备份的未跟踪源码文件 SHA256 一致 |
| P0 代码存在 | PASS | 冲突保留、企业证据绑定、报告事实保护均在分支中，47 个相关回归测试通过 |
| Git 冲突 / 覆盖风险 | 无 | 工作区干净，未执行 stash/reset/clean/force 操作 |
| 测试基线 | PASS | 后端 780 passed；前端 18 Vitest、2 Playwright（本轮开始前） |

## 2. 阶段执行

| 阶段 | 任务 | 状态 | 本轮动作 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | P0 事实可信度 | PASS | 复核实现并运行回归；未放宽校验器 | `tests/test_evidence_store.py`、`test_evidence_graph.py`、`test_report_projection.py`：47 passed |
| 2 | T2 深度研究捕获 | PASS | 复核三种模式与 worker 投影；全量测试覆盖 | 既有提交 `f72b9a0`；`jobs.result_json` 中的 `deep_research` |
| 3 | T3 细粒度事件 | PASS | 复核事件顺序、SSE、幂等与异常隔离 | 既有提交 `002e4f2`；事件配对与并发 append 测试 |
| 4 | T7 图谱/报告投影 | PASS | 复核稳定 ID、多重边、截断、引用编号 | 既有提交 `f88321c`；`tests/test_graph_projection.py`、`test_report_projection.py` |
| 5 | T10 报告与证据工作台 | PASS | 新增“冲突与缺口”面板；报告引用 → 证据抽屉 → 图谱定位；ContextPanel 图谱定位 | 提交 `46112d0`；截图 `09-disputes.png`、`10-report-graph-link.png` |
| 6 | T12 Cytoscape 图谱 | PASS | 400 节点以上切换同心布局、缩放感知标签、弱化边；新增浏览器性能测试 | 提交 `0adc236`；400 节点首帧 505ms，列表切换 204ms |
| 7 | T13 工程硬化 | PASS | 全量 Python/Ruff/TypeScript/Vitest/Vite/Playwright；新增 axe WCAG A/AA 扫描；修复对比度与滚动区焦点 | 下方测试记录；提交 `0adc236` |

## 3. 测试记录

所有后端命令在 Worktree 根目录运行，使用主线 `.venv` 与 `PYTHONPATH=src`。

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| P0 回归 | `pytest --no-cov -q tests/test_evidence_store.py tests/test_evidence_graph.py tests/test_report_projection.py` | `47 passed in 2.96s` |
| Python 全量 | `pytest --no-cov -q` | `780 passed in 24.63s` |
| Ruff | `ruff check src tests scripts/run_finish_roadmap_demo.py` | `All checks passed!` |
| TypeScript | `npm run typecheck`（build 前置） | exit 0 |
| Vitest | `npm test` | 4 files / `20 passed` |
| Vite build | `npm run build` | main `208.21 kB`，GraphCanvas `456.11 kB`，CSS `35.98 kB` |
| Playwright | `AXIOMSCOPE_E2E_PORT=8040 AXIOMSCOPE_E2E_PYTHON=... npx playwright test` | `4 passed (28.2s)` |
| 400 节点性能 | 同上，graph 测试 | 首帧 `505ms`，列表切换 `204ms` |
| 无障碍 | 同上，axe WCAG A/AA | define / run / report / disputes / graph list / drawer 六个界面 0 violations |

Playwright 覆盖：

1. 完整 Wizard：定义 → 运行/Agent 时间线 → 图谱/列表 → 证据抽屉 → 报告引用 → 冲突与缺口 → 刷新恢复布局 → 报告引用跳图谱。
2. 运行中报告不可读，取消与恢复状态真实。
3. 400 节点/800 边合成投影：同心布局、首帧时间、400 行列表切换。
4. axe 无障碍扫描覆盖六个主要界面。

## 4. 本轮提交

```text
46112d0 feat(web): add dispute panels and report-graph linkage
0adc236 perf(web): bound large-graph layout and add accessibility coverage
63a0a0e test: record one bounded live provider smoke
```

文档提交（本日志、最终报告、STATE/ACCEPTANCE/README）紧随其后。

## 5. 未完成 / 不计为 PASS

- M5 的 40–60 个独立密封任务集、Live 端到端评测、语义 Judge、人工标注与裁决：仍未完成。2026-11-20 只执行了一次显式授权的受限 Live smoke（见第 7 节）；它不构成 Live 评测，也不满足 M5。
- 真实调查的 400 节点浏览器基准：`NOT_RUN`。本轮通过的是 400 节点/800 边**合成投影**的浏览器性能测试，不是真实公开资料调查。
- 章节级流式生成与真实 token 核算：`NOT_RUN`，界面明确不伪造。
- 真实供应链关系：未建模，图谱只投影已持久化的关系。
- 无障碍：已通过 axe WCAG A/AA 自动扫描，但未做真实屏幕阅读器人工走查。

## 6. 当前状态与下一步

本轮 Goal 的完成条件已满足：T2/T3/T7/T10/T12/T13 均有验收证据，三个 P0 回归通过，核心架构保持，后端/前端/E2E 全绿，Wizard 可实际运行，图谱与报告可追溯，所有改动已提交，主工作区未受破坏。

下一步只建议在获得单独授权后进行：Live + 语义 Judge 的 cost gate、密封任务集、真实 400 节点调查基准、流式章节与非证据型供应链关系。

## 7. 受限 Live smoke（2026-11-20，已获用户授权）

用户明确表示“允许付费调用”并“跑一次 Live”。执行了**一次**带硬上限的
Live 任务；未执行第二次，也未启动 Live 评测、语义 Judge 或密封任务集。

| 检查 | 结果 |
| --- | --- |
| Provider | DeepSeek `deepseek-flash`（进程级覆盖）+ Tavily basic |
| 配置发现 | 根 `.env` 写的是 Gemini endpoint/model，但 key 是 DeepSeek key；免费 `/models` 验证 200，Gemini 端点 400。未修改根 `.env` 或主工作区 |
| Job | `d367c9b277cf47d086d28f9824d661e5` |
| 状态 | `SUCCEEDED` / `LIVE` / `NO_PROGRESS`（`no_supported_claims`） |
| 事件 / 图谱 | 28 事件；273 节点 / 1,869 边，返回 800 边 |
| 报告 | 0 verified / 239 `NOT_COMPARABLE`；7 冲突；2 缺口；8 来源 |
| 守卫 | 2 次 LLM、7 次 Tavily；0 违规；47.89s |
| 成本 | 模型 $0.00089；Tavily 7 credits（若付费 $0.056）；≤ $0.0578 |
| 结论 | 工程链路 PASS；研究结果为 `NO_PROGRESS`，不构成质量 PASS |

暴露的问题：

- 合约指定的 `竹产业` 被自动发现覆盖为 `特色农业`；发现调用正好用满 768
  output token，疑似 JSON 截断后回退到 handler 默认方向。
- 检索结果包含福建、洛阳、湖南蓝山与国家统计局等非安吉来源，区域相关性不足。
- 所有 239 条 claim 均为 `NOT_COMPARABLE`（多数为 2022/2023/2025/2026 时间窗，
  少数缺少可用期间）；其中“2024 年竹产业产值为 6.855 亿元”被标为
  `outside_requested_window:2026`，期间归因需要单独核查，暂不称为误拒。
- 真实数据已产生 273 节点，说明真实调查的图谱规模会超过合成 400 节点测试的
  假设；真实 400 节点浏览器基准仍未运行。

完整记录：`docs/goal/LIVE_SMOKE.md`；预算与实际用量：
`docs/goal/LIVE_SMOKE_COST_GATE.md`。
