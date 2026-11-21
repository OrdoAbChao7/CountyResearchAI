"""产业与产业链 Agent：结构、环节、集群与主导产业。"""
from __future__ import annotations

from typing import Any

from ...domain.intelligence import AgentKind, ResearchTask
from ..base import AgentContext, AgentSpec, SpecialistAgent, ToolObservation
from ..fallbacks import (
    INDUSTRY_HINTS,
    build_gaps,
    claims_from_items,
    confidence_for,
    filter_items,
    first_claim,
    graph_observations,
    observation_evidence,
)
from ..findings import IndustryFindings

SYSTEM_PROMPT = """你是县域产业研究团队的产业与产业链分析师。

职责边界：
- 只负责产业结构与产业链：主导产业、细分环节、上下游关系、集群形态、
  本地配套与产业链完整度。
- 不负责宏观统计核算（宏观 Agent）、企业尽调（企业 Agent）、政策解读（政策 Agent）。
- 知识图谱中的关系分为 verified / pending / inferred。你只能把 verified 关系
  当作事实陈述；pending 与 inferred 关系必须明确标注"待核实/推断"。
- 不得自行发明企业名称、环节名称或上下游关系；所有关系必须来自图谱工具或证据。

方法要求：
1. 先用 search_industry 获取产业资料，再用 graph_supply_chain / graph_clusters
   读取已构建的产业链结构；
2. 给出环节清单时区分"有本地企业承载"与"仅存在于图谱/资料中"；
3. 定量指标（区位熵、集中度）交给定量 Agent，不自行计算；
4. 证据不足的环节写入 gaps，供 Supervisor 触发补充研究。

除通用字段外，尽量填写 segments / chain_structure / leading_industries / output_value。"""


def _entity_rows(observations: list[ToolObservation], entity_type: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in graph_observations(observations):
        for entity in observation.data.get("entities", []) or []:
            if not isinstance(entity, dict):
                continue
            if entity.get("type") != entity_type:
                continue
            name = str(entity.get("name", "")).strip()
            if name and name not in seen:
                seen.add(name)
                rows.append(entity)
    return rows


def build_fallback(
    spec: AgentSpec,
    observations: list[ToolObservation],
    context: AgentContext,
    task: ResearchTask,
) -> dict[str, Any]:
    all_items = observation_evidence(observations, context)
    items = filter_items(all_items, INDUSTRY_HINTS)
    claims = claims_from_items(items, max_claims=6)
    segments = [str(e.get("name", "")) for e in _entity_rows(observations, "industry_segment")]
    industries = [str(e.get("name", "")) for e in _entity_rows(observations, "industry")]
    graph_lines = [
        str(o.data.get("answer", ""))[:240]
        for o in graph_observations(observations)
        if o.data.get("answer")
    ]
    if not segments and not graph_lines:
        gaps = build_gaps(items, required=("产业链", "环节"))
        gaps.append("知识图谱尚未提供产业链环节结构")
    else:
        gaps = build_gaps(items)
    summary = (
        f"{context.county} {context.focus or '产业'}：识别 {len(segments)} 个产业链环节、"
        f"{len(industries)} 个产业节点，整理 {len(claims)} 条证据结论。"
    )
    return {
        "summary": summary,
        "claims": claims,
        "gaps": gaps,
        "confidence": confidence_for(items, base=0.35),
        "metrics": {
            "evidence_count": len(items),
            "segment_count": len(segments),
        },
        "segments": segments[:20],
        "leading_industries": industries[:10],
        "chain_structure": "；".join(graph_lines)[:1200],
        "output_value": first_claim(items, "产值", "增加值", "营业收入"),
    }


SPEC = AgentSpec(
    kind=AgentKind.INDUSTRY,
    name="产业与产业链分析师",
    description="县域产业结构、产业链环节、集群与上下游关系",
    system_prompt=SYSTEM_PROMPT,
    tools=(
        "search_industry",
        "search_web",
        "evidence_search",
        "graph_query",
        "graph_supply_chain",
        "graph_clusters",
        "graph_chain_paths",
    ),
    output_model=IndustryFindings,
    fallback_calls=(
        {
            "tool": "search_industry",
            "arguments": {"county": "{county}", "focus": "{focus}", "limit": 12},
        },
        {
            "tool": "graph_supply_chain",
            "arguments": {"industry": "{focus}", "direction": "both", "depth": 2},
        },
        {
            "tool": "evidence_search",
            "arguments": {
                "keywords": ["产业链", "龙头", "规上", "加工", "集群", "专精特新"],
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
