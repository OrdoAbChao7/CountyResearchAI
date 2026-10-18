# Goal：CountyResearchAI 真实效能验证与多智能体自动化对照实验

## Objective

通过真实联网、可复现、可审计的对照实验，判断 CountyResearchAI 相比传统网页检索研究和通用联网 AI 研究，是否在事实准确性、关键事实覆盖、证据支持、分析深度和资源效率上具有实质性提升。结论不得预设为项目获胜；数据不足时标记 `INCONCLUSIVE`。

本 Goal 只比较自动化研究流程，不证明真实人类的理解能力或学习效果。

## Research Questions

1. 在相同地区、题目、模型和受控搜索预算下，A/B/C 三种研究方式的事实准确率、覆盖率和证据支持率有何差异？
2. CountyResearchAI 的 QuestionTree、ResearchCritic、FactVerifier 和 Specialized Role Analysis 是否带来可测量的增益，还是只增加了调用次数？
3. 各方法的端到端时间、LLM token、搜索请求和失败率如何权衡？
4. 增益是否稳定跨越资料丰富/稀缺、产业现状/兴衰/长历史等地区和任务类型？
5. 研究报告是否足以支持独立 AI 仅依据报告回答冻结的客观问题？

## Success Criteria

### Engineering Success

- Resource Manager 对 LLM、Search、Fetch、Judge 调用提供并发安全的预留、结算、熔断和持久化记录。
- A/B/C 运行上下文隔离，任何 Mock 或回退路径都会使运行标记为 `INVALID_MOCK`，不得进入正式质量比较。
- 运行 Manifest、原始响应、来源、执行轨迹、token/请求计量和 Checkpoint 可恢复。
- Ground Truth、盲评、指标计算、独立审计和报告生成可执行。
- 新增测试与既有测试通过；不泄漏 API Key。

### Research Success

- 至少完成一轮真实联网 A/B/C 对照，且至少包含 2 个未参与原有开发调试的地区；或在资源/账户限制下留下完整的 `NOT RUN` 证据和可复现解锁条件。
- Ground Truth 经两个独立核查上下文交叉验证并冻结。
- 至少两个匿名 Blind Judge 完成冻结 Rubric 评分，分歧大时启动裁判。
- 计算事实准确率、关键事实覆盖率、证据支持率、错误类型、分析深度、时间和资源效率。
- 形成 `FINAL_REPORT.md`，明确结论、失败样本、成本、局限和是否支持性能提升。

## Scope

包含：正式实验协议、A/B/C 研究运行、D Ground Truth、E Blind Judges、F Auditor、资源控制、真实数据产物、统计分析、图表和最终报告。

不包含：招募真实用户或大学生问卷；以 Mock 数据替代真实实验；未经授权的付费 API；为了提高成绩而修改被测系统；把规则式角色分析器描述为独立 LLM Agent。

开发集的安吉县、信丰县、鹤岗市只用于回归和 Smoke Test，不进入正式测试集，除非明确建立新的冻结批次并记录原因。

## Technical Architecture

- `experiments/independent_comparison/` 保存协议、地区/任务数据、冻结 Ground Truth、Manifest、运行原始产物、盲评、指标、图表、报告和检查点。
- `ResourceManager` 使用本地持久化状态实现租约式资源预留；按 Provider/Model/资源类型区分免费额度、已知付费、未知计费状态，并采用保守停止。
- Provider Adapter 只返回结构化响应和实际 Usage；真实失败不回退到 Mock。DeepSeek Search/Fetch 默认禁用，只有在免费证据或用户授权付费证据通过 gate 后启用。
- A/B 通过独立进程和独立工作目录运行通用研究脚本；C 调用 CountyResearchAI 真实流程但必须使用显式的 `strict_real` 容器，禁止静默 Mock。
- D/E/F 使用独立输入和匿名化报告；评分只能读取批准的输入快照，不读取其他组运行过程或 Ground Truth 泄漏内容。
- 所有运行先写入 `RUNNING` Manifest，成功结算后转为 `VALID`；异常、超额、Mock、资源未结算或污染转为明确的无效状态。

## Milestones

| Milestone | 验收条件 | 状态 |
| --- | --- | --- |
| P0 Goal 初始化 | Goal、目录、分支/权限状态和资源约束有记录 | COMPLETE |
| P1 仓库审计 | `PROJECT_AUDIT.md` 记录真实能力、缺陷和可执行性 | COMPLETE |
| P2 协议冻结 | 设计、任务、Rubric、隔离和预算策略落盘 | COMPLETE（六地区最小正式 claim target、输入 hash、Rubric 和 E1 primary task 映射均已冻结；snapshot/rise-fall/long-history 均有正式地区覆盖） |
| P3 工程实现 | Resource Manager、Manifest、Runner、Judge、Metrics、Report 有测试 | COMPLETE（含空报告拒绝、DeepSeek thinking 参数、批次过滤、失败 Judge 不并入统计的回归测试） |
| P4 资源验证 | 选定 Provider 的模型、调用方式和计费边界有证据 | COMPLETE（历史 DeepSeek API、Search、真实 Usage 和旧授权标签均已记录；续作已确认缺少账户级账单证据并关闭 Gate） |
| P5 Smoke Test | 至少一轮真实 A/B/C，运行无 Mock 污染且来源可核验 | COMPLETE（正式修正批次先经低预算诊断，空报告问题已被发现并修复） |
| P6 正式实验 | 在确认配额内执行冻结批次并保留所有成功/失败样本 | COMPLETE（E1/E2 各 18 个修正后 VALID 运行；旧失败批次保留并排除） |
| P7 审计与报告 | 独立审计、统计、图表和 `FINAL_REPORT.md` 完成 | COMPLETE（E1/E2 Claim、Judge、QA、合并观测、统计、图表和批次审计均已落盘） |
| P8 最终验收 | Engineering/Research Success 逐项有证据，Goal 才可完成 | REOPENED（第一轮工程完成，但 Benchmark 有效性审计发现分母、Ground Truth 与授权边界问题） |

## Task Breakdown

1. 完成仓库与历史 Benchmark 审计，隔离旧离线回归语义。
2. 写入实验设计、样本冻结规则、Rubric、资源预算和数据字典。
3. 用 TDD 实现 Resource Manager、Provider Usage、RunManifest、Artifact、Checkpoint。
4. 实现严格真实 Provider 与失败分类，禁止静默 Mock。
5. 实现隔离的 A/B/C 运行器、Ground Truth Builder、Blind Judge 和 Auditor 输入契约。
6. 完成最低成本 Smoke Test；失败则保存完整检查点，不伪造结果。
7. 冻结正式批次，执行可承受规模的真实实验和消融实验（仅在模块可可靠关闭时）。
8. 计算指标、生成图表和最终报告，独立复核结论。

## Resource Budget

- 历史正式批次使用 DeepSeek `deepseek-flash` 与 DeepSeek Search，旧账本记录为 `USER_AUTHORIZED_PAID`；续作已按当前指令撤回该解释，在新的计费证据前禁止任何新业务调用。
- E1 研究账本：91,815 LLM tokens、72 次搜索；E2 研究账本：55,065 LLM tokens、0 次搜索。
- E1/E2 Claim、Judge、QA 后处理继续通过独立 Resource Manager 账本记录；总 DeepSeek LLM tokens 为 586,373，搜索请求为 72。
- Gemini/Tavily 仍保留为可用 Provider 的配置和历史资源证据，但不进入本次正式结论；没有自动充值、静默升级或把付费调用标记为免费。

## Execution Status

- Git：当前工作在 `codex/experiment-superiority`；续作新增审计与计划文件，不提交 `.env` 或 API Key。
- 测试：本轮新增回归测试覆盖 DeepSeek thinking 参数、空报告拒绝、批次前缀过滤、失败 Judge 不并入统计、布尔字符串兼容；全量测试与静态检查在收尾阶段复核，pytest cache 的 Windows 权限警告仍为环境问题。
- Provider：历史 DeepSeek Models、Search 和 Chat Probe 曾成功；但仓库没有账户账单或免费资格证据，历史 `USER_AUTHORIZED_PAID` 仅作审计证据，当前续作 Gate 为 `CLOSED_BILLING_UNCONFIRMED`。
- 正式 E1：`formal_target_deepseek_20261018_corrected_r2`，6 地区 × A/B/C = 18/18 `VALID`，报告全部非空，资源与产物审计通过。
- 正式 E2：六个 `e2_formal_target_deepseek_20261018_corrected_*` 批次，18/18 `VALID`，冻结输入 hash 全部匹配，资源与产物审计通过。
- 后处理：E1/E2 Claim Verification 各 18/18 有效；Blind Judge 各 17/18 有效；Report-Based QA 各 18/18 可解析；统计、配对差异、区域统计和真实 SVG 图表已生成。
- 第一轮研究结论降级为 `INCONCLUSIVE_WITH_EFFICIENCY_REGRESSION`：E2 报告 QA 曾观察到 C=0.667、A/B=0.500，但 Ground Truth 与任务覆盖不足、E1/E2 分母存在测量效度问题，且 C 的成本更高；完整历史结果保留在 `FINAL_REPORT.md`。
- 旧的 512-token 空报告批次、`corrected_r1` 诊断批次和开发/先导失败样本均保留，未进入最终质量统计。
- 历史离线 Benchmark：仅作为问题复现证据，不作为本 Goal 结论。

## Evidence

- `PROJECT_AUDIT.md`：代码审计与风险。
- `docs/superpowers/specs/2026-10-18-independent-comparison-design.md`：实验系统设计。
- `docs/superpowers/plans/2026-10-18-independent-comparison.md`：TDD 实施计划。
- `experiments/independent_comparison/protocol/`：冻结协议与 Rubric。
- `experiments/independent_comparison/manifests/`、`runs/`、`judgements/`、`metrics/`、`reports/`：已填充正式运行、评分、统计、图表和审计证据。
- `experiments/independent_comparison/reports/SMOKE_TEST_REPORT.md`：真实 Smoke 的批次、资源账本、失败样本和有效性判定。
- `experiments/independent_comparison/reports/FINAL_REPORT.md`：基于修正后 E1/E2 有效观测、盲评、QA、统计和审计的最终研究报告。
- `experiments/independent_comparison/reports/AUDIT_REPORT.json`：12 个运行目录的产物哈希、资源租约和历史归档审计结果；于都县先导的超预算被明确审计为错误。
- `experiments/independent_comparison/runs/pilot_20261018T183000Z/CORRECTION.md`：于都县先导资源超限的原始证据与状态更正记录。
- `experiments/independent_comparison/ground_truth/pilot_20261018_yudu.jsonl`：于都县先导的双来源、双上下文 Ground Truth 候选；不进入六地区正式最小目标。
- `experiments/independent_comparison/ground_truth/candidate_claims_20261018.jsonl`：六个候选地区各一条初始 Claim，全部 `UNVERIFIED`，用于后续独立核验，不进入质量指标。
- `experiments/independent_comparison/ground_truth/candidate_claims_20261018_manifest.json`：候选 Claim 文件哈希、排除原因和未冻结状态。
- `experiments/independent_comparison/ground_truth/verifications/`、`verification_matrix_20261018.yaml`：D1–D4 独立来源核查日志和逐 Claim 共识矩阵。
- `experiments/independent_comparison/ground_truth/partial_verified_panel_20261018.jsonl`、对应 manifest：于都、白山、临泽三条经 D3/D4 重叠核验的部分冻结 Claim；明确排除正式六地区目标。
- `experiments/independent_comparison/datasets/fixed_input_candidate_manifest_20261018.json` 及六份 `fixed_input_candidate_20261018_*.json`：为 E2 预检准备的六个有界公开来源快照，已完成 `FixedInputPack.load` 与 `source_hash` 校验，但仍是 `CANDIDATE_INPUT_PACKS_NOT_FORMAL`，不代表 E2 已执行。
- `experiments/independent_comparison/ground_truth/formal_ground_truth_20261018.jsonl`、manifest、`datasets/formal_regions_20261018.yaml` 和 `datasets/fixed_input_formal_manifest_20261018.json`：六个地区的最小正式 claim target、地区冻结记录和输入 hash；正式评分入口通过 `GroundTruthStore.freeze_verified(..., require_cross_verification=True)` 校验后已被 E1/E2 评分消费。
- `src/county_research_ai/evaluation/fixed_input.py`、`scripts/run_independent_fixed_input.py`、`scripts/run_independent_fixed_input_worker.py`：E2 固定输入包与独立批处理入口。
- `scripts/run_independent_fixed_input.py::formal_batch_root`、`tests/test_fixed_input_runner.py`：验证 E2 批次根目录固定在项目内，不受启动当前工作目录影响。
- `experiments/independent_comparison/manifests/formal_target_gate_20261018.json`：正式目标 Provider、模型和用户授权付费边界证据；修正批次运行记录另见 `runs/formal_target_deepseek_20261018_corrected_r2` 与六个 E2 根目录。
- `experiments/independent_comparison/manifests/formal_launch_manifest_20261018.json`：冻结模型、地区/任务、E1/E2 预算、preflight 范围、输出目录和协议/输入 hash；未被 gate 解锁前不产生业务调用。
- `experiments/independent_comparison/reports/GEMINI_ACCOUNT_CHECK_20261018.md`：只读 AI Studio 页面检查记录；当前会话停留在公开欢迎页，未取得账户级 billing/quota 证据。
- `require_frozen_launch_manifest` 及 `tests/test_experiment_gate.py`：gate 解锁时复核 launch manifest 的模型/Provider 一致性、协议/输入文件 hash 和 E2 pack 文件 hash。
- `experiments/independent_comparison/datasets/source_audit.yaml`：六个候选地区的公开来源、冲突与 primary-source 缺口审计；不等同于冻结 Ground Truth。
- `experiments/independent_comparison/ground_truth/source_audit_supplement_20261018.md`：主 Agent 的公开来源补充检索；确认攀枝花初始值官方上下文和长汀官方年鉴附件入口，但不增加 D3/D4 独立核查上下文，也不扩大最小正式 claim target。
- `experiments/independent_comparison/ground_truth/verifications/D5_20261018.md`、`D6_20261018.md` 及 `industry_verification_matrix_20261018.yaml`：两份独立产业事实核查与共识矩阵；记录术语修正、同源来源限制和临泽/攀枝花版本争议。
- `experiments/independent_comparison/ground_truth/industry_supplemental_panel_20261018.jsonl` 及 manifest：四条通过双来源/双上下文校验的产业 Claim，但明确排除正式六地区质量目标。
- `GOAL_COMPLETION_AUDIT_20261018.md`：按目标原文逐项核对工程、Ground Truth、正式运行、盲评、统计、图表和最终报告的完成状态。
- `tests/test_evaluation_resource_manager.py::test_overrun_usage_blocks_later_reservations`：验证实际结算超预算后，持久化账本会阻止后续继续预留资源。
- `src/county_research_ai/evaluation/gate.py`、`tests/test_experiment_gate.py`：验证正式 E1/E2 API gate 在状态未打开、DeepSeek LLM/Search/Fetch 任一独立 boundary 不属于当前允许的 `FREE_CONFIRMED`、模型身份/可见性未核实、预检超过 24 小时、缺少新鲜 billing evidence、Tavily 余额耗尽或 PAYG 非零时，在创建运行目录前拒绝执行；历史 `USER_AUTHORIZED_PAID` 仅保留为审计记录。
- `scripts/run_independent_formal.py`、`scripts/run_independent_formal_worker.py`、`tests/test_formal_runner.py`：冻结六地区 E1 编排、A/B/C 进程命令和低预算参数校验；当前 gate 关闭时不创建运行目录。
- `src/county_research_ai/evaluation/experiment_runner.py`、`tests/test_experiment_runner.py`：执行异常后若仍有未结算资源租约，运行被标记为 `INVALID_RESOURCE_ACCOUNTING`，不再被普通 `FAILED` 状态掩盖。
- `src/county_research_ai/evaluation/resource_manager.py`、`tests/test_evaluation_resource_manager.py`：重开同一 SQLite 账本时拒绝容量或计费类别漂移，避免恢复/多进程启动绕过冻结资源上限。
- `scripts/run_independent_judges.py`、`tests/test_judge_batch.py`：仅收集 Manifest 显式 `formal_target: true` 的 VALID 报告，执行哈希校验、匿名化、至少两个独立 Judge、分歧裁判和 `kind=judge` 资源账本；历史开发集 VALID 运行不会进入正式后处理。
- `src/county_research_ai/evaluation/report_qa.py`、`scripts/run_independent_report_qa.py`、`tests/test_report_qa.py`、`tests/test_report_qa_runner.py`：冻结 Report-Based QA 问题、匿名报告答题、保守 Ground Truth 数字评分和 `kind=qa` 资源账本入口；E1/E2 QA 观测已生成。
- `src/county_research_ai/evaluation/claim_verification.py`、`scripts/score_independent_claims.py`、`tests/test_claim_verification.py`：在独立评分阶段依据报告/归档来源和冻结 Ground Truth 生成声明级 `ClaimEvaluation` 与 metrics observation；E1/E2 Claim 观测已生成。
- `src/county_research_ai/evaluation/ground_truth.py`、`tests/test_ground_truth_and_judging.py`：正式评分入口通过 `freeze_verified` 拒绝状态、正式标记或 `source_hash` 不匹配的 Ground Truth manifest，避免评分前静默替换冻结文件。
- `src/county_research_ai/evaluation/gate.py`、`scripts/run_independent_formal*.py`、`scripts/run_independent_fixed_input*.py`、`tests/test_experiment_gate.py`：正式 E1/E2 在创建批次或初始化资源前再次校验冻结 Ground Truth manifest，漂移直接拒绝执行。
- `src/county_research_ai/evaluation/checkpoints.py`、`scripts/run_independent_formal.py`、`scripts/run_independent_fixed_input.py`、`tests/test_experiment_models.py`、`tests/test_formal_runner.py`、`tests/test_fixed_input_runner.py`：E1/E2 批次持久化配置绑定 checkpoint；`--resume` 只跳过已有终态 Manifest，拒绝配置漂移、非终态运行和缺失证据。
- `src/county_research_ai/evaluation/providers.py`、`src/county_research_ai/search/web_search.py`、`tests/test_evaluation_providers.py`、`tests/test_search_web.py`：DeepSeek Search/Fetch 适配器和普通 provider 工厂已接入，默认禁用，并覆盖离线响应解析、URL/内容去重、元数据、Fetch、失败统计、限速和 A/B 按冻结 provider 选择路径。
- `scripts/merge_independent_observations.py`、`tests/test_merge_observations.py`：按 `run_id` 合并 Claim、Blind Judge 和 QA observation，保留无效/缺失状态后交给统计脚本。
- `experiments/independent_comparison/protocol/benchmark_claim_schema.yaml`、`continuation_protocol.yaml`、`datasets/independent_regions_20261018.yaml`、`scripts/build_benchmark_ground_truth.py`：续作的 rich Claim、Natural Execution/Matched Budget 和本地冻结入口；输入不足或双重核验缺失时拒绝生成 Benchmark。
- `experiments/independent_comparison/reports/SECOND_ROUND_REPORT.md`：第二轮因当前计费 Gate 关闭而明确记为 `NOT_RUN`，不把离线校准当作真实效能结果。
- `src/county_research_ai/evaluation/metrics.py`、`src/county_research_ai/evaluation/statistics.py`、`scripts/generate_independent_stats.py`：错误率、分析深度、QA、时间、token、搜索请求、单位覆盖效率和地区×组差异的 observation/统计/图表支持；E1/E2 正式 observation、CSV、JSON 和 SVG 已生成。
- Gemini/Tavily/DeepSeek 官方资源核验记录写入 `PROJECT_AUDIT.md` 和本文件，不将 Key 或响应中的敏感字段写入日志。

## Blockers

- 当前续作已创建 `codex/experiment-superiority` 分支并推送；历史数据和续作审计产物均保留。
- 研究规模只完成每组每地区 1 次重复，不能支持稳定性或显著性结论；这是结果局限，不阻塞本 Goal 的最小验收。
- 当前没有可靠账户价格、账单或免费资格字段，报告只呈现真实 tokens/请求数，不将其换算成金额；在重新确认前禁止业务 API。
- 未完成可靠的模块消融，因此不能把 C 的任何差异归因到某一个专用模块。

## Final Acceptance

第一轮真实实验产物、失败样本、资源计量、Ground Truth、盲评、审计、统计和最终报告均已落盘并可核验；但续作审计已将研究状态改为 `INCONCLUSIVE_WITH_EFFICIENCY_REGRESSION`。只有完成有效 Ground Truth、离线评分校准和公平第二轮验证后，才能重新判断整体优势。

## Goal Continuation：实验有效性修复

### 当前状态

- Engineering Completion：第一轮工程实现完成，测试基线保留。
- Benchmark Validity：`REOPENED`；正式 Ground Truth 只有每地区一条 GDP claim，与产业研究任务不匹配。
- Research Evidence：`INCONCLUSIVE`；第一轮事实指标不能解释为完整研究能力。
- Efficiency Performance：`REGRESSION_OBSERVED`；C 的时间和 token 成本明显高于 A/B。
- Overall Goal Completion：`NOT_COMPLETE`；等待有效 Benchmark 和第二轮验证。

### 续作优先级

1. `P0` 关闭历史付费授权解释，完成账单证据边界审计，不再发起业务 API 调用。
2. `P0` 建立 15–20 条/地区、任务匹配、双上下文核查的 rich Ground Truth 规范。
3. `P0` 重构 Fact Precision、Ground Truth Recall、Evidence Support、Factual Error 与 N/A 分母。
4. `P1` 通过离线控制样例校准 Judge，再冻结 Natural Execution 与 Matched Budget 协议。
5. `P2` 仅在有效 Benchmark 完成后开展真实模块消融。

续作计划：`docs/superpowers/plans/2026-10-18-goal-continuation-validity.md`。
P0 审计：`experiments/independent_comparison/reports/CONTINUATION_P0_AUDIT_20261018.md`。
当前资源 Gate：`experiments/independent_comparison/manifests/continuation_resource_gate_20261018.json`。
