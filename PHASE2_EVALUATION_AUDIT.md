# Phase 2 Evaluation Audit

审计日期：2026-10-19  
分支：`codex/evidence-first-v2`

## 结论

Phase 2 已完成第一版离线评价链路：Claim 比较不再把不同期间、地区、指标、单位、统计口径、行政范围或版本强行判成事实矛盾；这些情况进入 `NON_COMPARABLE`，并从 fact precision 和 factual error rate 的可验证分母中排除。只有同一比较身份下的数值不一致仍判为 `CONTRADICTED`。

冻结的 continuation matched-budget 产物已完成纯离线重评分：48 个 VALID run、240 条 Claim observation、0 次 Provider call、0 次 semantic Judge call。旧 v3 输出保持不变，新结果写入版本化目录：

`experiments/independent_comparison/claim_scores/continuation_matched_budget_deepseek_flash_20261019_v4_offline/`

这不是新的 Provider 实验，也不能替代独立语义 Judge；它是对已有报告、已有 source archive 和已保存 RawDoc 的规则型可复算审计。

## Claim identity and classification

冻结 Claim 的比较身份由 `claim_comparison_key()` 固定为：

```text
(region, metric, period, administrative_scope, unit, version)
```

其中 period 优先使用 `metric_year`，否则回退到 `date`；`caliber` 作为额外口径维度保留在 Claim contract 中。分类规则为：

| 场景 | 状态 | 是否进入 factual error denominator |
| --- | --- | ---: |
| 同一 identity，报告数值不一致 | `CONTRADICTED` | 是 |
| 年份、地区、指标、单位、口径、范围或版本不同 | `NON_COMPARABLE` | 否 |
| 报告和来源都没有足够主题信息 | `UNVERIFIED` | 否 |
| 提到主题但缺少正文证据 | `UNSUPPORTED` | 否 |
| 来源明确存在争议 | `DISPUTED` | 否 |
| 报告和 source contract 的结构化事实一致 | `SUPPORTED` | 是 |

新增的负例测试覆盖不同年份、地区、指标、单位、口径、版本、行政范围、同 identity 错值、URL-only support、缺失提及、争议来源和百分比错值，共 12 组；另有指标分母和历史 fixture 回归测试。

## Offline rescore evidence

| 项目 | 结果 |
| --- | ---: |
| Candidate runs | 48 |
| Claim observations | 240 |
| Provider calls | 0 |
| Semantic Judge calls | 0 |
| Classification changes vs v3 | 28 |
| `CONTRADICTED → NON_COMPARABLE` | 8 |
| `SUPPORTED → NON_COMPARABLE` | 9 |
| `UNSUPPORTED → NON_COMPARABLE` | 4 |
| `UNSUPPORTED → SUPPORTED` | 2 |
| `CONTRADICTED → DISPUTED` | 5 |

Source material 使用情况：36 个 run 读取已有 Source Contract；12 个 run 发现旧 metadata-only `sources.json`，从各自已保存的 `data/raw/**/raw_docs.json` 重建 Source Contract。旧 v3 目录没有被覆盖。

重评分输出包括：

- `claim_observations.jsonl`：逐 Claim 的新状态、比较原因、source material 状态、旧状态和变更原因；
- `summary.json`：run 数、总 observations、变更计数和 `provider_calls=0`；
- `rescore_manifest.json`：冻结 ground truth、baseline 输出、重评分版本和零 Provider/Judge 调用声明；
- `statistics_summary.json`、`summary.csv`、`region_summary.csv`、`paired.csv` 和 `figures/`：按有效 offline observation 聚合的独立指标输出。

脚本入口为 `scripts/score_independent_claims_offline.py`，它不导入 Provider client、不调用 API gate，也不会创建资源计费记录。统计入口已接受 `VALID_OFFLINE`，并新增 `non_comparable_rate` 汇总指标。

## 解释边界

- `NON_COMPARABLE` 的意义是“当前 Claim identity 不可直接比较”，不是报告正确，也不是报告错误；它应进入不可验证/覆盖缺口分析，而不是 factual error。
- 纯规则重评分只能覆盖有结构化字段的 Claim。没有结构化信号的 Claim 会标为 `UNVERIFIED` 并记录 `offline_semantic_pending`，不会为了填满分母调用 semantic Judge。
- 本次离线输出显示的是评价契约和 source archive 修复后的分类变化，不是 Evidence-First v2 已经提高了模型真实写作质量的因果结论。
- 真实独立实验和新的 Provider smoke test 仍受原有 cost gate 约束；本阶段没有申请或执行新的付费调用。

## 验证命令

```text
.venv\Scripts\python -m pytest tests/test_claim_verification.py tests/test_experiment_metrics.py tests/test_evaluation_metrics.py tests/test_offline_claim_rescore.py -q
31 passed, 1 Windows .pytest_cache permission warning

.venv\Scripts\python -m ruff check <changed Phase 2 source, script, and test files>
All checks passed!

python -m scripts.score_independent_claims_offline ...
OK_OFFLINE; runs=48; valid_observations=240; provider_calls=0
```

