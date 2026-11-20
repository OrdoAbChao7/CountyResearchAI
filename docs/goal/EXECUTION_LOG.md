# Goal Mode 执行日志

更新时间：2026-11-20
Worktree：`E:\Projects\CountyResearchAI-finish-roadmap`
分支：`codex/finish-roadmap`
本轮起点：`88f210c`
本轮代码提交：`46112d0`、`0adc236`；Live smoke 修复：`94202f6`、`3403ddb`；区域检索修复：`53c2007`；短名误判修复：`6614307`；第三次 Live 记录：`ee63fed`；第四次 Live 记录：`f813ba3`；空结果修复：`daa0b83`

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
ee63fed test: record the third bounded live smoke and the short-name fix
6614307 fix: require the full county name inside document content
227b4f7 docs: record the region retrieval gate
53c2007 fix: keep retrieval results inside the requested county
9c76384 docs: link the live smoke fix commits
3403ddb test: record the corrected bounded live smoke
94202f6 fix: preserve an explicit research focus during discovery
ec50451 docs: link the live smoke commit in the execution record
63a0a0e test: record one bounded live provider smoke
0adc236 perf(web): bound large-graph layout and add accessibility coverage
46112d0 feat(web): add dispute panels and report-graph linkage
```

文档提交（本日志、最终报告、STATE/ACCEPTANCE/README）紧随其后。

## 5. 未完成 / 不计为 PASS

- M5 的 40–60 个独立密封任务集、Live 端到端评测、语义 Judge、人工标注与裁决：仍未完成。2026-11-20 执行了两次显式授权的受限 Live smoke（见第 7 节）；它们不构成 Live 评测，也不满足 M5。
- 真实调查的 400 节点浏览器基准：`NOT_RUN`。本轮通过的是 400 节点/800 边**合成投影**的浏览器性能测试，不是真实公开资料调查。
- 章节级流式生成与真实 token 核算：`NOT_RUN`，界面明确不伪造。
- 真实供应链关系：未建模，图谱只投影已持久化的关系。
- 无障碍：已通过 axe WCAG A/AA 自动扫描，但未做真实屏幕阅读器人工走查。

## 6. 当前状态与下一步

本轮 Goal 的完成条件已满足：T2/T3/T7/T10/T12/T13 均有验收证据，三个 P0 回归通过，核心架构保持，后端/前端/E2E 全绿，Wizard 可实际运行，图谱与报告可追溯，所有改动已提交，主工作区未受破坏。

下一步只建议在获得单独授权后进行：Live + 语义 Judge 的 cost gate、密封任务集、真实 400 节点调查基准、流式章节与非证据型供应链关系。

## 7. 受限 Live smoke（2026-11-20，已获用户授权）

用户明确表示“允许付费调用”并“跑一次 Live”。先执行了**一次**带硬上限的
Live 任务；用户随后说“再跑一次”，又执行了**一次**修正版（2,048 token、
显式 focus）。未执行第三次，也未启动 Live 评测、语义 Judge 或密封任务集。

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

第二次运行（修正版）：

| 检查 | 结果 |
| --- | --- |
| 修复 | `ResearchApplication.discover_focus` 让显式 `research_focus` 优先；新增 `test_explicit_focus_wins_over_discovery` 与 API 级断言（`stage.discover.completed` 与问题树） |
| 回归 | `pytest --no-cov -q` → `781 passed`（含 `test_explicit_focus_wins_over_discovery`） |
| Job | `fdf7f3e86d444419967124236c4cc1ad` |
| 状态 | `SUCCEEDED` / `LIVE` / `NO_PROGRESS`（`no_supported_claims`） |
| Focus | `stage.discover.completed` 与问题树均为 `竹产业`；发现 completion 838 < 2,048 |
| 事件 / 图谱 | 28 事件；256 节点 / 1,785 边，返回 800 边 |
| 报告 | 0 verified / 224 `NOT_COMPARABLE`；7 冲突；2 缺口；8 来源 |
| 守卫 | 2 次 LLM、3,944 tokens、7 次 Tavily；0 违规；43.56s |
| 成本 | 模型 $0.00097；Tavily 若付费 $0.056；≤ $0.0579 |
| 结论 | Focus 修复生效；仍为 `NO_PROGRESS`，剩余瓶颈是区域检索与期间覆盖 |

区域检索修复（离线，2026-11-20）：

| 检查 | 结果 |
| --- | --- |
| 代码 | `search/region_relevance.py`：按 REGION / CONTEXT / OTHER_REGION / NATIONAL / UNKNOWN 分类，仅 REGION 与 UNKNOWN 可作为县级证据入库 |
| 接入 | `SearchCollector.collect`、`collect_supplemental(county=...)`、`collect_adaptive`（深度研究路径）、`ProviderSearchAdapter.collect` |
| 可观测 | `collect_adaptive` 的 usage 新增 `region_filtered_documents`，随 `retrieval.round.completed` 事件输出 |
| 回放 | 第二次 Live 的 8 条来源：保留 3 条安吉来源；丢弃 3 条国家级、福建与洛阳来源 |
| 回归 | `tests/test_region_relevance.py` 10 tests；全量 `792 passed in 23.05s`；Anji MOCK 演示不变（25 节点 / 33 边，1 SUPPORTED / 5 NOT_COMPARABLE） |
| 未验证（当时） | 尚未执行第三次付费 Live；2024 时间窗仍会拒绝现有 2023/2025/2026 材料 |

第三次运行（区域闸门验证，用户“跑第三次”）：

| 检查 | 结果 |
| --- | --- |
| Job | `007487e8e7494e3fba1770c1f7b0781f` |
| 状态 | `SUCCEEDED` / `LIVE` / `NO_PROGRESS`（`no_supported_claims`） |
| 用量 | 2 次 LLM、4,693 tokens（发现 completion 1,224）；7 次 Tavily；0 违规；29.23s |
| 事件 / 图谱 | 28 事件；165 节点 / 1,077 边，返回 800 边 |
| 报告 | 0 verified / 133 `NOT_COMPARABLE`；6 冲突；2 缺口；8 来源 |
| 成本 | 模型 $0.001256；Tavily 若付费 $0.056；≤ $0.0585 |
| 区域闸门 | 第二次运行中的国家统计局 / 福建 / 洛阳页面消失；剩余来源集中在安吉，但混入 1 条贵州规划（见下） |
| 发现 | 贵州省“十五五”规划因正文含“安吉精铸”“正安吉他”被短名子串误判为 REGION；该文正文无“安吉县” |
| 修复 | 正文只认全称 `安吉县`；短名仅在标题/摘要/URL 且需词边界；回放第三次来源为 7 region / 1 other_region（贵州规划） |
| 可观测补充 | `collect` 阶段新增 `retrieval.region_filtered` 事件；第三次运行早于该事件，无法给出 collect 阶段丢弃计数 |
| 回归 | `tests/test_region_relevance.py` 13 tests；全量 `795 passed in 37.07s` |
| 未验证 | 修复后的短名规则未再跑付费 Live；2024 时间窗仍为 0 verified |

完整记录：`docs/goal/LIVE_SMOKE.md`；预算与实际用量：
`docs/goal/LIVE_SMOKE_COST_GATE.md`。

## 2024 时间覆盖与 Claim 级区域修复（2026-11-20）

依据：`docs/goal/2024_PERIOD_COVERAGE_AUDIT.md`。全部离线实施，未调用付费
API，未修改 `.env` 或主工作区。工作树
`E:\Projects\CountyResearchAI-finish-roadmap`，分支 `codex/finish-roadmap`。

| Phase | Commit | 变更 | 验证 |
| --- | --- | --- | --- |
| 1 | `e8021c8` | `evidence/claim_region.py`；`EvidenceStore` Claim 独立区域；ledger/图谱/冲突/引用只使用目标县 Claim；`region_present` 参与授权 | `tests/test_claim_region.py`；P0 保持 |
| 2 | `36a7c4f` | `ResearchContract.date_window` → `request_from_contract` → `ResearchRequest` → application → `SearchPort` → collector → QueryEngine；三种模式查询包含目标年份；不按发布日期过滤 | `tests/test_date_window_propagation.py` |
| 3 | `1da579c` | `CoverageSnapshot` 增加目标年 Claim/来源计数与 `period_coverage_met`；`quality_met` 同时要求主题与期间覆盖；期间缺口生成年度查询；事件记录真实 query 文本和每轮覆盖 | `tests/test_adaptive_retrieval.py`、`tests/test_period_coverage_flow.py` |
| 4 | `1f08ba1` | `infer_claim_period`：Claim 原文年份优先；跨年保留区间；无本地年份时才用文档年；窗口检查拒绝越界区间 | measure / ledger / graph 回归 |
| 5 | `c6d98a6` | Tavily/Serper/Bing/DeepSeek 发布日期；URL `tYYYYMMDD` / `/YYYYMM/`；正文仅接受发布标签日期；Provider 截断原文长度与状态 | `test_search_web.py`、`test_deep_retrieval.py` |
| 补充 | `d186577` | 2023/2025 年 Claim 在 2024 窗口外 | `test_evidence_graph.py` |

最终验证（代码 HEAD `d186577`）：

| 检查 | 结果 |
| --- | --- |
| 新增目标回归 | `85 passed in 1.10s` |
| P0 三个模块 | `49 passed in 2.96s` |
| 全量后端 | `827 passed in 35.24s` |
| Ruff | `All checks passed!`（`src tests`） |

未验证：第四次付费 Live 已执行，但在 adaptive follow-up 阶段 `FAILED`；真实检索
是否返回可验证的 2024 年资料仍未验证。修复只改变检索、期间抽取和区域授权，没有
放宽 Verifier；若目标年资料不存在，最终结果仍可为 `INSUFFICIENT_DATA` /
`NO_PROGRESS`。

## 第四次 Live（2026-11-20，用户“跑第四次 Live”）

用户明确说“跑第四次 Live”，授权一次受限付费 smoke。使用同一脚本、同一 provider
覆盖、同一 480s / 24 搜索 / 3 LLM 上限；新 artifact root
`experiments/quality/live_smoke_20261120_fourth`，未修改 `.env`，未覆盖旧运行。

| 检查 | 结果 |
| --- | --- |
| Job | `4f4d6610f48248a599e6b112ce5b9ee0` |
| 状态 | `FAILED` / `LIVE` / `FAILED`（`execution_error`） |
| 用量 | 2 LLM / 4,651 tokens（发现 completion 1,204）；11 Tavily（7 初次 + 4 补充）；0 违规 |
| 时间 | job 31.85s；guard 39.64s |
| 事件 | 14，最后 `job.failed` |
| 区域闸门 | `retrieval.region_filtered`: kept 27 / dropped 4（other_region 3, national 1） |
| 期间覆盖 | `retrieval.period_coverage`: target 2024；22 selected；1 in-window claim/source；period met；topic 缺失 4 slots |
| 补充查询 | 4 条，真实文本记录，含 `2024年` 查询；全部 gov 通道 |
| 失败 | `collect_adaptive` 的 4 条 gov 查询均无白名单结果；`_run_tasks` 在 `fail_fast` 下将空结果当搜索失败，抛 `SearchError` → `ResearchStageError` |
| 产物 | 无验证、无证据持久化、无图谱（409）、报告为空；sources 0 |
| 成本 | 模型 $0.001241；Tavily 11 credits $0.088；≤ $0.0905 |

诊断：

- 根因不是期间覆盖计算，也不是 provider 调用失败。Guard 记录 4 次 Tavily 调用各
  返回 6 条，说明搜索本身成功；`GovDataProvider` 的白名单过滤把这 4 批结果全部
  过滤为空。
- `_run_tasks` 的 `if not results and self._fail_fast` 把“所有任务空结果”与
  “所有任务异常”混为一谈；该分支自 `4400668`（2026-08-05）已存在，不是本轮
  2024 修复引入。第三次 Live 没有进入补充轮；第四次是首次进入该路径。
- 离线复现（无付费调用）：stub gov provider 返回 `[]` 时，`collect_adaptive`
  抛出同样的 `SearchError`，context 为 `{'tasks_count': 1, 'providers': ['gov']}`。
- 未在本次运行中修改代码；没有第二次付费重试。

结论：第四次 Live 证明了区域闸门、2024 目标年传递、期间覆盖事件和补充查询文本
在真实 provider 下工作；但它在补充检索阶段失败，未完成验证，不能算 2024 检索
成功，也不能算 Live quality PASS。下一步需申请第五次授权；空结果处理已在下一节
修复并加回归。

## 补充修复：补充检索空结果处理（2026-11-20）

第四次 Live 暴露的 `fail_fast` 空结果误判已修复；未调用付费 API。

| 检查 | 结果 |
| --- | --- |
| 代码 | `SearchCollector._run_tasks` 区分“任务抛异常”与“成功返回空”；仅当所有任务都抛异常且 `fail_fast=True` 时抛 `SearchError` |
| 行为 | 空 gov 补充轮返回空 `AdaptiveCollectionResult`；协调器以 `ZERO_MARGINAL_EVIDENCE` 停止该轮，继续用已有证据分析/报告 |
| 回归 | `tests/test_search_collector.py` 新增 3 个：空 gov 不失败、全异常仍失败、空+异常不失败；11 passed |
| 全量 | `830 passed in 23.53s` |
| Ruff | `All checks passed!` |
| 提交 | `daa0b83` |
| 未做 | 未跑第五次 Live；未 Push/合并 |
