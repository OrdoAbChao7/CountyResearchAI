# Goal Completion Audit — 2026-10-18

当前 Goal：`COMPLETE`  
研究结论：`NO_OVERALL_ADVANTAGE`，E2 报告 QA 对 C 存在有限优势，但成本更高。

## 验收矩阵

| 要求 | 证据 | 状态 |
| --- | --- | --- |
| Goal、范围、预算、里程碑和验收规则 | `GOAL.md` | PASS |
| 仓库与历史 Benchmark 审计 | `PROJECT_AUDIT.md` | PASS |
| Resource Manager、Usage、Checkpoint、失败分类 | `src/county_research_ai/evaluation/`、测试套件 | PASS |
| A/B/C 进程隔离和严格真实 C 入口 | `scripts/run_independent_formal*.py`、`scripts/run_independent_fixed_input*.py`、`strict_container.py` | PASS |
| 冻结 Ground Truth | `ground_truth/formal_ground_truth_20261018.jsonl` 及 manifest，6 地区、双来源/双上下文 | PASS |
| 冻结 E2 输入 | `datasets/fixed_input_formal_manifest_20261018.json`，6/6 hash 匹配 | PASS |
| E1 真实联网 A/B/C | `runs/formal_target_deepseek_20261018_corrected_r2`，18/18 VALID | PASS |
| E2 相同输入 A/B/C | 六个 `e2_formal_target_deepseek_20261018_corrected_*`，18/18 VALID | PASS |
| Claim Verification | E1 18/18、E2 18/18 有效观测；旧失败记录保留 | PASS |
| 至少两个 Blind Judge | E1/E2 各 17/18 有效；失败候选未补齐 | PASS WITH LIMITATION |
| Report-Based QA | E1/E2 各 18/18 可解析 | PASS |
| 核心指标、配对差异和图表 | `metrics/summary_*.csv`、`metrics/paired_*.csv`、`figures/` | PASS |
| 资源与产物审计 | `reports/audits_corrected_20261018/`，E1 和六个 E2 审计均 `passed=true` | PASS |
| 最终研究报告 | `experiments/independent_comparison/reports/FINAL_REPORT.md` | PASS |

## 有效性边界

- 正式比较为每组每地区 1 次重复，不支持稳定性或显著性结论。
- 旧的 512-token 批次和 `corrected_r1` 保留为诊断证据，不进入最终指标。
- E1 冻结 Claim 与研究题目的覆盖关系不足，三组事实指标同时为 0；这被报告列为任务设计局限。
- 没有可靠模块消融，因此不能将差异归因到 QuestionTree、ResearchCritic、FactVerifier 或 Specialized Role Analysis 的单独贡献。
- F 阶段使用确定性的资源/产物审计器，未另建一个 LLM 审计 Agent；这属于审计层实现边界，已在最终报告披露。

## 可复核命令

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests scripts
.venv\Scripts\python.exe -m scripts.audit_independent_runs --runs-root experiments/independent_comparison/runs/formal_target_deepseek_20261018_corrected_r2
.venv\Scripts\python.exe -m scripts.generate_independent_stats --source <observations.jsonl> --summary-csv <summary.csv> --paired-csv <paired.csv> --summary-json <summary.json> --figures-dir <figures>
```

最终验收不是“项目获胜”验收，而是完成真实、可审计、可复现的比较并如实报告：本次证据不支持 CountyResearchAI 整体优于 A/B，仅支持 E2 报告问答能力的有限优势，且需要额外 token 成本。
