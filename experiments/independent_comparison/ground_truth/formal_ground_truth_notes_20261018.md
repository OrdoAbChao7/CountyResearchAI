# Formal Ground Truth Notes — 2026-10-18

本文件说明本批次正式 Ground Truth 的边界，不替代 JSONL claim 文件。

## 冻结范围

本批次冻结六个非开发地区、每个地区一个与 E2 固定输入包直接对应的最小 claim target。所有 claim 均经过 `GroundTruthStore.freeze(require_cross_verification=True)` 验证，要求两个不同 URL 和两个独立核查上下文（D3、D4）。

德清县和攀枝花市的 GDP claim 明确限定为初始发布版本。后续修订值仍保留在 `verification_matrix_20261018.yaml` 和候选输入包中，不得在评分时静默合并。长汀县只冻结官方统计公报中的 GDP 总量；360.8/4.6 的年初预计值和 357.8/4.9 的后发布公报值属于不同时间点，暂不把增速合并为正式 claim。

## 未纳入本批次评分的证据

`partial_verified_panel_20261018.jsonl`、`industry_supplemental_panel_20261018.jsonl` 和 `candidate_claims_20261018.jsonl` 保持原状态，继续作为审计和后续扩展素材，不被改名为正式 Ground Truth。D5/D6 发现的产业术语、工业增速和版本冲突继续保留；它们不因本次最小 claim target 冻结而消失。

## 实验限制

六条 claim 适合做第一轮真实 E1/E2 的声明级质量门槛，不足以单独覆盖所有产业、历史和因果分析要求。分析深度仍必须由冻结 Rubric 的两个盲评 Agent 评分，且正式统计必须保留失败样本和当前小样本不确定性。
