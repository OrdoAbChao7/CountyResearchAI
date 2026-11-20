# Ground Truth

Ground Truth 文件独立于 A/B/C 运行目录保存。`VERIFIED` claim 必须包含至少两个核查来源和两个独立核查上下文；冻结后不得因某组报告而改写。

当前有 `pilot_20261018_yudu.jsonl`、六地区候选 Claim、一个三 Claim 的 `PARTIAL_FROZEN_NOT_FORMAL` panel，以及六条 Claim 的最小正式 Ground Truth。先导批次和部分 panel 仍不进入正式指标；最小正式目标记录在 `formal_ground_truth_20261018.jsonl`，其 manifest 已通过 `GroundTruthStore.freeze(require_cross_verification=True)`。它只冻结每个地区一个版本明确的 claim，不能被误读为覆盖全部产业、历史和因果事实。

`candidate_claims_20261018.jsonl` 是六个候选地区的一条/地区初始 Claim 清单，仅用于核验工作台输入。它的每条记录都保持 `UNVERIFIED`，不满足正式冻结门槛，也不进入质量指标；其中德清、攀枝花的候选来源仍是转载页面，临泽的官方 PDF 还需要页码摘录，长汀、于都、白山需要第二独立核验上下文。

第一轮独立核查记录保存在 `verifications/D1_20261018.md` 和 `verifications/D2_20261018.md`。D1、D2 各自只负责三地，报告之间没有互相引用；它们只能提升候选证据质量，不能替代对同一 Claim 的双角色交叉核验。

第二轮重叠核查记录保存在 `verifications/D3_20261018.md` 和 `verifications/D4_20261018.md`，结果汇总于 `verification_matrix_20261018.yaml`。基于两轮角色对同一 Claim 的独立结果，`partial_verified_panel_20261018.jsonl` 仅冻结于都、白山和临泽 GDP 总量三条 Claim；它不是六地区正式 Ground Truth，德清/攀枝花版本冲突、长汀增速缺口仍被保留。

`datasets/fixed_input_candidate_20261018_*.json` 是六份公开来源有界摘录的历史候选 source snapshot，候选 manifest 仍保持 `CANDIDATE_INPUT_PACKS_NOT_FORMAL`。在最小正式 Ground Truth 冻结后，`datasets/fixed_input_formal_manifest_20261018.json` 以相同 `source_hash` 引用这六份内容作为正式最小 E2 输入；它们仍未被 API 批次消费，不能据此宣称 E2 已完成。

`source_audit_supplement_20261018.md` 记录主 Agent 的公开来源补充检索。它不增加 D1–D4 的独立核查上下文；德清、攀枝花的版本差异和长汀年鉴页码缺口仍需保留。

`verifications/D5_20261018.md` 和 `verifications/D6_20261018.md` 是新增的独立产业事实核查记录。它们共同支持一个四 Claim 的 `industry_supplemental_panel_20261018.jsonl`，覆盖德清产业分类、于都规上工业增速、攀枝花规上工业增速和钒钛/先进材料背景；该 panel 已通过双来源/双上下文校验，但明确标记为 `SUPPLEMENTAL_FROZEN_NOT_FORMAL`，不替代六地区任务级 Ground Truth。

`formal_ground_truth_notes_20261018.md` 说明正式最小目标的版本范围和保留的争议。德清、攀枝花后续修订以及长汀预计值/公报值的时间点差异继续保存在 `verification_matrix_20261018.yaml`，不得在评分前静默改写。
