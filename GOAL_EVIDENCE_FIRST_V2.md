# CountyResearchAI Evidence-First v2 Goal

状态：`IN_PROGRESS / PHASE_1_EVIDENCE_PRESERVATION`

本文件是现有 `GOAL.md`（上一轮真实效能验证 Goal）的独立续作管理文件，不覆盖旧 Goal 历史。完整目标原文保留在用户提供的粘贴文件：

`D:\Dev\.codex\attachments\67fda3ad-b9ca-44e3-938c-aaa4b66716ea\pasted-text-1.txt`

## Objective

将 CountyResearchAI 从多阶段文档处理和 LLM 报告生成系统升级为结构化、可追溯、可验证、预算感知的县域产业研究引擎。优先级固定为：证据保真 > 证据选择 > 事实准确性 > 自适应检索 > 分析深度 > 性能优化 > 新 Agent 功能。

## Fixed baseline and development boundary

- Legacy comparison baseline: `52a6ed0f5164721cece221ffb9e7f67f73ac3dd7` on `codex/experiment-superiority`.
- Candidate hotfix audited from `origin/fix/evidence-preservation-20261019` at `b32470a40c1a042a8d386d15c248fb5e765bc60c`.
- Development branch: `codex/evidence-first-v2`.
- No existing experiment artifacts may be overwritten or deleted.
- No new paid Provider call is allowed without a fresh explicit cost gate.

## Phase ledger

| Phase | Objective | Status | Evidence |
| --- | --- | --- | --- |
| 0 | Baseline freeze, corpus inventory, reproducible loss audit | COMPLETE | `ARCHITECTURE_BASELINE_AUDIT.md`, `tests/test_evidence_preservation_regression.py` |
| 1 | Evidence preservation and unified Source Contract | IN_PROGRESS | `src/county_research_ai/evidence/source_contract.py`, `ARCHITECTURE_BASELINE_AUDIT.md` |
| 2 | Claim classification and independent metrics | NOT_STARTED | `PHASE2_EVALUATION_AUDIT.md` |
| 3 | Structured Evidence Ledger and contracts | NOT_STARTED | `PHASE3_EVIDENCE_ARCHITECTURE.md` |
| 4 | QuestionSlot-driven adaptive retrieval | NOT_STARTED | `PHASE4_ADAPTIVE_RETRIEVAL_REPORT.md` |
| 5 | Evidence-bound analysis and verification | NOT_STARTED | `PHASE5_EVIDENCE_BOUND_SYNTHESIS_REPORT.md` |
| 6 | Efficiency, architecture versions, long-history routing | NOT_STARTED | `PHASE6_EFFICIENCY_OPTIMIZATION_REPORT.md` |
| 7 | Offline replay and authorized independent comparison | NOT_STARTED | `PHASE7_EXPERIMENTAL_EVALUATION.md` |
| 8 | Final engineering/research acceptance | NOT_STARTED | `REFACTOR_FINAL_REPORT.md` |

## Phase 0 known facts

- Current candidate full test baseline: `pytest --no-cov -q` → `494 passed`, one Windows `.pytest_cache` permission warning.
- Full `ruff check src tests scripts` → 77 findings; most are historical verification scripts. Candidate-specific findings are recorded in `ARCHITECTURE_BASELINE_AUDIT.md`.
- Saved Deqing snapshot raw and processed artifacts contain `722.5亿元`, `300.6亿元`, `5.8%`, and `7.7%`; old formal C archives can contain only report metadata, so source-based scoring loses the actual evidence.
- Candidate hotfix has three focused regression tests and changes processor cleaning, long-text evidence segmentation, bounded context distribution, and C source persistence. The initial Source Contract serializer now covers new experiment writers, but the full Source Contract, truncation audit trail, and structured claim/version semantics required by this Goal remain unfinished.

## Milestone gate rule

每个 Phase 必须完成：`Implementation → Tests → Evidence → Acceptance`。未通过的阶段不得标记 Completed；历史实验结果、负面结果和资源失败必须保留。

## Working plan

详细任务、文件边界、接口和测试要求见 [`docs/superpowers/plans/2026-10-19-evidence-first-v2.md`](docs/superpowers/plans/2026-10-19-evidence-first-v2.md)。

