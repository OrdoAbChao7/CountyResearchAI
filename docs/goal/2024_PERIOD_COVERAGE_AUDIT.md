# 2024 年时间覆盖问题专项审计

日期：2026-11-20
分支：`codex/finish-roadmap`
审计开始时 HEAD：`aaa6a09`
审计对象：第三次 Live smoke `007487e8e7494e3fba1770c1f7b0781f`
审计性质：只读。未调用任何付费 API，未修改 `.env`、`region_relevance.py`、Verifier、源码或既有运行工件；主工作区 `codex/quality-recovery` @ `144f4c8` 未修改。

## 0. 结论摘要

**直接结论：2024 年结论为 0，不是 Verifier 过严，也不是区域闸门造成的。**
当前语料里没有任何 2024 年度数据；检索查询也从未要求 2024。即使把 `infer_period` 对全部 Claim 重放一遍，仍然没有任何 Claim 落入 2024。

| # | 问题 | 审计结论 | 证据等级 |
| --- | --- | --- | --- |
| 1 | 2024 年资料是否实际检索到？ | 持久化证据中没有；7 条查询也没有一条包含年份。是否曾被 Provider 返回又被丢弃，现有工件无法判定 | 实测 + 不可判定 |
| 2 | 如果检索到了，在哪个环节被排除？ | 不能确定。本轮没有查询文本、原始结果集或丢弃日志；只能列出候选环节 | 不可判定 |
| 3 | 如果没有检索到，查询策略哪里有问题？ | 确认：`date_window` 从未进入检索；查询无年份；Provider 无日期参数；补充检索 0 次 | 代码事实 + 实测 |
| 4 | 如果已经入库，为什么不能形成 Claim？ | 本次没有 2024 文档入库。若入库，文档级年份、8,000 字符截断和表格抽取会构成风险 | 代码事实 + 推断 |
| 5 | 如果形成 Claim，为什么全部 NOT_COMPARABLE？ | 133 条 finding 的期间为 96×2025、11×2026、10×2022、2×2023、1×2005、1×2011、12×缺失；0×2024。Verifier 的窗口检查先于一切支持判断，正确拒绝了这些年份 | 实测 |
| 6 | 哪些问题属于代码缺陷？ | 6 类（§6），其中窗口未进入检索、文档级年份覆盖是最重要的两项 | 代码事实 |
| 7 | 哪些问题属于真实数据缺失？ | 当前 8 条来源确实没有 2024 年度值；2025 公报页面中存在一个未抓取的 2024 年链接，不能据此断言公开数据缺失 | 实测 + 不可判定 |
| 8 | 应该如何修复？ | 分阶段补齐窗口传递、年度查询、期间覆盖反馈、期间抽取和区域归属；不放宽 Verifier（§7） | 建议 |
| 9 | 修复后应该增加哪些回归测试？ | 见 §8，覆盖 2024 正例、相邻年份负例、窗口传递、期间推断和区域归属 | 建议 |

一句话：**当前系统把 2024 当成“核验条件”，但没有把 2024 当成“检索条件”和“抽取条件”。**

## 1. 审计方法、数据与限制

### 1.1 实际读取的数据

第三次运行的持久化目录：

```text
experiments/quality/live_smoke_20261120_third/run/
  data/api/evidence.sqlite      # source_snapshots 8, evidence_spans 71, claims 151,
                                # verification_records 151, findings 133
  data/api/jobs.sqlite          # jobs 1, job_events 28
  data/api_jobs/007487…/raw/…/raw_docs.json
  data/api_jobs/007487…/processed/…/竹产业.json
  events.json
```

审计使用的离线方法：

- 直接读取 SQLite 的 `source_snapshots`、`claims`、`verification_records`、`findings`、`evidence_spans`；
- 用确定性 `QueryEngine.generate_research_queries("安吉县", "竹产业", "snapshot", 10)` 重建首轮查询（不触网）；
- 把每个 Claim 的 span quote 作为 `chunk_text`，离线重放 `infer_period`（不修改数据）；
- 读取 `jobs.result_json.deep_research` 中的问题树、覆盖率、gaps、conflicts 和 `retrieval_usage`。

### 1.2 不能从工件中确定的事情

- **没有查询文本**：第三次运行的 28 个事件中没有 `retrieval.round.*`，`summary.json` 只记录 `query_chars`，没有 query 原文；运行 stdout 也没有保存。
- **没有原始搜索结果集**：只持久化了最终 8 条来源；被区域闸门、去重或排序丢弃的中间结果没有落盘。第三次运行早于 `retrieval.region_filtered` 事件，collect 阶段的丢弃计数也不存在。
- **没有抓取 2024 页面**：审计禁止网络调用；2025 公报页面中的 2024 链接只作为“候选存在”的证据，不能证明其内容。

因此，下文把结论分成 **实测**、**代码事实**、**推断**、**不可判定** 四类；不把推断写成已验证根因。

## 2. 时间字段盘点

| 字段 | 当前位置 | 语义 | 本次运行的实际状态 |
| --- | --- | --- | --- |
| `published_at` | `RawDoc.published_at`、`source_snapshots.published_at` | 发布日期/公开时间 | 由 `extract_publish_date` 从 URL 或正文前 500 字猜测，不是 Provider 给的可靠字段；8 条来源中 5 条有值、3 条为空 |
| `event_date` | 不存在 | 事件发生日期 | 模型中没有该字段 |
| `valid_from` / `valid_to` | 不存在 | 统计期间的结构化起止 | 模型中没有 |
| `statistical_period` | 仅以 `claims.valid_time` 自由文本存在 | 统计/数据所属期间 | 值为 `2011`、`2022`、`2023`、`2025`、`2026` 或空；没有 2024 |
| `contract_date` | `ResearchContract.date_window` | 合约要求的时间窗 | `2024-01-01` ~ `2024-12-31`；只在 Verifier 与 brief 中使用，未进入检索 |
| `observed_time` | `claims.observed_time`、snapshot 的 `observed_at` | 抓取/观测时间 | 2026-11-20，全部相同，不能当数据年份 |
| `year_hints` | `evidence_spans.year_hints_json` | chunk 级年份提示 | 2025 公报的 chunk 里同时出现 2020–2026，包含 2024；只说明文本提到过该年，不等于数据年份 |

模型缺少 `event_date`、`valid_from`、`valid_to` 和独立的 `data_year` / `statistical_period` 字段。**本次不修改模型**；这属于后续设计项。

## 3. 第三次运行的实际数据

### 3.1 八条来源

| # | 标题（截断） | `published_at` | 正文字符 | 正文中 2024 次数 | Claim 数 | Claim 期间 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 安吉县竹产业现状及发展对策（1996 论文） | 空 | 8,000 | 0 | 5 | 缺失 |
| 2 | 2025 年安吉县国民经济和社会发展统计公报 | 2025-01-01 | 7,986 | 2 | 110 | 2025 |
| 3 | 小蜂观察：安吉县竹产业高质量发展路径分析 | 2023-01-01 | 1,039 | 0 | 2 | 2023 |
| 4 | 浙江省安吉县竹产业 2011 年预计产值可达 130 多亿 | 2011-01-01 | 2,732 | 0 | 1 | 2011 |
| 5 | 贵州省国民经济和社会发展第十五个五年规划纲要 | 2026-02-14 | 7,999 | 0 | 11 | 2026 |
| 6 | 安吉县毛竹林下食用菌栽培产业发展现状与对策（2023） | 空 | 8,000 | 0 | 2 | 2023 |
| 7 | 走进安吉，看“绿水青山就是金山银山” | 空 | 7,995 | 0 | 13 | 2022 / 2005 / 缺失 |
| 8 | 传统竹产业有了绿色新路径（发改委，URL 含 202401） | 2022-01-01 | 2,905 | 0 | 7 | 2022 |

**没有任何一条来源包含 2024 年度统计值。** 2025 公报中的两次 2024：

1. 页面导航链接 `[2024年](https://tjgb.hongheiku.com/57063.html)`（offset 192），是另一页面的入口，不是数据；
2. 正文“2024-2025 年，安吉县农村饮用水工程累计总投入资金约 3 亿元……”（offset 3682），是跨年累计项目，不是 2024 年度事实。

全库 71 个 span 中，只有 2025 公报的 chunk 6 在正文中带 2024；它对应的 15 条 Claim 共享同一段 span，内容都是 2025 年公报数据，2024 只出现在上述累计项目句里。

### 3.2 Claim 与 finding 的期间分布

`claims` 表共 151 条，`verification_records` 151 条，进入 evidence pack / `findings` 的 133 条。全部 151 条 `region_id` 都是 `安吉县`。

| 期间 | 全部 Claim | 进入 findings | Verifier 原因 |
| --- | --- | --- | --- |
| 2025 | 110 | 96 | `outside_requested_window:2025` |
| 2026 | 11 | 11 | `outside_requested_window:2026` |
| 2022 | 10 | 10 | `outside_requested_window:2022` |
| 2023 | 4 | 2 | `outside_requested_window:2023` |
| 2005 | 1 | 1 | `outside_requested_window:2005` |
| 2011 | 1 | 1 | `outside_requested_window:2011` |
| 缺失 | 14 | 12 | `claim_period_missing_for_window` |
| **2024** | **0** | **0** | — |

133 条 finding 全部 `NOT_COMPARABLE`；其中 105 条的 `period_present=true`（期间确实出现在引文中；全部 151 条 Claim 中为 118 条），但这 105 条的期间是 2025/2026/2022/等，不是 2024。`period_present` 不是失败原因；失败原因是期间本身不在窗口内。

### 3.3 离线重放 `infer_period`

把每条 Claim 的 span quote 作为 `chunk_text`，并用 Claim 的 statement、value、title 重放 `infer_period`，得到：

```text
2025: 110
缺失: 27
2022: 5
2030: 4
2005: 2
2023: 2
2018: 1
2024: 0
```

即使绕开文档级年份、改用更局部的 `infer_period`，**仍然没有 2024 Claim**。这排除了“只是年份推断写错，改一下就会出 2024”的假设。反过来，重放暴露了文档级年份的真实错误：例如 `cfe20fa7e82f` 的引文明确写“2018 年，安吉县竹产业产值达到 225 亿元”，但存储期间是 2023（论文标题年份）；`infer_period` 会正确给出 2018。

### 3.4 查询构造与 Provider

第三次运行的 7 次搜索，`query_chars` 依次为 26、28、22、25、28、31、26。它们与 `QueryEngine` 对 `安吉县`、`竹产业`、`snapshot` 确定性生成的 7 条查询长度完全对应（顺序因并发而不同）：

| 长度 | 通道 | 查询 |
| --- | --- | --- |
| 22 | gov | 安吉县 统计公报 国民经济和社会发展统计公报 |
| 26 | web | 安吉县 竹产业 总产值 规上工业 增加值 增速 占比 |
| 28 | gov | 安吉县 竹产业 十四五 产业发展规划 扶持政策 实施意见 |
| 31 | web | 安吉县 竹产业 龙头企业 链主企业 产业园 专精特新 招商引资 |
| 25 | web | 浙江省 湖州市 安吉县 竹产业 特色产业 发展现状 |
| 28 | web | 安吉县 竹产业 销售市场 品牌价值 电商 展会 外贸出口 |
| 26 | web | 安吉县 竹产业 发展瓶颈 短板 挑战 风险 要素成本 |

**7 条查询中没有一条包含“2024”或任何年份。** `QueryEngine.generate_research_queries` 没有 `date_window` / `target_years` 参数（`search/query_engine.py:74-98`）；`_generate_snapshot_queries` 也不拼接年份（`:253-320`）。Tavily 请求体只有 `query`、`search_depth`、`max_results`、`include_answer`、`include_raw_content`，没有 `start_date` / `end_date` / `days`（`search/web_search.py:104-113`）。

补充检索也没有发生：`deep_research.retrieval_usage = {"search_queries": 0, "fetched_documents": 0, "remaining_queries": 12}`，`reflection_turns = 0`，`retrieval_stop_reason = "quality_met"`。28 个事件里没有任何 `retrieval.round.started/completed`，也没有 `reflection.*`。

### 3.5 问题树与缺口

问题树有 6 个子问题，覆盖率 0.667，`q_scale`（经济规模与贡献）的 required indicators 包含“统计公报”，因此被 2025 公报满足；`gaps.detected` 只有两类：

- `q_policy`：缺少政策/规划证据；
- `q_risks`：缺少成本、短板、瓶颈、风险证据。

**没有任何“缺少 2024 年数据”的 gap。** 后续的补充检索即使发生，也不会朝 2024 定向，因为问题树和 gap 描述里没有年份。

### 3.6 冲突与区域

6 个冲突中，贵州规划参与了 2 个（产值冲突 24 条 Claim 中 7 条来自贵州；面积冲突 11 条中 4 条来自贵州）。这些 Claim 的 `region_id` 都是 `安吉县`。区域闸门已在文档级丢弃贵州规划（离线回放为 `other_region`），但 **Claim 级区域归属仍然是合约县名直接赋值**，见 §5。

## 4. 九个问题的详细回答

### 4.1 2024 年资料是否实际检索到？

**没有证据表明检索到。** 更准确地说：

- 7 条查询没有一条要求 2024；
- 8 条持久化来源中没有任何 2024 年度数据；
- 151 条 Claim 中 0 条期间为 2024；
- 唯一含 2024 的正文片段是跨年累计项目，不是年度统计值。

**不能判定**的是：Tavily 是否曾返回一个 2024 页面，随后被去重、排序前 10 或区域闸门丢弃。该运行没有保存原始结果集、查询文本或丢弃日志；第三次运行也早于 `retrieval.region_filtered` 事件。把“没检索到”写成“Provider 一定没返回”是不诚实的。

### 4.2 如果检索到了，在哪个环节被排除？

**不可判定。** 现有工件能支持的只有“排除点可能存在于以下位置”，不能确定实际发生：

1. Provider 的 `max_results=6`（smoke 守卫上限）截断；
2. `SearchCollector._dedup_and_rank` 按 URL/指纹去重后只保留 top 10；
3. 区域闸门丢弃非安吉、国家级或仅上级来源；
4. `EvidenceStore` 只抽取 10–300 字符的行、且只匹配特定数值模式，表格或长句可能不形成 Claim；
5. 8,000 字符正文截断使页面后半部分的表格没有进入抽取。

这些是机制上的候选，不是本次的实际根因证据。

### 4.3 如果没有检索到，查询策略哪里有问题？

**这是可以确认的主要根因。**

- `ResearchContract.date_window` 只被 `api/evidence_service.py:27-30` 用于 Verifier，以及 `api/brief.py:66-67` 用于文案；没有进入 `ResearchRequest`（`models.py:470-481`）、`ResearchApplication.collect_materials`（`application/research.py:51-59`）、`SearchCollector.collect`（`search/collector.py:141-193`）或 `QueryEngine`。
- Worker 把 contract 转成 request 时只传 `county`、`focus`、`mode`、`options`（`api/worker.py:130-134`）。
- `ResearchContract.to_research_spec()` 本来会设置 `target_years` 和 `QuestionSlot.time_period`（`domain/research_contracts.py:339-363`），但这个方法在 `src/` 中**没有任何调用点**。
- `QueryEngine.generate_research_spec()` / `generate_question_slots()` 不设置 `target_years` / `time_period`（`search/query_engine.py:100-144`），所以 `QuestionSlot.time_period` 为空，`AdaptiveRetrievalController` 的 temporal 评分和 `select_evidence_pack` 的 `_period_match` 都不会按 2024 过滤。
- 7 条首轮查询没有年份；Tavily 请求没有日期参数；没有第二轮。

因此，本次运行没有“定向检索 2024”这一动作；它只是做了一次通用的“安吉县 + 竹产业”检索，搜索引擎按相关性和新鲜度返回了 2025 公报、2023 文章、2022 文章等。

### 4.4 如果已经入库，为什么不能形成 Claim？

**本次没有 2024 文档入库**，所以这个问题在本轮不成立。需要区分两种未来情况：

1. **2024 年标题的统计公报**：标题含“2024年”，`EvidenceStore` 的文档级 `year_str` 会取到 2024（`evidence/store.py:139-141`），Claim 期间大概率也是 2024，Verifier 窗口可以通过。这是最理想的路径。
2. **2025 年发布、正文报告 2024 年数据的文章**：文档级 `year_str` 会取标题中的 2025，随后 `period = item.year or infer_period(...)`（`evidence/ledger.py:389-396`）会短路 `infer_period`，把 2024 数据标成 2025。这是已由 2018→2023 案例证实的机制；如果未来引入这类来源，即使数据是 2024，也会被 Verifier 拒绝为 `outside_requested_window:2025`。

另外两个风险（未在本轮实际发生，不能写成已验证）：

- 8,000 字符截断（`config.py:91`、`config.py:126`、`search/web_search.py:164`）可能把统计公报后半部分的表格切掉；
- `EvidenceStore` 只抽取 10–300 字符的行（`evidence/store.py:146-148`），表格行、跨行指标可能不形成 Claim。

### 4.5 如果形成 Claim，为什么全部 NOT_COMPARABLE？

因为 Verifier 的窗口检查是 `_decide_status` 的第一道业务判断：

```text
_decide_status
  → _window_issue(claim, window)
      period 为空            → NOT_COMPARABLE / claim_period_missing_for_window
      period 不在窗口内      → NOT_COMPARABLE / outside_requested_window:<year>
```

位置：`evidence/graph.py:1316-1359`（`_decide_status`）、`:1361-1406`（`_window_issue`）。`api/evidence_service.py:27-30` 把 contract 的 `2024-01-01`~`2024-12-31` 传进来。

133 条 finding 的分布见 §3.2：96 条 2025、11 条 2026、10 条 2022、2 条 2023、1 条 2005、1 条 2011、12 条缺失。**没有 2024，所以不是“Verifier 把 2024 判错”，而是“没有 2024 Claim 可判”。** 把窗口放宽到相邻年份会违反本任务禁止项，也不是正确的修复。

### 4.6 2023、2025、2026 年材料为什么不能支持 2024 年结论？

- 2023 文章报告的是 2018/2021/2022/2023 的数据；
- 2025 公报报告的是 2025 年数据，正文 2024 只出现在跨年累计项目；
- 2026 贵州规划是 2030 年目标（部分 Claim 被文档年份标成 2026，实际语义是 2030）；
- 2022 发改委文章报告 2022 年数据；
- 2011 文章报告 2011 年数据。

合约要求 2024-01-01~2024-12-31，Verifier 只接受期间年份落在该窗口内的 Claim。相邻年份不是 2024 的等价证据；本审计不建议放宽这条约束。

### 4.7 是否存在发布日期与事件发生日期混淆？

**存在，且有两个层面。**

1. **`published_at` 不是可靠发布日期。** `extract_publish_date`（`search/content_extractor.py:66-100`）先匹配 URL 中的 `/YYYY-MM-DD`、`/YYYYMMDD`，再匹配正文前 500 字的日期，最后取第一个 `20xx年`。Tavily 返回的 `published_date` 没有被解析（`search/web_search.py:158-177`）。结果：发改委文章 URL 明确是 `.../202401/t20240108_1363146.html`（2024-01-08），但 `published_at` 被存成 `2022-01-01`，因为正文第一段提到“2022 年全县竹产业总产值约 166 亿元”。这是典型的“发布日期 ← 正文数据年份”混淆。
2. **文档年份被当作 Claim 年份。** `EvidenceStore.extract_evidence_from_doc` 在 `full_text[:400]` 里取第一个 `20xx` 作为整篇文档的 `year_str`（`evidence/store.py:139-141`），然后给该文档的每个数值/企业/政策 Claim 都赋这个年份（`:177`、`:206`、`:278`）。`build_evidence_ledger` 又用 `item.year or infer_period(...)` 让文档年份优先（`evidence/ledger.py:389-396`）。2018→2023 的例子就是结果。

`infer_period` 本身明确不把 `published_at` 当证据（`evidence/measure.py:105-110`），这是正确的；问题在于上游的 `item.year` 把标题/页头年份塞进了 Claim，绕过了这个原则。模型里也没有 `event_date` 来区分“事件发生日”和“发布日期”。

### 4.8 补充检索是否真正针对 2024 年缺失进行定向搜索？

**没有。**

- `deep_research.retrieval_usage.search_queries = 0`、`fetched_documents = 0`；
- `reflection_turns = 0`；
- `retrieval_stop_reason = "quality_met"`；
- 事件中没有 `retrieval.round.*` 或 `reflection.*`。

原因链：

1. 第三次运行已有 8 条 `existing_docs`，`DeepResearchCoordinator` 跳过首轮 adaptive 检索（`research_agent/coordinator.py:153-180`）；
2. 进入 `AdaptiveRetrievalController.next_round` 后，`CoverageSnapshot.quality_met` 只看核心 slot 是否 complete（`search/adaptive_retrieval.py:107-116`），不看期间；
3. `assess_evidence_pack_coverage` 只按 required metrics 判断 `complete`（`:241-288`），`q_scale` 的“统计公报/总产值”等指标被 2025 公报满足，于是 `quality_met=True`，直接停止（`:321-336`）；
4. 问题树和 gaps 里没有“2024 年缺失”，所以即使生成 gap 查询，也不会带年份。

这是“主题覆盖已满足，但时间覆盖为 0”的直接机制。

### 4.9 小结：哪些是代码缺陷，哪些是数据缺失？

**代码缺陷（可复现、可定位）：**

1. `date_window` 未进入检索/查询/Provider；
2. 补充检索的停止条件不含时间覆盖；
3. 文档级年份覆盖局部期间推断；
4. 发布日期从正文年份猜测，Provider 的 `published_date` 被丢弃；
5. Claim 的 `region_id` 无条件赋合约县名；
6. 8,000 字符截断的元数据记录在截断之后，`content_truncated` 可能为 false。

**真实数据缺失（就本次语料而言）：**

- 8 条来源没有 2024 年度统计值；
- 2025 公报只报告 2025 年数据；
- 2023 文章、2022 文章、2011 文章各自报告其他年份；
- 贵州规划是 2030 年目标，不是 2024 年事实。

**不能断言的数据缺失：** 2025 公报页面导航中存在 `[2024年](https://tjgb.hongheiku.com/57063.html)`，说明至少有一个候选页面；本次没有抓取，不能据此说“2024 数据不存在”。更准确的表述是：**当前检索策略没有把 2024 候选带进语料**。

## 5. Claim 级区域授权检查

结论：**存在“REGION 文档中的 Claim 被自动赋予县域归属”的实现，而且范围比第三次运行更大——所有 Claim 都被赋值。**

### 5.1 实测

- 151 条 Claim 的 `region_id` 全部是 `安吉县`；
- 其中 11 条来自贵州规划（标题/URL/引文都不含“安吉县”）；
- 73 条 Claim 的 `region_present=false`（该检查只看 span quote，不看标题/URL；“region_present=false”不等于“标题/URL 也没有安吉县”）；
- 贵州 11 条 Claim 的 `region_in_evidence=0`（quote+title+URL 都没有安吉县）；
- 贵州 Claim 参与了 2 个冲突组（产值 24 条中 7 条、面积 11 条中 4 条）。

### 5.2 代码路径

1. `build_evidence_ledger` 无条件设置 `region_id=processed.county.name`（`evidence/ledger.py:405`）。`processed.county.name` 来自请求，不是从来源中抽取的。
2. Verifier 的 `_claim_supported_by_quote` 会检查 `claim.region_id` 是否出现在 `quote + title + url` 中（`evidence/graph.py:291-293`）；贵州 Claim 因此**不会**得到 objective support。这一层起到了兜底作用。
3. 但 `checks["region_present"]` 只检查 quote（`graph.py:1243-1248`），而且 `_decide_status` 从不用它作为独立拒绝分支（`graph.py:1316-1359`）。本轮所有贵州 Claim 先被窗口检查拦下，原因是 `outside_requested_window:2026`，而不是 `claim_region_missing`。
4. `checks["supporting_edges"]` 统计的是完整 span 的边，不是“通过 region/value/statement 校验的支持”（`graph.py:1233`）；错误区域的 Claim 仍会被计为 `supporting_edges=1`，只是 `_has_objective_support` 为 false。
5. 由于 `region_id` 被写进 `claim_identity`（`graph.py:347-355`），贵州 Claim 与安吉 Claim 落在同一个 measure/region 身份空间，才会参与冲突检测。

### 5.3 风险判断

- **当前不会把贵州 Claim 判成 SUPPORTED**：`_claim_supported_by_quote` 的区域检查会失败；这是已被代码和本轮数据支持的结论。
- **但“区域归属”本身没有被证明**：Claim 的 `region_id` 是请求层假设，不是证据层事实。一个来源如果在标题/正文中顺带提到“安吉县”，但数据实际属于另一个地区，仍可能通过 `region in quote+title+url` 的弱检查。
- 文档级区域闸门（`search/region_relevance.py`）已经挡住了“整篇来源属于其他地区”的情况；它不能替代 Claim 级归属校验。两者是不同层，**不要修改区域闸门来修 Claim 归属**。
- 本轮贵州 Claim 参与冲突，说明错误归属会污染冲突/统计层，即使最终不会被判为 SUPPORTED。

## 6. 根因清单

| 编号 | 根因 | 证据 | 级别 | 状态 |
| --- | --- | --- | --- | --- |
| RC1 | `date_window` 从未进入检索：Contract → Request → collect → QueryEngine → Provider 整条链路都没有窗口参数 | `api/worker.py:130-134`、`models.py:470-481`、`application/research.py:51-59`、`search/collector.py:141-193`、`search/query_engine.py:74-98`、`search/web_search.py:104-113` | 阻断 | 已确认 |
| RC2 | 首轮查询没有年份；7 条查询长度与 7 次搜索完全对应，全部无 2024 | §3.4；`summary.json` 的 `query_chars` | 阻断 | 已确认 |
| RC3 | 已有文档时跳过 adaptive 首轮；`quality_met` 只看主题指标，不看时间覆盖；补充检索 0 次 | `research_agent/coordinator.py:153-180`、`search/adaptive_retrieval.py:107-116/241-288/321-336`；`retrieval_usage`、`reflection_turns=0` | 高 | 已确认 |
| RC4 | 文档级年份（标题/前 400 字）覆盖局部期间推断；2018 被标成 2023，2030 被标成 2026 | `evidence/store.py:139-141`、`:177/:206/:278`、`evidence/ledger.py:389-396`；Claim `cfe20fa7e82f` | 高 | 已确认 |
| RC5 | `published_at` 从正文年份猜测，Tavily `published_date` 未解析；发改委 202401 文章被标成 2022 | `search/content_extractor.py:66-100`、`search/web_search.py:158-177`、`search/collector.py:374-378` | 中 | 已确认 |
| RC6 | Claim `region_id` 无条件赋合约县名；区域只作为支持检查的一部分，不是独立判定分支 | `evidence/ledger.py:405`、`evidence/graph.py:291-293/1233/1243-1248/1316-1359` | 高（可信度） | 已确认 |
| RC7 | 8,000 字符截断发生在抽取前，截断元数据记录在截断之后 | `config.py:91`、`config.py:126`、`search/web_search.py:164`、`processor.py:154-155/167-172` | 中 | 已确认机制；本轮未观察到 2024 被截断 |

**未确认、不能写成根因的：**

- Provider 是否返回过 2024 页面后被丢弃（无原始结果日志）；
- 2024 公报是否存在、是否可访问（未抓取）；
- 8,000 字符截断是否实际切掉了 2024 数据（当前 8 条来源没有 2024 数据，无法判断）。

## 7. 最小修复方案（等待下一阶段授权）

修复顺序很重要：**先让 2024 进入检索和抽取，再谈 Live 验证；不要先放宽 Verifier。**

### Phase 1：把时间窗传进检索（不改变 Verifier）

1. `api/worker.py` 构建 `ResearchRequest` 时传入 `date_window`（或在 `ResearchRequest.options` 中传结构化窗口；建议显式字段）。
2. `ResearchApplication.collect_materials` 把窗口传给 `SearchPort.collect(..., date_window=...)`；`SearchCollector.collect` 把它传给 `QueryEngine.generate_research_queries(..., target_years=[...])`。
3. `QueryEngine` 新增可选的 `target_years`，只在经济规模/统计公报类查询中拼接年份，例如：
   - `安吉县 2024年 统计公报 国民经济和社会发展统计公报`
   - `安吉县 竹产业 2024年 总产值 规上工业 增加值`
4. 复用已有的 `ResearchContract.to_research_spec()`（当前无调用点，`domain/research_contracts.py:339-363`），或显式设置 `ResearchSpec.target_years` / `QuestionSlot.time_period`，让 adaptive scoring 和 `select_evidence_pack` 的期间匹配真正生效。

**不要**把 `published_at` 严格限制在 2024 年内：2024 年数据常由 2025 年发布的公报承载。年份应进入查询和 Claim 期间，不应只做成发布日期过滤器。

### Phase 2：把时间覆盖纳入停止条件

在 `CoverageSnapshot` 中增加“窗口内 Claim 数 / 窗口内证据数”；`quality_met` 仅在**主题覆盖满足且窗口内至少有一条 Claim**时为真。若窗口内为 0：

- 生成一条带年份的 gap 查询（例如 `安吉县 2024年 统计公报`）；
- 发出 `gaps.detected`（gap 类型为 `period_missing`）或新的 `retrieval.period_coverage` 事件；
- 记录实际 query 文本（当前只有 `query_chars`，这是本次审计无法还原查询的直接原因）。

### Phase 3：修正期间抽取

1. `build_evidence_ledger` 改为 `period = infer_period(...) or item.year`，或仅在文档标题明确是统计公报且没有局部年份时使用 `item.year`。
2. 明确处理多年度文本：`2024-2025年` 不能作为 2024 年度事实；应标为跨年期间或拒绝。
3. 给 `valid_time` 增加可选的起止结构（`valid_from`/`valid_to`）或独立的 `data_year` 字段；本次不修改模型，作为后续设计。
4. 保持 `infer_period` 现有的“不把 `published_at` 当证据”原则（`evidence/measure.py:105-110`）。

### Phase 4：修正发布元数据

1. Tavily 解析 `published_date`；如果 Provider 给了，优先使用，而不是从正文猜。
2. `extract_publish_date` 支持 `tYYYYMMDD` / `/YYYYMM/` 这类 URL；发改委案例应得到 2024-01-08。
3. 区分 `published_at`（公开时间）和 `data_year`/`statistical_period`（数据年份）；两者不得互相覆盖。
4. 截断前记录原始长度；`content_truncated` 应反映 Provider 层和 Processor 层的真实截断。

### Phase 5：Claim 级区域归属

1. 不要用 `processed.county.name` 直接填 `region_id`；至少在 Claim 上记录“区域来自合约”还是“区域来自证据”。
2. 在 `_decide_status` 中增加独立分支：区域不在证据中 → `INSUFFICIENT` / `claim_region_not_in_evidence`，并让 `supporting_edges` 不把该边计为有效支持。
3. 保留现有文档级 `region_relevance.py` 不动；两者分别处理“整篇来源”与“单条 Claim”。

### 最小可验证路径（不付费）

用离线 fixture 构造一份“2024 年安吉县统计公报”文本，包含：

- 2024 年 GDP/竹产业产值；
- 2023 年对比值；
- 2025 年目标值。

断言：2024 值在 2024 窗口内可 SUPPORTED；2023/2025 值仍为 NOT_COMPARABLE；区域不在引文的 Claim 不得 SUPPORTED。这个 fixture 不需要任何 Provider 调用，可以在下一阶段直接落地。

## 8. 回归测试清单（建议）

| 测试 | 断言 |
| --- | --- |
| `tests/test_search_collector.py::test_collect_receives_date_window` | 传给 collector 的窗口出现在生成的查询或传给 provider 的参数中 |
| `tests/test_search_collector.py::test_year_query_generated_for_target_year` | `QueryEngine` 在经济/统计查询中包含 `2024年`，非目标年份不出现 |
| `tests/test_search_web.py::test_tavily_published_date_is_parsed` | Provider 返回的 `published_date` 进入 `published_at`，不从正文猜 |
| `tests/test_search_web.py::test_url_timestamp_is_not_overridden_by_content_year` | `.../202401/t20240108...` 得到 2024-01-08，而不是正文里的 2022 |
| `tests/test_adaptive_retrieval.py::test_quality_not_met_without_in_window_claim` | 主题覆盖满足但窗口内 0 条时，`quality_met=False` |
| `tests/test_adaptive_retrieval.py::test_period_gap_generates_year_query` | 生成 `2024年` 定向查询，并记录 query 文本 |
| `tests/test_measure_identity.py::test_infer_period_prefers_local_data_year` | 2023 论文中的 2018 数值推断为 2018，不是 2023 |
| `tests/test_measure_identity.py::test_multi_year_span_is_not_single_year` | `2024-2025年` 不产生 2024 年度 Claim |
| `tests/test_evidence_store.py::test_document_year_does_not_override_claim_period` | 文档标题年份不覆盖引文中的明确数据年份 |
| `tests/test_evidence_graph.py::test_2024_claim_in_window_is_supported` | 2024 引文 + 2024 窗口 → `SUPPORTED` |
| `tests/test_evidence_graph.py::test_2023_and_2025_claims_stay_outside_2024_window` | 相邻年份仍为 `NOT_COMPARABLE` |
| `tests/test_evidence_graph.py::test_claim_region_not_in_evidence_cannot_be_supported` | 贵州式 Claim（region_id=安吉县、证据无安吉）不得 SUPPORTED，原因应为区域相关 |
| `tests/test_research_application.py::test_contract_window_reaches_collector` | 应用层把 contract 窗口传给 search port（spy） |
| `tests/test_api_app.py::test_worker_passes_contract_date_window` | API/worker 路径不再丢失 `date_window` |
| `tests/test_source_contract.py::test_truncation_metadata_reflects_provider_truncation` | 8,000 字符截断被标记，而不是 `content_truncated=False` |

## 9. 可复现证据与命令

本次审计使用的离线命令（均不触网、不写运行工件）：

```bash
# 表计数
python - <<'PY'
import sqlite3
con=sqlite3.connect('experiments/quality/live_smoke_20261120_third/run/data/api/evidence.sqlite')
for t in ('source_snapshots','claims','verification_records','findings','evidence_spans'):
    print(t, con.execute(f'select count(*) from {t}').fetchone()[0])
PY

# 期间分布 / 拒绝原因
python - <<'PY'
import sqlite3
con=sqlite3.connect('experiments/quality/live_smoke_20261120_third/run/data/api/evidence.sqlite')
for row in con.execute('select valid_time,verification_reason,count(*) from claims group by 1,2 order by 3 desc'):
    print(row)
PY
```

关键工件：

- `experiments/quality/live_smoke_20261120_third/summary.json`：`guard.search_events` 的 7 个 `query_chars`、`deep_research.retrieval_usage`、来源列表；
- `.../run/data/api/evidence.sqlite`：151 条 Claim、151 条验证记录、133 条 finding；
- `.../run/events.json`：28 个事件，无 `retrieval.round.*` / `reflection.*`；
- `.../run/data/api_jobs/.../raw/安吉县/20261120/raw_docs.json`：8 条来源的 `published_at`、正文和 `content_original_length`。

## 10. 待授权事项

本审计没有修改任何代码或运行工件，也没有调用付费 API。下一阶段若要实施 §7，需要新的实施授权；若要验证修复后的真实检索，还需要单独的第 **四次** Live 授权。本报告基于 `aaa6a09`，仅作为文档提交，不改变代码或运行工件。
