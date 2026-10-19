# Evidence-First v2 Refactor Audit

审计入口：[`ARCHITECTURE_BASELINE_AUDIT.md`](../../../ARCHITECTURE_BASELINE_AUDIT.md)

当前判断：`PHASE_1_EVIDENCE_PRESERVATION_IN_PROGRESS`；Phase 0 基线审计已完成。

已确认的 P0 根因是 C 组来源归档契约不一致：真实德清 snapshot C 的 RawDoc、ProcessedData、EvidenceStore 和 LLM context 保留了目标事实，但历史 `sources.json` 只保存报告路径和章节名称，导致离线 Claim 评分无法读取 C 的正文证据。新的 `serialize_source_documents()` 已完成初步接入，历史产物保持不变。

Phase 1 初始保真门已通过：真实德清 C 重放保留四个目标事实，新的 Source Contract 生成 2 个 source documents / 24 个 chunks，并记录正文哈希、抓取状态、来源元数据和 offsets。`pytest --no-cov -q` 为 `502 passed`（另有一个 Windows `.pytest_cache` 权限警告），变更范围 Ruff clean。Phase 1 仍未完成，后续必须补齐 Phase 3 结构化 contracts 和历史离线重评分版本。

Phase 2 已完成离线评价门：`NON_COMPARABLE` 与 `CONTRADICTED` 分离，continuation matched-budget 的 48 个 run / 240 条 Claim 已生成 v4 offline rescore，Provider/Judge calls 均为 0；旧 v3 结果未覆盖。详见 [`PHASE2_EVALUATION_AUDIT.md`](../../../PHASE2_EVALUATION_AUDIT.md)。

本文件不是最终性能结论。最终工程验收和研究验收必须分别依据 Phase 1–8 的测试、离线回放、成本记录和独立评分证据判断。

