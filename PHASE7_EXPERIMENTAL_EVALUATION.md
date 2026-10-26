# Phase 7 — 离线回放与独立评价

状态：`OFFLINE_REPLAY_PARTIAL / RESEARCH_ACCEPTANCE_NOT_MET`

## 本轮冻结数据重放

使用 `python -m scripts.score_independent_claims_offline`，对 matched-budget frozen benchmark 的 48 个有效 run / 240 条声明观测进行独立离线复算；输出到新目录：

`experiments/independent_comparison/claim_scores/continuation_matched_budget_deepseek_flash_20261019_v5_replay_20261019/`

- Provider calls：0；semantic Judge calls：0。
- Source material：36 条来自已存 Source Contract，12 条从原始 RawDocs 离线重建。
- 与 v4 逐条按 `(run_id, claim_id)` 对齐后，Claim status、error types 和 metrics 的差异数为 0/240。两版文件哈希不同，因为 rescore version/batch metadata 更新，不代表评分变化。
- 历史 v4 相对 v3 有 28 条分类变化；v5 重放验证 v4 当前分类可复现，未改写旧版本。

## 现有 Matched-Budget 结果（真实负面结果）

源数据和冻结 Hash 见 [`SECOND_ROUND_REPORT.md`](experiments/independent_comparison/reports/SECOND_ROUND_REPORT.md)、审计见 [`CONTINUATION_MATCHED_BUDGET_AUDIT_20261019.json`](experiments/independent_comparison/reports/CONTINUATION_MATCHED_BUDGET_AUDIT_20261019.json)。在当前有效 run 样本上，v4 离线汇总为：

| 组别 | 有效 run | GT Recall | Evidence Support | Fact Accuracy | Error Rate | LLM units/run | Search/run | 秒/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A 传统检索模拟 | 18 | 0.160 | 0.177 | 0.227 | 0.773 | 6,608 | 3 | 41.43 |
| B 通用联网 AI | 18 | 0.122 | 0.167 | 0.167 | 0.833 | 6,895 | 3 | 42.12 |
| C CountyResearchAI | 12 | 0.033 | 0.042 | 0.042 | 0.958 | 22,652 | 6 | 77.68 |

C 的 6 个 Matched-Budget long-history run 超过 120 秒墙钟预算并被排除在有效质量均值外；失败及资源记录保留在原始 manifests。各组每地区/模式的正式重复仍少，以上均值不能解释为统计显著差异或普遍能力结论。B 在已观测数据上 GT recall 高于 C，A 也高于 C；C 成本更高。当前数据不支持 Evidence-First v2 质量胜过基线。

Natural Stage A/B 的复核结果及“C 对应冻结事实零命中”记载于 [`SECOND_ROUND_REPORT.md`](experiments/independent_comparison/reports/SECOND_ROUND_REPORT.md)。本报告保留该负面结果，不把确定性复评分当作模型质量改善。

## 冻结 RawDocs 的证据链保留回放

对 Matched-Budget v5 replay 中可定位到原始 `raw_docs.json` 的 C 组 `snapshot` 与 `rise-fall` 运行做了离线精确摘录检查。90 条冻结 claim 中仅有 60 条与这 12 个可用运行的地区/模式匹配；long-history C 运行缺少可用原始输入，因此不纳入该分母。以冻结 `evidence_excerpt` 的空白归一化后精确包含为判定标准：

| 阶段 | 保留 | 比例 |
| --- | ---: | ---: |
| RawDoc 原文 | 17/60 | 28.3% |
| 18,000 字符 ProcessedData 渲染 | 17/60 | 28.3% |
| 时期 Evidence Ledger | 17/60 | 28.3% |
| EvidencePack（6,000 字符） | 13/60 | 21.7% |
| EvidencePack（18,000 字符） | 13/60 | 21.7% |

这是对冻结摘录的精确保留率，不是语义检索召回率、事实正确率或统计推断。Ledger 命中而 EvidencePack 未选中的四条，均被标记为 `period_only_fallback`：时期相关性命中，但冻结指标名没有被当前词项匹配命中；增大字符预算没有改变结果。另有 43 条在现有 RawDocs 中找不到精确摘录，不能据此判断其是否被语义等价证据支持。该回放说明下游字符预算不是这四条丢失的原因，指标别名/同义匹配与证据覆盖仍需改进。

切分器另外修复了英文小数点被误判为句界的问题（例如 `300.6`）。回归测试检查小数处的句片段完整性及其原文 offset；该修复保障派生片段不破坏数值，但不应被解读为上述总体精确命中率提升。

## 模块离线评价边界

- Phase 4 adaptive ranking 的离线回放只有 6 个 RawDocs，三个模式 top-3 required-metric recall 均与旧排序相同；样本过小且无提升证据，见 [`PHASE4_ADAPTIVE_RETRIEVAL_REPORT.md`](PHASE4_ADAPTIVE_RETRIEVAL_REPORT.md)。
- Phase 6 long-history 只测了三份存档的前七次输入 prompt 字符数；合计 185,103→52,215 字符（加权 -71.8%）。显式年份锚点修复后，有限词项检查保留 30/31 个旧上下文可见词项；于都 contemporary task 的 `2020` 已恢复，`2000` 超出当前时期边界。此结果不是 token 成本，也未验证 gold-evidence recall；long-history 事实质量 replay 未完成。详见 [`PHASE6_EFFICIENCY_OPTIMIZATION_REPORT.md`](PHASE6_EFFICIENCY_OPTIMIZATION_REPORT.md)。
- 没有完成有效模块消融、足量独立地区/任务重复或独立 semantic Judge 复评。未进行任何新 Provider/Judge 请求。

## Gate 判断与下一步

- 离线评分复算门：通过（0/240 评分字段差异）。
- 架构效果门：未通过/证据不足；当前有效 Matched-Budget 样本 C 的事实指标落后且资源更高。
- long-history 效率门：字符层面有下降迹象，但 token、事实覆盖、耗时收益未知；6 个旧 C 运行超时。
- Research Acceptance：未满足。Phase 6/8 工程复核发现的问题已修复并重新通过全量测试；实际 token/成本比较、足量独立质量样本与 semantic Judge 仍未完成。
- 无新的 Provider 调用授权，不做付费 smoke test。继续先做冻结离线 replay、缺陷定位和无付费验证；正式质量结论需后续取得足够的独立数据与明确授权。
