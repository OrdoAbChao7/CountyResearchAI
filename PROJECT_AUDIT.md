# CountyResearchAI 仓库与实验可执行性审计

审计日期：2026-10-18

## 结论先行

仓库当前是可运行的研究原型，当前 437 个测试和本次改动范围内的 `ruff` 检查通过，但现有 Benchmark 不能证明 CountyResearchAI 相比基线的真实优势。正式实验前必须新增独立实验层，并修复或隔离以下有效性问题：历史 Runner 人为制造了文档覆盖差异；基线事实支持率核验了候选组的文本；专业角色主要是确定性规则分析；Synthesizer 写死 token 与泛化结论；容器初始化失败会静默回退到 Mock。

## Git 与项目状态

- 初始状态：`master` 与 `origin/master` 同步，工作树干净。
- GitHub：`https://github.com/OrdoAbChao7/CountyResearchAI.git`。
- 本环境尝试创建 `codex/independent-comparison` 失败，原因是无法写入 `.git/refs/heads/*.lock`；没有执行破坏性 Git 操作。
- 未发现项目目录内的 `AGENTS.md`，本次以用户提供的 Goal 指令为项目规则补充。

## 已真实具备的能力

### CLI、固定 Workflow 与研究模式

- `src/county_research_ai/cli.py` 提供 `snapshot`、`rise-fall`、`long-history`、`--deep` 和 Agent 入口。
- `application/`、`modes/`、`pipeline.py`、`reporting/` 形成可执行的资料采集、分析和 Markdown 报告流程。
- `research_agent/tree.py` 能构造问题树；`critic.py` 能依据证据缺口生成补充查询；`evidence/store.py` 和 `evidence/verifier.py` 提供结构化证据和规则核验。
- `agent/` 包含计划、工具、运行状态、轨迹和验证器，但其中的独立性与真实 LLM 使用仍需按实验要求重新判定。

### Provider 与 Usage

- `llm/client.py` 使用 OpenAI-compatible API，并解析响应中的 `prompt_tokens`、`completion_tokens`、`total_tokens`。
- `search/web_search.py` 已有 Tavily、Serper、Bing REST Provider，但没有中央配额、租约、实际 credit 结算或持久化资源状态。
- `.env` 当前配置为 `LLM_PROVIDER=gemini`、`LLM_MODEL=gemini-3.1-flash-lite`、Tavily 搜索；密钥未写入本审计。
- Gemini `models.list` 通过当前 Key 成功返回；最新只读刷新仍只证明模型可见性，不证明账户的免费额度或无付费风险。

## 必须隔离的实验缺陷

### 1. 历史离线 Runner 不是公平对照

`src/county_research_ai/evaluation/runner.py` 的 `BenchmarkRunner.run_case_comparison`：

- baseline 固定读取 `get_mock_case_documents(case_id)[:1]`，候选系统固定读取全部 Mock 文档；这不是相同输入、相同搜索条件或动态检索对照。
- 两组耗时只测本地列表切片，结果接近 0 秒，不是网络、抓取、LLM 和报告的端到端时间。
- baseline 的 `FactVerifier` 核验的是 `ref_test_text`，即从候选系统 EvidenceStore 生成的事实文本，而非 baseline 自己的报告；存在候选结果泄漏。
- 评估器依赖关键词/数字文本匹配，不能替代逐声明的 Claim-Evidence 核验。

这套 Runner 应保留为“历史离线回归”并明确命名，不得作为真实对照结论。

### 2. 专业多智能体不是真正独立的 LLM Agent

`research_agent/specialized/economic.py`、`policy.py`、`industry.py` 直接遍历 EvidenceStore 并拼接固定模板；没有调用 LLM，也没有独立上下文、独立模型调用或独立执行进程。`synthesizer.py` 继续拼接固定建议，并写入 `deep-multi-agent-v2` 和固定 token 数。

正确标记：`Deterministic Role Analyzers`。不能在正式报告中称为独立多模型 Agent。

### 3. 真实 Provider 失败会静默进入 Mock

`bootstrap/container.py` 在搜索和 LLM 初始化异常时分别构造 `MockSearchProvider` / `MockLLMClient`；`research_agent/coordinator.py` 的 `_get_llm` 也会捕获异常后返回 Mock。对产品开发的离线体验有价值，但对正式实验是污染。实验层必须使用 `strict_real` 模式：缺 Key、初始化失败、请求失败、Mock 类实例或固定模型回退均使运行无效。

### 4. Token 计量不完整

真实 `OpenAICompatibleClient` 解析了 API usage，但专业 Synthesizer 的 `AnalysisResult.tokens_used` 为固定值，MockLLM 也返回硬编码 800/1200/2000。正式实验必须只使用 Provider 返回的 usage；缺失 usage 时记录 `UNKNOWN`，不能补成真实消耗。

### 5. 缺少中央资源控制

现有搜索并发由 `SearchCollector` 管理，LLM/搜索/Judge 没有共享的预算、并发、状态或恢复机制。多 Agent 实验可能同时超额，也无法区分免费套餐、付费余额和未知计费状态。需要新增租约式 Resource Manager。

## 真实联网资源核验

- Gemini 官方定价页（2026-10-18 检索）：`gemini-3.1-flash-lite` 标注 Free Tier 输入/输出 token 免费；Grounding 另有计费规则，实验不启用。官方 Billing 文档指出付费 API Key 和账户计划会影响计费，实时配额应在 AI Studio 查看。因此本 Goal 采用“模型免费价格 ≠ 账户绝对无付费”的保守表述。
- Gemini 官方 Rate Limits 文档：额度按项目、模型和 RPM/TPM/RPD 维度变化，`models.list` 不返回账户实际余额/配额。
- Tavily 官方 pricing：免费计划 1,000 API credits/月、无需信用卡，额度耗尽后请求停止；最新只读 `/usage` 返回 Researcher 计划，230/1000 credits，paygo 使用量为 0，后续按保守剩余 770 credits 控制。
- DeepSeek 官方 Search & Fetch 文档：Search/Fetch 按成功请求收费，当前文档不支持把直接 HTTP 调用默认视为免费；本 Goal 默认禁用。
- `evaluation/providers.py` 的 DeepSeek Search/Fetch 适配器与 `search/web_search.py` 的正常 provider 已覆盖响应解析、URL/内容去重、元数据、Fetch 原始响应、HTTP 失败计数、限速和默认禁用行为；`create_provider` 与 A/B 基线会遵循冻结的 `search_provider`。测试使用离线 HTTP 替身，不产生 DeepSeek 请求。
- `scripts/precheck_independent_resources.py`、`tests/test_resource_precheck.py`：可重复刷新 Gemini `models.list` 与 Tavily `/usage` 的只读预检，并只读取 DeepSeek 本地配置；当前刷新结果写入 `manifests/resource_precheck_20261018_refresh.json`，不记录 API key，DeepSeek 的 LLM 与 Search/Fetch billing boundary 分开保持 `UNKNOWN`，不会被推断为免费。

## 验证证据

- `pytest --no-cov -q`：437 passed，1 个 `.pytest_cache` 写权限警告。
- 本次新增/修改的实验文件通过 scoped `ruff check`；全量 `ruff check src tests scripts` 仍受历史 `scripts/_verify_*.py` 等文件的 73 项既有问题影响，不能记为全仓库 clean。
- `scripts/audit_independent_runs.py`：检查 12 个运行目录；3 个历史 VALID 运行有 LLM 原始响应归档缺失警告，于都县先导另有已记录的资源容量超限错误。
- 历史 Runner 已复现：安吉 recall 0.4→1.0、信丰 0.2→1.0、鹤岗 0.2→0.8，但这是由 Mock 文档切片差异驱动，不能作为本 Goal 证据。

## 需要修复或隔离的项目

1. 保留旧 Runner 作为离线回归，新增 `experiments/independent_comparison`，禁止共享 Ground Truth 和组间报告。
2. 新增严格真实运行容器和 Mock 污染检测。
3. 新增 Resource Manager、RunManifest、Artifact、Checkpoint、Provider Usage 和失败状态。
4. 用冻结 Claim 列表和独立来源核验替代关键词/数字子串的唯一判断。
5. 把所有固定 token、固定优势叙述和规则式专业角色从真实实验计量中剔除。

## 可执行性判定

工程上可执行；资源上适合递进式运行。当前能确认 Gemini 模型可见性、公开 Free Tier 价格和 Tavily 当前用量，但不能确认 Gemini key 的账户级 billing/quota，因此本轮不应直接启动 54 次大实验。先实现资源控制和最小 Smoke Test，任何真实 API 失败都保存为有效的失败样本或 `BLOCKED` 检查点。

## Smoke Test 结果（2026-10-18）

- `smoke_20261018T095509Z` 实际结算 4 次 Gemini、39,061 tokens 和 26 次 Tavily 请求；A/B 安吉县运行有效，后续运行触发资源预算不足。没有 Mock 回退。
- 两次低预算 C 探针真实调用完成，但由于实验器路径规范化缺陷在 Manifest 收尾失败；失败产物保留，问题已由 Runner 根目录绝对化和回归测试修复。
- `c_probe_20261018T182500Z` 修复后标记 `VALID`：2 次 Gemini、7,659 实际 tokens、7 次 Tavily，报告/来源/raw docs/processed data 均有产物哈希，所有租约已结算。
- 当前代码已为后续运行接入每次 LLM 原始响应归档；上述历史批次发生在该能力接入前，因此审计报告保留归档缺失警告。
- 该 C 报告只获得一个较早的历史来源，没有 Ground Truth、盲评或公平 A/B/C 配对，因此只能证明真实链路可运行，不能证明项目质量优势。详见 `experiments/independent_comparison/reports/SMOKE_TEST_REPORT.md`。
- 于都县先导 `pilot_20261018T183000Z` 真实执行了 A/B/C：A/B 分别完成但合计实际 Gemini Usage 为 45,641，超过 24,000 本地批次上限；C 在下一次预留时被阻断。A/B Manifest 已更正为 `INVALID_RESOURCE_ACCOUNTING`，全部产物保留在原目录。该事件促成结算时超限熔断和审计规则修复。
- E2 固定输入路径已经实现：文档包有独立 schema/hash，A/B 共用同一文档集合且不搜索，C 使用 `strict_real` 容器并显式禁用搜索；六个有界摘录包由正式最小 manifest 固定引用，同时保留候选 manifest 历史状态。
- `evaluation/providers.py` 已将 Judge、Fetch 纳入同一 Resource Manager 账本；`generate_independent_stats.py` 仅从 `VALID` 运行生成汇总、配对差异和图表，当前无有效正式行时明确输出 `NO_VALID_METRICS`。
- `ground_truth/verifications/` 与 `verification_matrix_20261018.yaml` 保存 D1–D4 的独立核查；D5/D6 及 `industry_verification_matrix_20261018.yaml` 进一步核查产业 Claim。六地区最小正式 Ground Truth 已写入 `ground_truth/formal_ground_truth_20261018.jsonl` 并通过双来源/双上下文冻结校验；正式 QA/Claim 入口还通过 `GroundTruthStore.freeze_verified` 校验冻结 manifest 的 `source_hash`，拒绝静默替换；德清、攀枝花的后续修订以及长汀增速口径仍在争议矩阵中保留。六个 E2 固定输入包的正式 manifest 已冻结 hash，但尚未用于 API 批次。
- E1/E2 入口现在强制读取 `evaluation/gate.py` 的正式 API gate；当前 `NOT_RUN`、Gemini billing boundary 非 `FREE_CONFIRMED`、DeepSeek LLM 或 Search/Fetch 任一 boundary 未单独达到 `FREE_CONFIRMED`、模型身份/可见性未核实、资源预检超过 24 小时、缺少新鲜账户级 billing evidence、Tavily 余额耗尽或 PAYG 非零时，在创建运行目录前拒绝执行，避免未知、伪确认、过期或潜在付费状态下误调用业务模型。
- `scripts/run_independent_formal.py` 和 `scripts/run_independent_formal_worker.py` 已提供冻结六地区 E1 的三组独立进程编排、重复次数和低预算参数；当前只通过门禁拒绝探针，未产生正式 API 结果。
- `evaluation/gate.py::require_frozen_ground_truth` 及 E1/E2 runner/worker 入口会在创建正式批次目录或初始化业务资源前校验冻结 Ground Truth manifest hash；漂移会以 `FormalGateError` 拒绝。
- `evaluation/checkpoints.py::CheckpointStore.start/record` 已接入 E1/E2 编排器；批次中断后可用同一 batch id 和 `--resume` 继续，配置 hash 漂移、非终态运行或缺失 Manifest 不会被静默覆盖。
- E2 单组 worker 也在进程入口重复检查 formal gate；`scripts/run_independent_judges.py` 已提供 VALID 报告哈希校验、匿名盲评、双 Judge/分歧裁判和独立 Judge 资源账本，但当前没有正式 VALID 报告可评分。
- E1 研究器的 `max-search-results` 现在传递到每次 A/B Provider 请求，C 的 `usage_known` 读取 instrumented LLM 的实际 Usage；正式任务映射覆盖三类任务。
- `report_qa.py`、`run_independent_report_qa.py` 和 `score_independent_claims.py` 已把 Report-Based QA 与声明级 Ground Truth 评分接入 gate/资源账本；当前没有正式 VALID 报告，因此没有生成正式 observations。
