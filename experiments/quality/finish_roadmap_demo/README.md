# 安吉县竹产业 MOCK 演示案例

> **这是 MOCK 演示，不是真实调研。** 搜索与 LLM 均由本仓库的 fixture 适配器提供，
> 用于验证产品链路、证据结构与事实校验；界面和任务记录均标注 `MOCK`。默认
> `AXIOMSCOPE_API_LIVE=false`，不会调用任何付费模型或搜索服务。

这个案例覆盖面试演示需要的完整链路：创建研究 → 问题树 → 检索 → 专业 Agent →
证据入库 → 图谱 → 冲突/缺口 → 程序生成报告 → 引用回溯。

## 一键运行

在仓库根目录执行（Python 3.10+，已安装项目依赖）：

```bash
PYTHONPATH=src python scripts/run_finish_roadmap_demo.py
```

Windows PowerShell：

```powershell
$env:PYTHONPATH = "src"
python scripts/run_finish_roadmap_demo.py
```

脚本使用真实的 FastAPI 应用（进程内 `TestClient`）、`JobStore`、`JobRunner`、
事件表、证据图和投影接口；只是检索/LLM 走 MOCK。运行后生成：

```text
experiments/quality/finish_roadmap_demo/run/
  summary.json                 # 任务、事件、图谱、报告核验摘要
  data/api/jobs.sqlite         # 任务与 job_events
  data/api/evidence.sqlite     # 证据图
  reports/api_jobs/<job_id>/   # 旧版 Markdown 报告（仅作背景材料）
```

重新运行会创建新任务并追加到同一个数据库；如需一份干净的单任务演示，先删除
`run/`（该目录是可再生运行产物），再执行脚本。

### 本次实测结果

最近一次运行（`job_id=33e79bc4384d4cc788d7d9fa04ed8509`）：

| 项目 | 观测值 |
| --- | --- |
| 状态 / 结论 | `SUCCEEDED` / `SUFFICIENT`，`mode_label=MOCK` |
| 事件 | 35 条，序号连续 |
| 问题树 | 6 个问题，覆盖率 50% |
| 证据 | 6 条证据项、3 个独立来源、2 个冲突、3 个缺口 |
| 图谱 | 25 节点 / 33 边（county 1、question 6、evidence 6、source 3、gap 3、conflict 2、topic 4） |
| 报告 | 6 个章节，1 条 `SUPPORTED`、5 条 `NOT_COMPARABLE`，6 条引用 |

5 条 `NOT_COMPARABLE` 不是缺陷，而是演示重点：研究窗口是 2024 年，材料中的
2025/2027 年产值和政策目标不能冒充 2024 年事实，因此不进入“已核实事实”表。
冲突节点和缺口节点仍会出现在图谱与“冲突、反证与不可比”章节中。

真实事件顺序（节选）：

```text
job.queued → job.started
stage.collect.* → stage.discover.* → stage.evidence.* → stage.analyze.started
question_tree.created → evidence.ingested
reflection.started/completed → retrieval.round.started/completed → evidence.ingested
question_tree.coverage → gaps.detected → conflicts.detected
agent.started/completed × 3 → synthesis.started/completed
evidence.persisted → stage.report.* → report.rendered → job.completed
```

## 在浏览器中演示

让 API 使用同一份演示数据启动（并托管已构建的 `web/dist`）：

```bash
PYTHONPATH=src DATA_DIR="experiments/quality/finish_roadmap_demo/run/data" REPORTS_DIR="experiments/quality/finish_roadmap_demo/run/reports" AXIOMSCOPE_API_LIVE=false AXIOMSCOPE_API_PORT=8030 python -m county_research_ai.api
```

打开：

- 创建工作台：`http://127.0.0.1:8030/?step=1`
- 运行与时间线：`http://127.0.0.1:8030/?step=2&task=33e79bc4384d4cc788d7d9fa04ed8509`
- 证据图谱：`http://127.0.0.1:8030/?step=3&task=33e79bc4384d4cc788d7d9fa04ed8509&layout=graph`
- 报告工作台：`http://127.0.0.1:8030/?step=4&task=33e79bc4384d4cc788d7d9fa04ed8509&layout=workbench`

`task` 使用 `summary.json` 中的 `job_id`。URL 会保存步骤、任务和布局，刷新可恢复。

## 90 秒演示脚本

1. **Step 01**：说明合同字段（地区、产业、2024 时间窗、深度研究、证据门槛），
   强调右上角 `MOCK` 徽标和“未配置 Provider 密钥时以 MOCK 运行”的提示。
2. **Step 02**：打开 Agent 时间线。指出 `question_tree.created`、两轮 Critic
   反思/补充检索、经济/政策/产业 Agent、`synthesis.completed`、`report.rendered`
   都来自持久化事件；没有伪造章节流式生成或 token 消耗。
3. **Step 03**：切到图谱。说明节点/边类型、稳定 ID、URL 去重和多重边；点击
   conflict/gap 节点查看右侧上下文；切“列表”验证无障碍替代视图。
4. **Step 04**：报告显示 `1/6` 已核实。解释 2025/2027 材料为何是
   `NOT_COMPARABLE`，冲突事实为何不在事实表中复述。点击引用角标打开证据抽屉，
   展示精确 quote 高亮、偏移、快照和核验原因。
5. **收尾**：刷新页面，任务、步骤和布局仍然恢复；说明任务/事件/证据分别持久化
   在 SQLite，报告由程序根据结构化事实生成，LLM 不重写数值、单位、期间和口径。

## 截图

- [00-define.png](00-define.png)：创建研究（MOCK、2024 时间窗、深度研究开关）
- [01-run.png](01-run.png)：真实事件驱动的 Agent 时间线
- [02-graph.png](02-graph.png)：Cytoscape 证据图谱与冲突/缺口
- [03-report.png](03-report.png)：程序生成的核验报告与 `1/6` 事实表
- [04-evidence.png](04-evidence.png)：引用 → 证据抽屉 → 精确原文高亮

浏览器截图在本机以 Playwright Chromium、1440×960 捕获，控制台无错误。浏览器
E2E 使用独立的 `experiments/quality/finish_roadmap_e2e/` 运行目录，见
`web/tests/e2e/workspace.spec.ts`。

## 真与假

| 真实运行 | MOCK / 限制 |
| --- | --- |
| FastAPI 路由、SQLite `jobs`/`job_events`、租约/心跳/fencing | 搜索结果与 LLM 文本来自 fixture |
| 事件顺序、SSE、刷新恢复、取消/恢复 | 不代表真实检索覆盖度或模型质量 |
| 证据快照、span 偏移/哈希、确定性校验 | 校验不等于语义蕴含，不识别同义改写 |
| 图谱/报告投影、引用编号、XSS 转义 | 不生成没有证据支持的产业链关系 |

M5 的 40–60 独立任务集、Live 评测、语义 Judge 和人工标注仍未完成，不能把本
案例当作研究质量或泛化能力的证明。
