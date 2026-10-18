# Independent Comparison 实施计划

## Review Focus

- 多进程同时预留同一 Provider 预算时必须只有允许范围内的租约成功。
- Provider 返回 HTTP 200 但缺少 usage 时必须标记未知，不能写入硬编码 token。
- 真实 Provider 初始化失败或返回 Mock 实例时运行必须无效，不能静默完成。
- 恢复运行时冻结协议/模型/预算哈希漂移必须拒绝继续。
- 匿名报告打包必须不包含地区之外的实验组来源、Ground Truth 或密钥。

## Task 1：Resource Manager 与持久化账本

**Files:**
- Create: `src/county_research_ai/evaluation/resource_manager.py`
- Test: `tests/test_evaluation_resource_manager.py`

**Interfaces:**
- `ResourceRequest(provider: str, model: str, kind: str, units: int, run_id: str)`
- `ResourceManager(path: Path, limits: Mapping[ResourceKey, ResourceLimit])`
- `reserve(request) -> Lease`
- `settle(lease_id, settled_units, *, usage: Mapping[str, Any] | None = None)`
- `fail(lease_id, reason)`
- `snapshot() -> ResourceSnapshot`

- [ ] 先写并运行失败测试：同一预算的并发租约、超额拒绝、重复结算、失败保守记账、跨进程 SQLite 锁。
- [x] 实现事务内 lease/reservation/settlement 表和按 Provider/Model/kind 的检查，并在实际结算超容量时记录 `overrun`。
- [x] 运行本文件测试，再运行完整 `pytest --no-cov -q`。

## Task 2：运行 Manifest、Artifact 和 Checkpoint

**Files:**
- Create: `src/county_research_ai/evaluation/experiment_models.py`
- Create: `src/county_research_ai/evaluation/checkpoints.py`
- Test: `tests/test_experiment_models.py`

**Interfaces:**
- `RunManifest.create(...)`, `.transition(status)`, `.write(path)`
- `RunArtifact.write_text/write_json`, `sha256(path)`
- `CheckpointStore.save/load` with config hash validation

- [ ] 先覆盖状态机、哈希稳定性、原子写入和漂移拒绝。
- [x] 实现严格字段模型和 JSON 持久化。

## Task 3：Strict Provider Adapter 与真实性检测

**Files:**
- Create: `src/county_research_ai/evaluation/providers.py`
- Modify: `src/county_research_ai/llm/client.py` only to expose non-sensitive request metadata if required
- Test: `tests/test_evaluation_providers.py`

**Interfaces:**
- `ProviderUsage.from_llm_response(response)`
- `StrictProviderGuard.assert_real(provider, run_id)`
- `DeepSeekSearchAdapter` with disabled-by-policy default

- [ ] 先测试真实 Usage、缺失 Usage、Mock provider、模型漂移和 DeepSeek 默认拒绝。
- [x] 实现适配器；禁止将 unknown usage 填成真实 token；DeepSeek 默认禁用。
- [x] 将 Judge 和 Fetch 调用纳入同一资源账本，并覆盖 usage 缺失与原始响应归档路径。

## Task 4：实验协议、样本与 Ground Truth Schema

**Files:**
- Create: `experiments/independent_comparison/protocol/protocol.yaml`
- Create: `experiments/independent_comparison/protocol/rubric.yaml`
- Create: `experiments/independent_comparison/protocol/data_dictionary.md`
- Create: `experiments/independent_comparison/datasets/official_regions.yaml`
- Test: `tests/test_experiment_protocol.py`

- [ ] 先写冻结字段、地区不重复、预算上限和 Rubric 分值范围的失败测试。
- [ ] 写入开发集与正式候选集的隔离声明；正式集在真实核验前标记 `UNFROZEN`。

## Task 5：隔离 Runner 与严格 C 入口

**Files:**
- Create: `src/county_research_ai/evaluation/experiment_runner.py`
- Create: `src/county_research_ai/evaluation/strict_container.py`
- Test: `tests/test_experiment_runner.py`

- [x] 覆盖 A/B/C 的独立输出目录、环境白名单、Mock 无效、失败样本保留和状态迁移。
- [x] 实现 E1 先导批次和 E2 固定输入批次的独立子进程协议、资源预留、原始输入输出快照和可恢复 checkpoint。
- [x] E2 校验冻结文档包哈希；A/B 不搜索，C 通过严格真实容器并显式关闭搜索。
- [ ] 将旧 `evaluation/runner.py` 保留为历史离线回归并在文档中隔离，不让新 Runner 复用其 Mock 文档。

## Task 6：Ground Truth、Blind Judge、Metrics 和报告

**Files:**
- Create: `src/county_research_ai/evaluation/ground_truth.py`
- Create: `src/county_research_ai/evaluation/judging.py`
- Create: `src/county_research_ai/evaluation/metrics.py`
- Create: `src/county_research_ai/evaluation/reporting.py`
- Create: `src/county_research_ai/evaluation/auditing.py`
- Test: `tests/test_experiment_metrics.py`

- [x] 覆盖声明级支持率、错误分类、有效/无效样本、双来源 Ground Truth、评分分歧和小样本统计边界。
- [x] 实现冻结 GT 读取、匿名打包、Rubric 校验、声明级指标计算和 Manifest 状态 Markdown 输出；正式 GT/盲评/图表仍待正式批次。
- [x] 实现仅消费 `VALID` 运行的汇总、配对差异、置信区间和真实数据图表生成器；无有效行时显式输出 `NO_VALID_METRICS`。

## Task 7：资源探针与 Smoke Test

**Files:**
- Create: `experiments/independent_comparison/manifests/smoke-test.yaml`
- Create: `scripts/run_independent_smoke.py`
- Test: `tests/test_smoke_manifest.py`

- [ ] 先执行 dry-run 验证预算、模型、输出目录和 Mock 检测。
- [ ] 仅在 Resource Manager 允许且账户免费边界可接受时执行极小真实探针；原始响应和 usage 不写入密钥。
- [ ] 若失败，输出 `BLOCKED` 或 `INVALID_*` checkpoint，不补造运行。

## Task 8：正式批次、统计、审计和最终报告

**Files:**
- Create: `experiments/independent_comparison/reports/FINAL_REPORT.md`
- Create: `scripts/analyze_independent_runs.py`
- Create: `scripts/audit_independent_runs.py`
- Test: `tests/test_final_report_inputs.py`

- [x] 验证报告只读取真实 Manifest/产物，失败样本保留在运行账本；现阶段报告明确标记 `INCONCLUSIVE`。
- [x] 提供 E2 固定输入批处理入口，并将输入包哈希写入每个运行产物。
- [ ] 按配额执行冻结批次，生成统计、图表、审计和结论。

## Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest --no-cov -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
```

真实实验命令必须从冻结 Manifest 生成，并在报告中原样记录；未执行的命令不得写成已完成。
