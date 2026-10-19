# Phase 1 Evidence Preservation Report

审计日期：2026-10-19  
分支：`codex/evidence-first-v2`

## 结论

Phase 1 的第一道证据保真门已通过：真实德清 snapshot C 的四个目标事实在离线重放中从 RawDoc 经 ProcessedData、EvidenceStore 和有预算的 LLM context 一直保留，并可由新的 Source Contract 重新生成带正文、哈希、来源元数据和 chunk 映射的 `sources.json`。

本阶段仍保持 `IN_PROGRESS`，因为当前 Source Contract 是面向 legacy `RawDoc` 的确定性 adapter，不是 Phase 3 的最终 Pydantic 证据架构；历史 C 产物没有被迁移，旧的任务级 report 仍然可能缺少事实。这份报告记录的是新写出路径和离线重放的工程验证，不宣称已有 Provider 独立实验效果提升。

## 真实产物重放

重放目标：

`experiments/independent_comparison/runs/continuation_natural_stage_b_deepseek_flash_20261019/continuation_natural_stage_b_deepseek_flash_20261019_region_01_snapshot_r1_C/`

四个必保留事实：`722.5` 亿元、`5.8%`、`300.6` 亿元、`7.7%`。

| 阶段 | 结果 | 四个事实 |
| --- | ---: | --- |
| RawDoc | 2 docs | 全部保留 |
| ProcessedData | 2 docs | 全部保留 |
| EvidenceStore | 231 items | 全部保留；长文本和单行统计均可抽取 |
| LLM context | 15,000 chars | 全部保留；2 个来源均 included，均有 `budget_excerpt` |
| Source Contract | 2 documents / 24 chunks | 全部保留；正文、URL、哈希、时间戳和 chunk offsets 可用 |

本次上下文审计的 `allocated_chars` 为每个来源 7,382 字符；`excluded_doc_indices=[]`，说明预算不足时没有静默丢弃后续县级来源。旧 C 的 `sources.json` 仍是只含 `report_path` 和 `sections` 的元数据对象，历史文件保持不变。

## 实现内容

### 正文保真与截断可见性

- `DocumentProcessor` 保留换行边界，记录 `content_original_length`、`content_truncated` 和 `truncation_reason`。
- `EvidenceStore` 对长段落和压缩单行统计使用带重叠的分段，保持指标、数值和单位的邻接关系。
- `ProcessedData.render_for_llm()` 在预算内为所有来源预留标题，并以来源优先级分配正文；当发生预算摘录时写入 `ContextRenderAudit`，而不是静默切掉来源。
- 全国 GDP 通过文档标题和正文范围判定为 `全国范围`，德清县 GDP 判定为 `县域本级`；两者不会因为数字形态相似而互相替代。

### Source Contract

`src/county_research_ai/evidence/source_contract.py::serialize_source_documents()` 为新实验写出路径提供统一的 JSON adapter，至少包含：

- 稳定的 `doc_id`、`content_hash`、`canonical_url`；
- `fetch_status`、`provider`、`source_type`、`document_timestamp`、`published_at`、`retrieved_at`；
- 完整 `content` 或明确的 `snippet_only` 状态；
- 每个 source 的确定性 `chunks`，包含 `chunk_id`、`text`、`start_offset`、`end_offset`、`content_hash`。

`experiment_agents`、independent smoke 的 C 写出路径和 fixed-input worker 共用同一 adapter。现有 A/B/C 产物 writer 仍保留原有 manifest/hash 机制。

## 验证证据

新增或扩展的永久回归覆盖：

- 真实德清 RawDoc/ProcessedData 离线回放和旧 metadata-only archive 不可变性；
- 换行清洗、压缩单行统计、长文本 metric/value/unit 邻接；
- 显式正文截断原因；
- 上下文预算审计和晚出现的县级事实保留；
- 全国 GDP 与德清县 GDP 的行政范围区分；
- Source Contract 的确定性序列化、正文哈希、chunk offsets 和 `snippet_only`/`fetched` 状态。

验证命令和结果：

```text
.venv\Scripts\python -m pytest --no-cov -q
502 passed, 1 Windows .pytest_cache permission warning

.venv\Scripts\python -m ruff check <all changed production and test files>
All checks passed!
```

全仓库 Ruff 仍有 73 个历史 findings，主要集中于既有 `scripts/_verify_*.py`，本阶段没有把它们误记为 Phase 1 新问题。

## 剩余限制与下一阶段边界

1. Source Contract 目前是 dict-based legacy adapter，尚未提供 Phase 3 所需的 `SourceDocument`、`EvidenceChunk`、`AtomicClaim`、`QuestionSlot` 和 `EvidencePack` Pydantic contracts。
2. chunk offsets 是序列化后正文的确定性 offset；当上游只提供 snippet 或经过清洗时，尚未有 raw-to-clean offset mapping，也不会伪造该映射。
3. 当前上下文 renderer 是预算感知的保真止损层，不是按 Claim/QuestionSlot 选择证据的完整 EvidencePack；任务相关选择和独立评价留给 Phase 2–4。
4. 历史 report、sources archive 和历史 score 不被回写；历史结果需要在 Phase 2 通过新 contract 离线重评分并写入新版本输出。

