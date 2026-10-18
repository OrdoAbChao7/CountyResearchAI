# Independent Comparison

这是 CountyResearchAI 真实效能验证的独立实验区。目录内只保存协议、冻结输入、运行原始产物、评分、指标、图表和报告；既有 `src/county_research_ai/evaluation/runner.py` 的三案例 Mock Benchmark 仍属于历史离线回归，不与本实验混用。

实验结果状态必须使用 `VALID`、`INVALID_*`、`FAILED`、`BLOCKED` 或 `NOT_RUN`。没有真实 Provider Usage、发生 Mock 回退、输入污染或预算状态未知时，不能标记为有效质量结果。

## 当前状态

现有运行是开发集 Smoke 和低预算探针，`FINAL_REPORT.md` 明确标记为 `INCONCLUSIVE`；它们不构成正式 A/B/C 性能结论。六地区最小正式目标已冻结在 `datasets/formal_regions_20261018.yaml`、`ground_truth/formal_ground_truth_20261018.jsonl` 和对应 manifest；E1 primary task 映射覆盖 `snapshot`、`rise-fall`、`long-history`；`datasets/official_regions.yaml` 保留候选集历史状态。

资源预检可用以下只读命令刷新；它只访问 Gemini `models.list` 与 Tavily `/usage`，并只读取 DeepSeek 本地配置，不会调用业务模型、搜索或 Fetch，也不会自动打开 formal gate。DeepSeek Search/Fetch 已接入普通 `create_provider` 工厂，但仍默认 `disabled_by_policy`；配置 `SEARCH_PROVIDER=deepseek` 不能单独解锁真实请求：必须显式设置 `DEEPSEEK_SEARCH_ENABLED=true`，并在实验 gate 中分别记录 DeepSeek LLM 与 Search/Fetch 的免费/计费证据。

```powershell
.\.venv\Scripts\python.exe scripts/precheck_independent_resources.py --output experiments/independent_comparison/manifests/resource_precheck_YYYYMMDD_refresh.json
```

E2 固定输入入口已经实现。正式最小目标的六个 JSON 文档包由 `datasets/fixed_input_formal_manifest_20261018.json` 固定引用，运行前仍需完成账户配额/计费检查和低预算预检：

```powershell
.\.venv\Scripts\python.exe scripts/run_independent_fixed_input.py --input-pack <path-to-frozen-pack.json> --batch-id e2_YYYYMMDD
```

该入口会为 A、B、C 各启动一个独立进程；三组共享同一个 `source_hash`，搜索被协议级禁用，C 使用严格真实容器分析冻结资料。批次根目录固定在项目内，不依赖启动命令的当前工作目录。候选输入、正式输入和争议 Ground Truth 分开记录，不能把补充面板当作正式指标。批次会写入配置绑定的 `checkpoint.json`；中断后必须使用同一个 `--batch-id --resume`，已完成的终态运行会跳过，配置漂移或未完成运行目录会拒绝静默覆盖。

E1 正式编排入口要求显式指定地区；低预算单地区预检示例：

```powershell
.\.venv\Scripts\python.exe scripts/run_independent_formal.py --region 德清县 --repeats 1 --max-tokens 512 --max-search-results 1 --batch-id e1_preflight_YYYYMMDD
```

该入口同样先检查 `manifests/formal_target_gate_20261018.json`，当前 gate 为 `NOT_RUN` 时不会创建运行目录或调用业务 API。中断恢复使用同一个 batch id 加 `--resume`；checkpoint 配置 hash 不匹配、已有运行仍处于 `PLANNED/RUNNING` 或 checkpoint 引用缺失 Manifest 时直接失败。

## 盲评入口

正式运行产生 `VALID` 报告后，使用独立 judge 进程入口进行匿名评分。入口只接受 Manifest 显式标记 `formal_target: true` 的正式运行，并先校验报告产物哈希；历史开发集 `VALID` 运行会被排除。之后只把匿名报告发送给至少两个独立 Judge；达到 Rubric 规定的维度分歧时追加 adjudicator。Judge 调用也受 formal gate 和单独的 `kind=judge` 资源账本控制：

```powershell
.\.venv\Scripts\python.exe scripts/run_independent_judges.py --runs-root experiments/independent_comparison/runs/<formal-batch> --output-dir experiments/independent_comparison/judgements/<judge-batch> --max-runs 1
```

当前 gate 为 `NOT_RUN`，因此该命令不会启动 API 评分；没有 `VALID` 运行时只写入 `NO_VALID_RUNS`，不生成伪评分。

## Report-Based QA 与统计

冻结问题位于 `protocol/report_qa_questions_20261018.yaml`。正式报告完成后，QA Agent 只读取匿名报告回答问题，评分器再独立读取 Ground Truth：

```powershell
.\.venv\Scripts\python.exe scripts/run_independent_report_qa.py --runs-root experiments/independent_comparison/runs/<formal-batch> --output-dir experiments/independent_comparison/judgements/<qa-batch> --max-runs 1
```

QA 和 Judge 都在 gate 关闭时停止；只有正式 `VALID` 运行、回答归档和指标 observation 完整后，统计脚本才会生成正式图表。

声明级事实核验入口为 `scripts/score_independent_claims.py`。它在 Ground Truth 评分阶段先用 `GroundTruthStore.freeze_verified` 校验正式 Ground Truth manifest 的 `source_hash`，再读取每个地区的冻结 claim、匿名报告和该运行归档的来源材料，生成 `claim_observations.jsonl`；Claim Verifier 失败、Usage 不明或 JSON 无法解析的行保留为无效状态，不进入统计。Report-Based QA 入口使用相同的冻结校验。

使用 `scripts/merge_independent_observations.py` 将 Claim、Judge 和 QA 结果按 `run_id` 合并，再把输出交给 `scripts/generate_independent_stats.py`；缺失的后处理分数保持缺失，不会填充默认高分。统计生成器同时写出按组汇总、按地区×组汇总的 `region_summary.csv`，并生成 `region_<metric>.svg`，用于检查各测试地区的差异。

正式目标批次当前由 `manifests/formal_target_gate_20261018.json` 明确记录为 `NOT_RUN`，并指向最新只读资源预检；该记录不进入质量指标。预检脚本 `scripts/precheck_independent_resources.py` 只访问 Gemini `models.list` 和 Tavily `/usage`，不会调用业务模型、搜索或 Fetch。正式 gate 还要求预检带时区时间戳且不超过 24 小时、Gemini provider/model/可见性与 gate 一致；若 Gemini 标记为 `FREE_CONFIRMED`，还必须提供新鲜的 `source`、`method`、`account_scope`、`evidence_ref`、`verified_at` 账户级证据，并要求 Tavily 有正的 conservative remaining credits 且 PAYG 为 0，防止把手工字段改写或潜在付费余额误当作免费资格判断。

正式启动配置冻结在 `manifests/formal_launch_manifest_20261018.json`，包括 E1/E2 输出目录、模型、任务、预算、preflight 子集和所有协议/输入 hash。它是启动前审计证据，不代表正式 API 已执行。

gate 解锁时还会重新校验该 manifest 的模型/Provider 一致性、冻结文件 hash 和 E2 pack 文件 hash；任何漂移都会在创建运行目录前拒绝。

## 可复核命令

```powershell
.\.venv\Scripts\python.exe scripts/audit_independent_runs.py --runs-root experiments/independent_comparison/runs --json-output experiments/independent_comparison/reports/AUDIT_REPORT.json
.\.venv\Scripts\python.exe scripts/analyze_independent_runs.py --runs-root experiments/independent_comparison/runs --output experiments/independent_comparison/reports/FINAL_REPORT.md
```

审计会校验 Manifest 声明的产物哈希、资源账本中的未结算租约，并把历史 LLM 原始响应归档缺失记录为警告。
