"""机会 Agent：把产业链缺口转化为可执行机会（Star A 的 Agent 层）。"""
from __future__ import annotations

from typing import Any

from ...domain.intelligence import AgentKind, ResearchTask
from ..base import AgentContext, AgentSpec, SpecialistAgent, ToolObservation
from ..fallbacks import confidence_for, graph_observations, observation_evidence
from ..findings import OpportunityFindings

SYSTEM_PROMPT = """你是县域产业研究团队的产业机会分析师。

职责边界：
- 只负责把"产业链缺口"转化为可执行机会：补链招商、本地配套替代、集群培育、
  技术/人才补短板。
- 缺口来自 gap_radar_scan 的确定性结果，或来自图谱中 verified 的产业链关系。
  不得凭空创造"当地缺少某个产业"的结论。
- 每个机会必须说明：缺口类型、涉及环节、判断依据、证据、建议动作、置信度。
- 机会是分析推断而非事实：verification_status 只能是 inferred 或 pending，
  不能标为 verified。没有证据支撑的机会必须显著降低置信度。
- 不承诺投资金额、产值目标或企业意向；这些必须来自证据或标记为待调研。

方法要求：
1. 先调用 gap_radar_scan 获取缺口基线；
2. 用 graph_supply_chain / graph_enterprise_relations 核实环节与本地企业；
3. 必要时用 search_web / evidence_search 补充外部目标企业线索；
4. 按 score 排序，最多给出 8 个机会，并明确哪些需要实地调研。

除通用字段外，尽量填写 opportunities / missing_segments / weak_segments /
external_dependencies / specialization_score。"""


def _radar_data(observations: list[ToolObservation]) -> dict[str, Any]:
    for observation in observations:
        if observation.tool == "gap_radar_scan" and observation.ok and observation.data:
            return observation.data
    return {}


def build_fallback(
    spec: AgentSpec,
    observations: list[ToolObservation],
    context: AgentContext,
    task: ResearchTask,
) -> dict[str, Any]:
    radar = _radar_data(observations)
    items = observation_evidence(observations, context)
    opportunities = radar.get("opportunities", []) or []
    missing = radar.get("missing_segments", []) or []
    weak = radar.get("weak_segments", []) or []
    external = radar.get("external_dependencies", []) or []
    notes = radar.get("notes", []) or []
    if not radar:
        notes = ["缺口雷达未返回结果，机会分析降级为仅汇总图谱观察。"]
    graph_lines = [
        str(o.data.get("answer", ""))[:160]
        for o in graph_observations(observations)
        if o.data.get("answer")
    ]
    summary = (
        f"{context.county} {context.focus or '产业'}：基于缺口雷达识别 "
        f"{len(opportunities)} 个机会（缺失环节 {len(missing)}、弱配套 {len(weak)}、"
        f"外部依赖 {len(external)}）。"
        if radar
        else f"{context.county} {context.focus or '产业'}：缺口雷达不可用，未形成机会结论。"
    )
    return {
        "summary": summary,
        "claims": [],  # 机会是推断，不作为事实性 claim；证据保留在 opportunities 中
        "gaps": list(notes) + graph_lines,
        "confidence": confidence_for(items, base=0.3) if opportunities else 0.2,
        "metrics": {
            "opportunity_count": len(opportunities),
            "evidence_count": len(items),
        },
        "opportunities": opportunities[:8],
        "missing_segments": missing,
        "weak_segments": weak,
        "external_dependencies": external,
        "specialization_score": float(radar.get("specialization_score", 0.0) or 0.0),
    }


SPEC = AgentSpec(
    kind=AgentKind.OPPORTUNITY,
    name="产业机会分析师",
    description="基于产业链缺口的补链招商与本地配套机会",
    system_prompt=SYSTEM_PROMPT,
    tools=(
        "gap_radar_scan",
        "graph_supply_chain",
        "graph_enterprise_relations",
        "graph_query",
        "search_web",
        "evidence_search",
    ),
    output_model=OpportunityFindings,
    fallback_calls=(
        {
            "tool": "gap_radar_scan",
            "arguments": {"county": "{county}", "industry": "{focus}"},
        },
        {
            "tool": "evidence_search",
            "arguments": {
                "keywords": ["产业链", "配套", "招商", "龙头", "项目"],
                "limit": 15,
            },
        },
    ),
    fallback_builder=build_fallback,
    max_steps=6,
    max_llm_calls=6,
)


def build(
    llm: Any,
    tools: Any,
    *,
    max_steps: int | None = None,
    max_llm_calls: int | None = None,
) -> SpecialistAgent:
    return SpecialistAgent(
        SPEC, llm=llm, tools=tools, max_steps=max_steps, max_llm_calls=max_llm_calls
    )


__all__ = ["SPEC", "SYSTEM_PROMPT", "build", "build_fallback"]
