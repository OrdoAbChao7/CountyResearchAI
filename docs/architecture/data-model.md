# 数据模型

> 对应代码：`domain/intelligence.py`、`domain/events.py`、`orchestration/state.py`、`api/schemas/`、`knowledge_graph/ontology/`。所有运行状态必须 JSON 可序列化。

## 1. 研究运行

### `ResearchRunCreate`（API 入参，`api/schemas/research.py`）

| 字段 | 类型 | 约束 |
| :--- | :--- | :--- |
| `county` | `str` | 2–40 字符，必填 |
| `focus` | `str \| None` | ≤ 60 字符；留空由 `DiscoveryService` 发现方向 |
| `objectives` | `list[str]` | ≤ 10 条，空白项会被剔除 |
| `mode` | `str` | 默认 `snapshot`，保留兼容字段 |
| `options` | `dict` | 预留扩展参数 |

`to_domain()` 转换为 `ResearchRunRequest`（county/focus/objectives/mode/options）。研究问题由 Supervisor 基于县名、方向与目标生成，不是独立入参。

### `ResearchRunRecord`（`domain/intelligence.py`）

| 字段 | 说明 |
| :--- | :--- |
| `run_id` | `run_<uuid12>` |
| `request` | `ResearchRunRequest` 快照 |
| `status` | `queued / running / completed / failed / cancelled` |
| `created_at`、`started_at`、`finished_at` | UTC |
| `current_agent`、`current_node`、`progress` | 运行进度 |
| `plan` | `ResearchPlan \| None` |
| `agent_results` | `list[AgentResult]` |
| `critique` | `CritiqueReport \| None` |
| `opportunities` | `list[OpportunityCandidate]` |
| `report_path` | 报告路径 |
| `evidence_count`、`graph_entities`、`graph_relations` | 统计 |
| `degraded`、`error` | 降级与失败信息 |
| `checkpoint_thread` | 检查点线程（通常等于 run_id） |

### `ResearchState`（LangGraph 状态，`orchestration/state.py`）

`TypedDict`，仅 JSON：

```python
run_id, county, focus, mode, objectives, research_question
round, max_rounds, plan, tasks
results: Annotated[list[dict], operator.add]
aggregated
critique, followup_queries
supplements: Annotated[list[dict], operator.add]
graph_stats
opportunities, opportunity_notes, report
status, error, degraded, evidence_count, progress
```

`SpecialistState` 只有 `task` 与 `results`；服务、证据库、事件发射器放在 `RunnableConfig.configurable`，绝不进入检查点。

## 2. 研究计划与结果

### `ResearchPlan`

```python
research_question: str
objectives: list[str]
tasks: list[ResearchTask]
rationale: str
round: int
planner_source: str      # llm / deterministic
```

### `ResearchTask`

```python
task_id: str
agent: AgentKind          # macro/industry/enterprise/policy/innovation/geo/quantitative/opportunity
objective: str
queries: list[str]
priority: int             # 数字越小越优先
round: int
parent_gap: str           # 由 Critic 缺口触发时记录来源
```

### `AgentResult`

```python
task_id: str
agent: AgentKind
summary: str
claims: list[Claim]
evidence_ids: list[str]
findings: dict[str, Any]
confidence: float
gaps: list[str]
metrics: dict[str, Any]
llm_calls: int
tool_calls: int
degraded: bool
error: str
started_at / finished_at: datetime
```

### `Claim`

```python
claim_id: str
text: str
evidence_ids: list[str]
confidence: float
verification_status: VerificationStatus   # verified / inferred / pending / unverified
source_agent: str
```

### `CritiqueReport`

```python
is_sufficient: bool
coverage: float            # 0..1
findings: list[CritiqueFinding]
followup_queries: list[str]
audited_claims: int
unsupported_claims: int
round: int
reasoning: str
```

`CritiqueFinding`：`kind`（`unsupported_claim / missing_evidence / conflict / weak_source / gap`）、`description`、`severity`（`high/medium/low`）、`agent`、`evidence_ids`、`followup_queries`。

### `OpportunityCandidate`

```python
opportunity_id: str
title: str
gap_type: GapType          # missing_segment / weak_local_supply / external_dependency /
                           # low_specialization / policy_gap / talent_tech_gap
segment: str
description, rationale: str
score: float
evidence_ids: list[str]
target_enterprises: list[str]
suggested_actions: list[str]
verification_status: VerificationStatus   # 默认 inferred
```

`OpportunityReport` 汇总 `county`、`industry`、`opportunities`、`missing_segments`、`weak_segments`、`external_dependencies`、`specialization_score`、`evidence_ids`、`notes`、`degraded`。

## 3. 证据与文档

### `RawDoc`（`models.py`）

`title`、`url`、`snippet`、`content`、`source`、`fetched_at`、`metadata`，以及质量字段 `published_at`、`domain_type`、`credibility_score`、`evidence_type`、`source_summary`。

### `EvidenceItem`（`models.py`）

| 字段 | 说明 |
| :--- | :--- |
| `id` | 证据 ID（运行内唯一） |
| `claim` | 事实陈述或统计指标 |
| `snippet`、`url`、`title`、`source_name` | 原文与来源 |
| `domain_type` | government / research / news / company / social / unknown |
| `credibility_score` | 0–1 |
| `year`、`administrative_scope`、`indicator_caliber` | 年份、口径、行政层级 |
| `verification_status` | verified / conflicting / unverified / insufficient |
| `corroborating_sources`、`topic` | 交叉佐证与主题 |

`EvidenceService` 负责证据入库、检索、prompt 渲染与快照持久化；运行级实例写入 `{run_id}/evidence.json`。

## 4. 知识图谱模型

见 [knowledge-graph-design.md](knowledge-graph-design.md)。核心模型：

### `KGEntity`

```python
id: str
type: EntityType           # 13 类
name, aliases
county: str
properties: dict[str, Any]
evidence_ids: list[str]
confidence: float
verification_status: VerificationStatus
valid_from / valid_to / observed_at: datetime | None
source: str
```

### `KGRelation`

```python
id: str                    # rel_<sha1>
source_entity_id, target_entity_id: str
relationship_type: RelationshipType
source_evidence_id: str
evidence_ids: list[str]
confidence: float
verification_status: VerificationStatus
valid_from / valid_to: datetime | None
observed_at: datetime
properties: dict[str, Any]
quote, extracted_by: str
```

模型层校验：`VERIFIED` 必须有证据引用；禁止自环；`valid_from <= valid_to`。

### `Subgraph`

```python
entities: list[KGEntity]
relations: list[KGRelation]
evidence_ids: list[str]
truncated: bool
```

## 5. 事件

### `RunEvent`（`domain/events.py`）

```python
seq: int                  # 单调递增
run_id: str
type: str                 # EventType 常量
agent: str = ""
node: str = ""
message: str = ""
data: dict[str, Any]
created_at: datetime
```

`EventType`：`run_queued`、`run_started`、`run_completed`、`run_failed`、`run_resumed`、`notice`、`node_started`、`node_completed`、`plan_created`、`agent_started`、`agent_tool_call`、`agent_tool_result`、`agent_completed`、`agent_failed`、`critique`、`supplement`、`graph_built`、`opportunities`、`report_ready`、`checkpoint_saved`。

事件写入 `events.jsonl`；SSE 支持 `?after=<seq>` 与 `Last-Event-ID`，运行结束后发送 `stream_end`。

## 6. 报告

### `IntelligenceReport`

```python
run_id, county, focus, research_question
executive_summary
sections: list[ReportSectionV2]   # title, content, order, agent, evidence_ids
opportunities: list[OpportunityCandidate]
evidence_index: list[dict]
gaps, agent_summaries
generated_at
markdown, report_path
degraded, model_used
```

## 7. 仿真（Star B）

### `SimulationRequest`

```python
baseline: BaselineProfile
scenario: SimulationScenario
```

- `BaselineProfile`：`county`、`industry`、`output_yi`（>0）、`growth_rate`、`employment`、`enterprise_count`、`source_year`、`evidence_ids`、`verification_status`、`notes`。
- `SimulationScenario`：`name`、`description`、`horizon_years`（1–20）、`shocks: ScenarioShock`。
- `ScenarioShock`：`growth_delta_pp`、`investment_yi`、`investment_output_ratio`、`productivity_delta`、`enterprise_growth_delta_pp`。

### `SimulationOutcome`

`county`、`industry`、`scenario`、`baseline`、`projections: list[YearProjection]`、`assumptions`、`model_type`、`model_version`、`verification_status`、`degraded`、`notes`、`metadata`。

## 8. 序列化契约

- API 入参/出参使用 Pydantic v2，`model_dump(mode="json")` 后写入磁盘。
- LangGraph 状态只放 `str/int/float/bool/list/dict/None`；枚举在节点边界转字符串。
- 证据与文档单独保存在 `RunArtifacts`，恢复运行时重新装载，不依赖检查点。
- 时间统一使用 UTC；报告展示时再格式化。
