# Phase 3 Evidence Architecture

审计日期：2026-10-19  
分支：`codex/evidence-first-v2`

## 结论

Phase 3 已完成工程验收：核心 Evidence-First contracts 使用 Pydantic 定义，legacy `RawDoc`/`ProcessedData` 可以通过 adapter 建立 Source → Chunk → Claim → EvidencePack 关系，`ResearchApplication.build_evidence()` 在缓存命中和新处理两条路径都会挂载 Ledger 与 EvidencePack。分析输入优先消费挂载的 EvidencePack，报告输出证据包状态、缺口和来源映射。

本阶段没有新的 Provider 调用，也没有改写旧实验产物。Phase 3 证明的是数据架构和 legacy 接线，不宣称模型写作质量已经改善。

## Canonical contracts

`src/county_research_ai/domain/research_contracts.py` 提供：

- `ResearchSpec`：区域、模式、研究重点、目标年份、问题槽、预算和架构版本；
- `SourceDocument`：canonical URL、正文哈希、发布时间、抓取时间、来源类型、行政范围和原始存储路径；
- `EvidenceChunk`：文档关系、正文、heading、offset、年份/指标提示和内容哈希；
- `AtomicClaim`：区域、指标、数值、单位、期间、行政范围、统计口径、序列版本、来源和 chunk 关系；
- `QuestionSlot`：研究问题、必需指标、区域/期间、优先级、证据要求、完成状态和预算；
- `EvidencePack`：选中的 claims/chunks、source map、预算、排除原因、缺口和完成状态。

未知坐标使用 `None + offset_status=unknown`，不伪造原文偏移。旧字段名通过输入 validator 和只读 compatibility property 兼容，canonical `model_dump()` 仍输出结构化字段。

## Ledger and adapter behavior

`src/county_research_ai/evidence/ledger.py` 实现：

- source/chunk/claim 插入与 ID/关系校验；
- 同一 canonical URL 的转载关系 `same_source_repost`，不当作独立来源；
- claim 到 chunk/source 的反向查询；
- 基于 QuestionSlot 指标命中、已关联 claim 和字符预算的确定性 EvidencePack 选择；
- verified 状态的证据约束：没有 evidence chunk 时自动降为 `unverified`，并写入 `no_evidence_chunk`；
- 同区域、指标、期间、行政范围、统计口径和版本的数值比较；亿元/万元等支持单位在 Ledger 内归一到万元后比较。

`build_evidence_ledger(ProcessedData)` 保留旧模型，同时写出 canonical SourceDocument/EvidenceChunk/AtomicClaim。`EvidencePack` 被挂载回 `ProcessedData`，因此现有 analyzer 仍使用原接口，但 `render_for_llm()` 会优先渲染 selected chunks 和来源链接；三种 legacy mode 的报告也追加 Evidence-First 证据包审计段落。

## Verification

永久回归覆盖：

- Pydantic schema round-trip 和 unknown offset；
- 同一来源转载关系和 chunk/source 追溯；
- 预算选择、缺口和排除原因；
- 版本化事实保持独立；
- 单位归一化；
- 无 chunk 不得 verified；
- legacy adapter 把真实 GDP claim 追溯到来源、EvidencePack 和 LLM context；
- 应用缓存命中与新处理路径均挂载结构化证据。

验证命令：

```text
.venv\Scripts\python -m pytest tests/test_evidence_ledger.py tests/test_research_application.py tests/test_mode_registry.py -q
18 passed, 1 Windows .pytest_cache permission warning

.venv\Scripts\ruff.exe check <changed Phase 3 source and test files>
All checks passed!

.venv\Scripts\python -m pytest --no-cov -q
527 passed, 1 Windows .pytest_cache permission warning
```

## Remaining boundary

Phase 3 的 Ledger 是稳定的内存中枢和 legacy adapter；QuestionSlot 的多阶段检索计划、MMR/语义排序、缺口补检和资源 stop reason 留给 Phase 4。Evidence-bound 专业 Agent 消费和事实核验留给 Phase 5。旧 `RawDoc`、`ProcessedData` 和 historical artifacts 继续保留，便于离线 replay 和前后版本比较。
