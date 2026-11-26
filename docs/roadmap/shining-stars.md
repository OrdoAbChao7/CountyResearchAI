# Shining Stars 路线图（实验性分析层）

> **前置门禁（[ADR-005](../architecture/ADR-005-single-evidence-core.md)）**：Shining Stars 当前属于实验性模块，尚未接入权威证据图谱 `evidence/graph.py`。在重新启动功能迭代前必须满足两项前置条件：(1) `services/evidence_service` 完成只读适配器改造，仅消费 `evidence/graph.py` 中通过时间窗、地域与 0.65 来源门槛的 `SUPPORTED` Finding；(2) 企业与统计数据源补齐，使龙头企业与核心产值问题在多县样本上达到 `SUPPORTED`（避免把“检索缺失”误判为“产业链缺口”）。
>
> 三个「亮点」能力：A 产业链缺口雷达、B 产业数字孪生、C 时序产业智能。
> 原则：先把领域契约、证据边界与确定性实现做对，再引入需要校准的模型。

## Star A · 产业链缺口雷达

### 已实现

- `services/opportunity_service.py::GapRadarService.scan(county, industry)`。
- 识别四类机会：
  | 类型 | 判定 | 基础分 |
  | :--- | :--- | :---: |
  | `missing_segment` | 链条环节存在，但县域无相关企业 | 0.78 |
  | `weak_local_supply` | 本地企业少或规模弱 | 0.62 |
  | `external_dependency` | 关键投入依赖县外企业 | 0.55 |
  | `low_specialization` | 区位熵低于阈值 | 0.50 |
- 叠加证据数量/验证状态修正；输出 `OpportunityCandidate { rationale, suggested_actions, target_enterprises, evidence_ids, score, verification_status }`。
- 机会固定为 `PENDING` / `INFERRED`，报告与 API 显式标注「分析推断」，不会写成既成事实。
- Agent `opportunity` 通过 `gap_radar_scan` 工具调用；Supervisor 在 Critic 充分后调度。
- 测试：`tests/test_services_v2.py` 的 `_seed_gap_graph` 覆盖四类机会与评分。

### 边界

- 评分是可解释启发式，不是经训练的预测模型；未经专家复核不得作为招商决策依据。
- 企业覆盖不足时，`missing_link` 可能是数据缺失而非真实缺口，需在报告中提示。

### 下一步

1. **数据补全**：接入企业名录、园区企业、海关/工商数据，降低「无企业=缺口」的误判。
2. **评分校准**：用标注案例（已知补链成功/失败）拟合权重，输出校准曲线与置信区间。
3. **目标企业推荐**：基于供应链位置、规模、地域距离与招商政策匹配度排序，并给出可核验的依据。
4. **专家复核闭环**：API 增加机会审核状态（待审/确认/驳回），把复核结果回写评分。

## Star B · 产业数字孪生

### 已实现

- 领域契约：`shining_stars/digital_twin/models.py` 的 `SimulationEngine` 协议、`SimulationRequest/Result`、`Assumption`、`Projection`。
- `BaselineEngine`：确定性会计外推（产出、企业数、就业按显式增长率复利），记录全部假设与局限。
- `DigitalTwinService`：
  - `capabilities()` 返回可用引擎与限制；
  - `baseline()` / `simulate()` 输出逐年投影；
  - 证据不足时 `degraded=True` 并说明；
  - 配置 `simulation.engine="mesa"`（或直接 `_build_engine("mesa")`）抛 `SimulationEngineUnavailable`，不返回伪结果。
- API：`GET /api/simulations/capabilities`、`POST /api/simulations`。
- 测试：`tests/test_shining_stars.py` 覆盖确定性、边界、禁用与 Mesa 不可用。

### 边界

- 当前没有价格、投资、政策反馈、企业进出与行为规则，不能回答「政策会带来多少增长」。
- 基线只做会计恒等式外推，不是因果模型。

### 下一步（按顺序，未完成前不引入 Mesa）

1. **校准数据集**：县域产出/企业/就业时间序列，统一口径与缺失值处理。
2. **情景协议**：定义投资、补贴、用地、能耗等外生变量的单位、范围与来源。
3. **验证方案**：历史回测（2018–2023）与留出年份误差指标；误差阈值写入验收标准。
4. **引擎实现**：先做系统动力学/投入产出，再评估 Mesa 的 Agent 行为建模；每个引擎必须通过同一契约测试。
5. **可解释性**：输出每步假设、敏感性与不确定性区间，禁止单点「精确预测」。

## Star C · 时序产业智能

### 已实现

- 关系级时间字段：`valid_from`、`valid_to`、`observed_at`。
- `GraphStore.get_relations(..., as_of=...)` 时点过滤；InMemory 与 Neo4j 语义一致（仅显式 `as_of` 过滤）。
- `TemporalQuery`：`snapshot_as_of(as_of, county="")`、`relations_as_of(...)`、`verified_relation_count(as_of)`、`entity_history(entity_id)`、`diff(before, after, county="")`。
- `services/graph_builder.py` 写入 `observed_at`；抽取器保留原文日期（可得时）。
- 测试：`tests/test_shining_stars.py` 的快照/历史/差异；`tests/test_knowledge_graph.py` 的时点过滤。

### 边界

- 当前是「有效区间」模型，无法表达同一关系的多次修订与来源冲突。
- 关系消失通常意味着「本期未观测到」，不一定是真实退出；需在 UI/报告区分。

### 下一步

1. **版本节点**：为关系建立 `RelationVersion` 节点，记录修订原因、来源与替代关系。
2. **双时态**：区分「业务有效期」与「记录时间」，支持追溯某次研究当时看到的图谱。
3. **事件抽取**：从政策/新闻抽取「签约、投产、退出、扩产」事件，落到时间线。
4. **变更检测**：按研究周期对比图谱，自动生成「新增/消失/增强/减弱」报告。
5. **Graphiti 评估**：仅当版本链与事件时间线需求稳定后，再评估引入 Graphiti；当前不增加依赖。

## 验收门禁（三个 Star 共用）

- 所有事实性输出可追溯到 Evidence ID；无证据内容必须标 `inferred/pending`。
- 任何模拟/预测必须列出假设、区间与局限，并拒绝未校准引擎。
- 新能力必须有确定性测试；外部服务缺失时可降级运行。
- 文档与 API Schema 同步更新，不以「未来会实现」描述当前能力。
