# 2024 时间覆盖与 Claim 级区域修复报告

日期：2026-11-20
分支：`codex/finish-roadmap`
工作树：`E:\Projects\CountyResearchAI-finish-roadmap`
实施起点：`d7a5dc4b3fa3bf8648487af418bee3e3971d0fb4`
代码 HEAD：`d186577`
依据：`docs/goal/2024_PERIOD_COVERAGE_AUDIT.md`

性质：离线实施与离线测试。未调用真实付费 LLM/搜索 API，未修改 `.env`，
未执行 Git Push，未合并主线，未修改主工作区或其他 worktree，未放宽
Verifier，未制造 2024 年数据。

## 1. 结果摘要

| Phase | Commit | 状态 |
| --- | --- | --- |
| 1. Claim 级区域归属 | `e8021c8` | 完成 |
| 2. `date_window` 全链路传递 | `36a7c4f` | 完成 |
| 3. Adaptive Retrieval 时间覆盖停止条件 | `1da579c` | 完成 |
| 4. `infer_period` / Claim 期间修复 | `1f08ba1` | 完成 |
| 5. 日期解析与内容截断 | `c6d98a6` | 完成 |
| 补充回归：相邻年份窗口 | `d186577` | 完成 |

最终验证：

| 检查 | 结果 |
| --- | --- |
| 新增/相关目标回归（8 个模块） | `85 passed in 1.10s` |
| P0 三个模块 | `49 passed in 2.96s` |
| 全量后端 | `827 passed in 35.24s` |
| Ruff | `ruff check src tests` → `All checks passed!` |

真实 2024 检索与 Live outcome 未验证，见 §8。

## 2. Phase 1：Claim 级区域归属

### 修复内容

- 新增 `evidence/claim_region.py:36` 的 `ClaimRegion` 与
  `classify_claim_region`（`:119`），对每条 Claim 独立判断：
  1. Claim 原文出现完整县名 → 目标县；
  2. Claim 原文出现其他地名 → 其他区域；
  3. 出现全国/省级/市级范围 → 对应范围；
  4. Claim 本身无地名时，才参考标题/URL 的文档级区域；
  5. 标题同时出现目标县与其他区域、而 Claim 无地名 → `UNKNOWN`；
  6. 其余保持 `UNKNOWN`。
- `models.py` 的 `EvidenceItem` 与 `domain/research_contracts.py` 的
  `AtomicClaim` 增加 `region_source`（`claim` / `document` / `scope` /
  `unknown`），用于区分区域来源。
- `evidence/store.py` 的数值、政策、企业抽取均调用 Claim 分类；
  `get_target_items()`（`:343`）与 `_is_target_region`（`:355`）只返回目标县
  Claim；`detect_conflicts`、`assess_question_tree_coverage`、引用表均使用
  目标县条目。
- `evidence/ledger.py` 的 `_claim_region_allowed`（`:41`）与
  `select_evidence_pack` 排除跨区域 Claim；`build_evidence_ledger`（`:351`）
  为每条 Claim 写入区域。
- `evidence/graph.py` 的 `region_present` 使用引文 + 来源标题/URL 判断
  （`:1262`）；`_region_issue`（`:1388`）使 `UNKNOWN`、跨区域、
  `region_present=false` 的 Claim 不能 `SUPPORTED`。
- 只给 `search/region_relevance.py` 增加了公开包装函数，未修改原有分类规则。

### 测试

- `tests/test_claim_region.py`：县域统计 Claim 允许；贵州规划不归属安吉；
  同一篇同时提安吉与贵州的文章产生不同 Claim 区域；UNKNOWN 不被提升；
  跨区域 Claim 不参与目标县冲突；`region_present=false` 阻断支持；
  仅有行政范围不足以归属。
- `tests/test_evidence_store.py` 的冲突夹具补充了明确县名，冲突断言未改变。
- P0 的三个模块全部通过。

## 3. Phase 2：`date_window` 全链路传递

### 修复内容

- `models.py:486` 的 `ResearchRequest` 增加可选 `date_start` / `date_end`，
  并由 `target_years` / `time_period` 派生目标年份和期间；默认 `None`，
  保持旧调用兼容。
- `api/worker.py:60` 的 `request_from_contract` 复用
  `ResearchContract.to_research_spec()` 与 `date_window`，JobRunner 不再手工
  构造丢失窗口的请求。
- `application/research.py:51` 把窗口传给 `SearchPort.collect`；
  `ports/search.py:11`、`infrastructure/search_adapter.py`、`agent/tools.py`
  的条件参数保持向后兼容。
- `search/collector.py:142` 接收窗口与目标年，并传给
  `QueryEngine.generate_research_queries`（`query_engine.py:122`）。
- `query_engine.py` 为 snapshot、rise-fall、long-history 生成目标年查询；
  snapshot 统计公报查询形如
  `安吉县 2024年 统计公报 国民经济和社会发展统计公报`。
- `ResearchSpec.target_years` 与每个 `QuestionSlot.time_period` 被真实赋值，
  使排序和证据包期间匹配生效。
- **不按网页发布日期过滤**：2025 年发布的公报可以承载 2024 年数据。

### 测试

- `tests/test_date_window_propagation.py`：请求派生年份/期间；contract →
  request 复用 spec；三种模式都出现目标年；spec 的每个 slot 携带期间；
  应用层把窗口传给 search port；collector 把年份写入真实 query；
  2025 年发布但含 2024 年数据的页面不被过滤。

## 4. Phase 3：Adaptive Retrieval 时间覆盖停止条件

### 修复内容

- `search/adaptive_retrieval.py:27` 新增 `claim_period_in_window`：只有 Claim
  的全部年份都落在目标年份内才算窗口内；空期间不提升；`2024-2025` 不算
  2024 年度事实。
- `CoverageSnapshot`（`:106`）增加目标年、已选 Claim 数、窗口内 Claim 数、
  窗口内来源数；`topic_coverage_met` 与 `period_coverage_met` 分离，
  `quality_met` 同时要求两者成立。
- `assess_evidence_pack_coverage`（`:298`）统计窗口内 Claim/来源。
- `AdaptiveRetrievalController.next_round`（`:414`）在期间缺口时生成目标年
  补充查询；`QueryEngine.generate_period_queries`（`query_engine.py:156`）
  生成形如 `安吉县 2024年 统计年鉴 统计公报 主要经济指标` 的查询。
- `research_agent/coordinator.py:223` 每轮发出
  `retrieval.period_coverage` 事件，记录轮次、目标年、主题/期间覆盖、
  窗口内 Claim/来源；`retrieval.round.started` 记录真实 `query_texts`。
- `DeepResearchResult` 增加 `period_coverage` 与
  `period_coverage_history`（`:79`），并由 `api/worker.py:387` 投影到 job
  结果。
- 保留最大轮次/查询/抓取预算；没有为达到阈值放宽 Verifier。目标年资料不存在
  时最终仍可为 `INSUFFICIENT_DATA` / `NO_PROGRESS`。

### 测试

- `tests/test_adaptive_retrieval.py`：主题覆盖满足但窗口内 0 条时
  `quality_met=False`；窗口内 Claim 满足期间覆盖；期间缺口生成 `2024年`
  查询；`2024-2025` 不算单年。
- `tests/test_period_coverage_flow.py`：协调器发出每轮期间覆盖事件，
  启动事件记录真实查询文本，结果保存历史。

## 5. Phase 4：Claim 期间推断

### 修复内容

- `evidence/measure.py:136` 新增 `infer_claim_period`：
  1. Claim 原文出现多个年份 → 返回跨年区间（如 `2024-2025`），不折叠为单年；
  2. 原文单一年份 → 直接使用；
  3. 通过数值上下文推断 → 使用；
  4. 原文/标题/证据块出现年份但无法无歧义解析（如发布标签、歧义数值）→
     保持空期间；
  5. 完全没有年份上下文时才使用文档年。
- `evidence/ledger.py:414` 改用该函数，不再让 `item.year` 覆盖 Claim 本地年份。
- `evidence/store.py:145` 的文档年改为只接受一个无歧义数据年；多个年份或
  发布标签年份不再成为整篇文档的年份。
- `evidence/graph.py:1408` 的窗口检查由“任一 overlap 即可”收紧为“区间内所有
  年份都必须在窗口内”；`2024-2025` 对 2024 窗口返回
  `outside_requested_window:2025`。这是收紧，不是放宽。
- `infer_period` 原有行为保留，`published_at` 仍不作为事实年份。

### 测试

- `tests/test_measure_identity.py`：2023 文档中的 2018 Claim → 2018；
  2026 规划中的 2030 目标 → 2030；跨年保留 `2024-2025`；仅无任何年份时用
  文档年；只有发布年份的 Claim → 空。
- `tests/test_evidence_ledger.py`：文档标题年份不覆盖引文 2018；规划目标
  2030 不变成文档年 2026。
- `tests/test_evidence_graph.py`：跨年 Claim 在 2024 窗口拒绝；2023/2025
  Claim 在 2024 窗口拒绝。

## 6. Phase 5：发布日期解析与内容截断

### 修复内容

- `search/content_extractor.py:109` 新增 `parse_published_date`，支持
  ISO-8601、RFC/HTTP 日期、Unix 时间戳和中文日期；只写入 `published_at`，
  不推导事实期间。
- `extract_publish_date`（`:146`）：
  - URL 优先，支持政府站 `tYYYYMMDD`（如
    `/202401/t20240108_123.html`）、`/YYYY/MM/DD/`、`/YYYYMM/`（月精度）；
  - 正文只在出现“发布时间/发布日期/更新时间/成文日期”等明确标签时解析；
  - 删除“正文前 500 字任意年份”兜底，避免把正文事件日期当成发布日期。
- `search/web_search.py:67` 新增 `_prepare_content`；Tavily、Serper、Bing
  解析 provider 发布日期并在截断时记录：
  - `content_original_length`：截断前长度；
  - `content_truncated=True`；
  - `truncation_reason=detail_max_chars:<n>`。
- DeepSeek 结果也解析 `published_date`；原 metadata 保留原始字段。
- `processor.py` 保留 provider 已记录的原始长度与截断状态，不覆盖为“未截断”。

### 测试

- `tests/test_search_web.py`：Tavily `published_date=2024-01-08` 进入
  `published_at`，正文 2018 年仍是正文；provider 截断记录原长、状态、原因。
- `tests/test_deep_retrieval.py`：URL `t20240108` 优先于正文 2018 年；
  `/202401/` 月精度；正文单独日期不再当发布日期。
- `tests/test_source_contract.py`：截断审计字段继续被序列化保留。
- `tests/test_evidence_preservation_regression.py`：processor 截断仍记录原长。

## 7. 回归测试与审计清单映射

审计报告 §8 的 15 条建议测试均已覆盖或由等价测试覆盖：

| 审计建议 | 本仓库对应测试 |
| --- | --- |
| `test_collect_receives_date_window` | `test_application_passes_window_to_search_port`、`test_collector_sends_target_year_into_real_queries` |
| `test_year_query_generated_for_target_year` | `test_query_engine_adds_the_target_year_for_every_mode` |
| `test_tavily_published_date_is_parsed` | `TestTavilyProvider::test_published_date_is_parsed_and_body_year_stays_body_text` |
| `test_url_timestamp_is_not_overridden_by_content_year` | `test_url_timestamp_is_not_overridden_by_a_body_year` |
| `test_quality_not_met_without_in_window_claim` | 同名测试 |
| `test_period_gap_generates_year_query` | 同名测试 |
| `test_infer_period_prefers_local_data_year` | 同名测试 |
| `test_multi_year_span_is_not_single_year` | `test_infer_claim_period_keeps_multi_year_span`、`test_multi_year_claim_is_not_a_single_target_year_fact` |
| `test_document_year_does_not_override_claim_period` | `test_claim_period_uses_the_quote_year_not_the_document_year` |
| `test_2024_claim_in_window_is_supported` | `test_api_evidence_service.py::test_claims_outside_requested_window_are_not_comparable` 中 `claim-good` 在 2024 合约窗口下为 `SUPPORTED` |
| `test_2023_and_2025_claims_stay_outside_2024_window` | `test_adjacent_year_claims_stay_outside_the_2024_window` |
| `test_claim_region_not_in_evidence_cannot_be_supported` | `test_claim_region.py` 的 `region_present` 与跨区域用例 |
| `test_contract_window_reaches_collector` | `test_application_passes_window_to_search_port`、`test_contract_to_request_reuses_to_research_spec` |
| `test_worker_passes_contract_date_window` | `request_from_contract` 单测；API 路径使用同一函数 |
| `test_truncation_metadata_reflects_provider_truncation` | `TestTavilyProvider::test_provider_truncation_records_original_length`、`test_source_contract_preserves_truncation_audit_fields` |

## 8. 未解决问题与未验证事项

1. **没有第四次付费 Live**。真实 Provider 是否返回 2024 年资料、目标年查询
   是否命中、最终 outcome 是否改善，均未验证。当前结论仅为工程修复。
2. **没有制造 2024 数据**。若公开资料中缺少目标年，系统会保持
   `INSUFFICIENT_DATA` / `NO_PROGRESS`，这是预期行为。
3. **区域分类器未重写**。`search/region_relevance.py` 只增加公开包装；文档级
   短名规则仍是既有逻辑。Claim 级分类是新增的第二层，而不是替换文档闸门。
4. **`EvidenceItem.year` 仍用于展示/冲突分组**，不是 Claim 核验的唯一期间来
   源；Claim 期间以 `infer_claim_period` 为准。多来源冲突分组可能仍需后续
   细化到 measure + period 的联合键。
5. **跨年区间的窗口语义已收紧**。`2024-2025` 不再满足 2024 单年窗口；若业务
   需要“区间包含目标年即可”，需要单独设计，而不是放宽当前实现。
6. **前端未改**。`period_coverage` 只进入 worker 的 deep-research 投影；
   UI 展示不在本次授权范围。
7. **`scripts/` 存在既有 Ruff 告警**。本次验收范围是 `ruff check src tests`；
   全仓 `ruff check .` 会报告历史脚本问题，未在本任务中修改。
8. **任务描述中的 `search/processor.py` 不存在**。正文清洗与截断实际位于
   `src/county_research_ai/processor.py`，本次已检查并保持 provider 元数据；
   `config.py` 的 `detail_max_chars` / `max_evidence_length` 阈值未修改。

## 9. 文件变更范围

源码：

- `src/county_research_ai/api/worker.py`
- `src/county_research_ai/api/evidence_service.py`
- `src/county_research_ai/agent/tools.py`
- `src/county_research_ai/application/research.py`
- `src/county_research_ai/domain/research_contracts.py`
- `src/county_research_ai/evidence/claim_region.py`（新增）
- `src/county_research_ai/evidence/graph.py`
- `src/county_research_ai/evidence/ledger.py`
- `src/county_research_ai/evidence/measure.py`
- `src/county_research_ai/evidence/store.py`
- `src/county_research_ai/evidence/verifier.py`
- `src/county_research_ai/infrastructure/search_adapter.py`
- `src/county_research_ai/models.py`
- `src/county_research_ai/modes/{snapshot,rise_fall,long_history}.py`
- `src/county_research_ai/ports/search.py`
- `src/county_research_ai/research_agent/coordinator.py`
- `src/county_research_ai/search/adaptive_retrieval.py`
- `src/county_research_ai/search/collector.py`
- `src/county_research_ai/search/content_extractor.py`
- `src/county_research_ai/search/query_engine.py`
- `src/county_research_ai/search/region_relevance.py`（仅公开包装）
- `src/county_research_ai/search/web_search.py`

测试：

- `tests/test_claim_region.py`（新增）
- `tests/test_date_window_propagation.py`（新增）
- `tests/test_period_coverage_flow.py`（新增）
- `tests/test_adaptive_retrieval.py`
- `tests/test_deep_retrieval.py`
- `tests/test_evidence_graph.py`
- `tests/test_evidence_ledger.py`
- `tests/test_evidence_store.py`
- `tests/test_measure_identity.py`
- `tests/test_research_application.py`
- `tests/test_search_web.py`

文档：

- `docs/goal/STATE.md`
- `docs/goal/ACCEPTANCE.md`
- `docs/goal/EXECUTION_LOG.md`
- `docs/goal/2024_PERIOD_COVERAGE_AUDIT.md`
- `docs/goal/2024_PERIOD_COVERAGE_FIX_REPORT.md`（本文件）

## 10. 停止状态

五个 Phase 已独立提交、独立测试。工作树在本次修复提交后保持干净（文档提交除
外）。按授权要求停止，不执行第四次 Live、不 Push、不合并主线；等待下一次 Live
授权。
