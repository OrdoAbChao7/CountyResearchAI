# Phase 4 — QuestionSlot 驱动自适应检索

状态：`ENGINEERING_COMPLETE / OFFLINE_REPLAY_INCONCLUSIVE`

## 目标与实现

检索计划现在按 snapshot、rise-fall、long-history 生成不同 QuestionSlot；文档评分明确记录任务相关度、县域范围、时期匹配、指标覆盖、来源可靠性和新颖性，并对 URL/正文重复项确定性去重。EvidencePack 缺口生成带 `slot_id`、`expected_metrics` 和 `gap_id` 的追问；控制器按质量、预算、零边际证据、无缺口查询及最大轮数停止。

`DeepResearchCoordinator` 对支持 adaptive 接口的 Collector 使用新路径，并在 `DeepResearchResult` 暴露 ResearchSpec、EvidencePacks、停止原因和 Search/返回文档用量；不支持该接口的旧 Collector 保留原反思路径。Adaptive Collector 对结果使用 slot-aware 排序，而非重新落回通用重排。Fetch 计数保留实际观测值，即使超出预算上限也不会静默截断；剩余预算归零后不再安排新一轮。

## 验证

- Focused：`pytest --no-cov -q tests/test_adaptive_retrieval.py tests/test_multi_agent_research.py` → 13 passed。
- 全量：`pytest --no-cov -q` → 532 passed，1 个 Windows `.pytest_cache` 写入权限警告。
- 改动范围 Ruff：通过。
- 离线回放：`PYTHONPATH=src python scripts/evaluate_adaptive_retrieval_offline.py`，0 Provider/Judge calls。

## 历史归档回放结果

脚本在相同的存档文档、相同的 slot 查询、top-3 截断下比较通用 `rerank_documents` 与 slot-aware 排序的必需指标命中率。它只隔离排序差异，不是完整搜索规划的端到端对照。

| 模式 | 地区 | RawDoc 数 | Legacy 命中率 | Adaptive 命中率 |
| --- | --- | ---: | ---: | ---: |
| snapshot | 临泽县 | 2 | 19.44% | 19.44% |
| rise-fall | 临泽县 | 2 | 21.67% | 21.67% |
| long-history | 于都县 | 2 | 41.67% | 41.67% |

三组完全持平。每组仅有 2 条 RawDoc，指标命中来自同一小型存档，样本不足以判断召回改进；本阶段不宣称质量提升。脚本路径和档案选取均固定，原实验数据未修改。

## 文件与已知限制

- 新增 `src/county_research_ai/search/adaptive_retrieval.py`、`tests/test_adaptive_retrieval.py`、`scripts/evaluate_adaptive_retrieval_offline.py`。
- 修改 QueryEngine、Collector、ResearchCritic、QuestionTree adapter 和 DeepResearchCoordinator；新增端到端字段断言。
- 首版检索评分是确定性词项匹配，不做语义召回；历史档案过小，未证明任务相关事实召回提升。
- 当前 `fetched_documents` 是 Collector 返回的 RawDoc 数，不等于底层 Provider 的网络 Fetch 请求数。若 Provider 将 Search/Fetch 分开计费，需后续增加其真实用量回传，不能将此数字当作网络请求量或费用。
- 没有调用任何真实或付费 Provider。

## 验收判断

工程验收通过：不同模式计划、县域优先排序、缺口反馈、停止条件、真实返回量记录和深度研究流程接入均有测试。研究效果验收未通过/未定：离线样本太小且无召回差异。Phase 4 可进入后续架构阶段，但不得据此声称适应性检索提高了事实覆盖。
