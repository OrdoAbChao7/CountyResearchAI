# Phase 5 — Evidence-bound analysis and verification

状态：`ENGINEERING_COMPLETE / DETERMINISTIC_SCOPE_LIMITATIONS_RECORDED`

## 实现范围

- 新增 `EvidenceBoundVerifier`。数值陈述必须匹配地区、指标/指标别名、值、单位、时期（Claim 有年份时要求句内最近年份一致）、统计口径/系列版本（Claim 声明时）、已选原文片段、来源 URL 和可信度（来源评分至少 0.65）。证据引用包含 canonical URL、chunk ID 和原文摘录；重复核验不会重复添加引用。
- 不含数值的分析句如精确映射到有来源的 AtomicClaim，会附支持来源；其余陈述标记为未映射/待核实，资料缺口与建议分别标注。报告渲染在 snapshot、rise-fall、long-history 均启用。
- DeepResearchCoordinator 将生成的 EvidencePacks 传入综合器；统一 Source Contract 保存实际 RawDoc credibility score，便于后续核验。
- 移除空证据场景中的预设产业事实、政策举措、风险列表和无证据发展建议。执行摘要只摘录有证据标记的句子；无此类句子则明确呈现证据不足。

## 验证

- RED→GREEN 回归覆盖同数不同指标、不同地区、不同年份、低可信来源、无 canonical URL、非数字县域断言、未映射分析句、片段原文/URL、重复引用和三种模式渲染。
- `pytest --no-cov -q` → 546 passed，1 个 Windows `.pytest_cache` 写入权限警告。
- 本阶段改动范围 Ruff → clean。
- 无 Provider/Judge 调用，未生成 Mock 真实实验数据。

## 限制与解释

- 这是确定性、保守的表层校验，不是语义蕴含证明。数字和指标的词项匹配仍可能漏掉复杂改写；不匹配时会显式标为未核实，不应视为已支持。
- 非数字句只有在 Claim statement 精确出现于句子和对应原文片段时才算支持，其余标为未映射；这会产生保守的假阴性。
- 0.65 是当前工程阈值，不等同于经校准的概率，也没有用正式保留集调参。来源评分缺失时不视为可验证支持。
- 不宣称报告事实精度、独立研究质量或长周期结论的实际提升；这些仍需 Phase 7 的有效独立评测。
