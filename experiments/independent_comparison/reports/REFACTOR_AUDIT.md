# Evidence-First v2 Refactor Audit

审计入口：[`ARCHITECTURE_BASELINE_AUDIT.md`](../../../ARCHITECTURE_BASELINE_AUDIT.md)

当前判断：`PHASE_6_ENGINEERING_PARTIAL / TOKEN_EFFECT_PENDING`；Phase 0 基线审计已完成。

已确认的 P0 根因是 C 组来源归档契约不一致：真实德清 snapshot C 的 RawDoc、ProcessedData、EvidenceStore 和 LLM context 保留了目标事实，但历史 `sources.json` 只保存报告路径和章节名称，导致离线 Claim 评分无法读取 C 的正文证据。新的 `serialize_source_documents()` 已完成初步接入，历史产物保持不变。

Phase 1 保真门已通过：真实德清 C 重放保留四个目标事实，新的 Source Contract 生成 2 个 source documents / 24 个 chunks，并记录正文哈希、抓取状态、来源元数据和 offsets。Phase 3 已补齐 canonical Pydantic contracts 与 Ledger adapter，历史 source archive 仍保持不变。

Phase 2 已完成离线评价门：`NON_COMPARABLE` 与 `CONTRADICTED` 分离，continuation matched-budget 的 48 个 run / 240 条 Claim 已生成 v4 offline rescore，Provider/Judge calls 均为 0；旧 v3 结果未覆盖。详见 [`PHASE2_EVALUATION_AUDIT.md`](../../../PHASE2_EVALUATION_AUDIT.md)。

Phase 3 已完成结构化证据架构门：六类 Pydantic contracts、Source → Chunk → Claim Ledger、预算感知 EvidencePack 和 legacy workflow adapter 均有 focused regression coverage。EvidencePack 进入 analyzer 的 `ProcessedData.render_for_llm()`，并进入 snapshot、rise-fall、long-history 报告的证据包审计段落。详见 [`PHASE3_EVIDENCE_ARCHITECTURE.md`](../../../PHASE3_EVIDENCE_ARCHITECTURE.md)。

Phase 4 工程路径已接入深度研究协调器，覆盖模式化 QuestionSlot、slot-aware 排序、缺口追问、停止原因及用量字段。历史存档回放仅 6 条 RawDoc，三个模式的新旧 top-3 指标命中率均相同；不足以判断提升。全量回归 532 passed，Ruff 改动范围通过，未调用 Provider/Judge。详见 [`PHASE4_ADAPTIVE_RETRIEVAL_REPORT.md`](../../../PHASE4_ADAPTIVE_RETRIEVAL_REPORT.md)。

Phase 5 将 EvidencePack/AtomicClaim 核验接入报告路径，核验地区、时期、指标、单位、原文 chunk、URL 和来源可信度；无证据时明确标记缺口并移除空证据预设结论。全量回归 546 passed，改动范围 Ruff 通过。该确定性词项核验不等价语义蕴含，也未证明质量提升。详见 [`PHASE5_EVIDENCE_BOUND_SYNTHESIS_REPORT.md`](../../../PHASE5_EVIDENCE_BOUND_SYNTHESIS_REPORT.md)。

Phase 6 工程仍部分完成：实验 manifest 持久化 architecture version；long-history 一次构建 Ledger 后生成保留父 chunk 与原文偏移的句级证据，并为六项任务选择时期/主题 EvidencePack，报告附录记录来源、chunk ID 和证据缺口。模型抽取且可解析的 HistoricalPeriod 现在会与五项分析任务时期求交并驱动证据路由，无可用交集时回退到预设时期；动态路由有结构化边界测试，但尚未通过 provider replay 评估抽取噪声。任务显式年份参与证据排序；三份历史 long-history 存档前七次调用字符数从 185,103 降至 52,215（加权减少 71.8%），词项保留 30/31，`2020` 已恢复、`2000` 在时期范围外。分析器支持逐任务原子 checkpoint，long-history 模式接受 `analysis_checkpoint_path` 请求选项；配置漂移拒绝复用，中断重试跳过已完成任务，并沿用首次分析日期。固定输入实验对 RUNNING run 的恢复仍关闭，避免覆盖响应或绕过未结算租约。字符回放不等价 tokenizer token、成本、延迟或事实质量证明；历史运行曾记录 52,561 tokens、136.231 秒并超过 120 秒预算，存档无逐提示 token 账本。全量回归 569 passed。详见 [`PHASE6_EFFICIENCY_OPTIMIZATION_REPORT.md`](../../../PHASE6_EFFICIENCY_OPTIMIZATION_REPORT.md)。

Phase 7 冻结 matched-budget 48 个有效 run / 240 条 claim 做了 v5 离线重评分，逐条状态/错误类型/指标与 v4 一致（0 差异），无 Provider/Judge 调用。负面结果仍是 C 组事实指标低于 A/B，资源开销更高，另有 6 个 long-history 墙钟超时。没有完成足量独立重复、模块消融或语义 Judge 复评，因此 Research Acceptance 未通过。详见 [`PHASE7_EXPERIMENTAL_EVALUATION.md`](../../../PHASE7_EXPERIMENTAL_EVALUATION.md)。

本文件不是最终性能结论。最终工程验收和研究验收必须分别依据 Phase 1–8 的测试、离线回放、成本记录和独立评分证据判断。

