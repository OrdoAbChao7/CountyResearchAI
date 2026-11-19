"""地理与载体 Agent：园区、土地、交通与资源禀赋。"""
from __future__ import annotations

from typing import Any

from ...domain.intelligence import AgentKind, ResearchTask
from ..base import AgentContext, AgentSpec, SpecialistAgent, ToolObservation
from ..fallbacks import (
    GEO_HINTS,
    build_gaps,
    claims_from_items,
    confidence_for,
    filter_items,
    first_claim,
    graph_observations,
    observation_evidence,
)
from ..findings import GeoFindings

SYSTEM_PROMPT = """你是县域产业研究团队的地理与产业载体分析师。

职责边界：
- 只负责空间与载体：产业园区、开发区、基地、土地供应、交通区位、资源禀赋、
  园区企业集聚。
- 不把"规划中"的园区当作已建成载体；必须区分已认定/在建/规划。
- 不编造园区面积、入驻企业数量、土地价格；没有证据时写入 gaps。
- 不分析企业财务、政策补贴细则或宏观统计。

方法要求：
1. 用 search_web / search_industry 检索园区、土地、交通信息；
2. 用 graph_clusters 查询已入库的集群/园区节点，用 graph_park_enterprises 查询入驻企业；
3. 每条结论给出 evidence_ids；
4. 资源禀赋只描述有证据支撑的要素（矿产、农林、能源、区位等）。

除通用字段外，尽量填写 parks / transport / land / resource_endowment。"""


def _graph_parks(observations: list[ToolObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in graph_observations(observations):
        for entity in observation.data.get("entities", []) or []:
            if not isinstance(entity, dict) or entity.get("type") != "industrial_park":
                continue
            name = str(entity.get("name", "")).strip()
            if name and name not in seen:
                seen.add(name)
                rows.append(
                    {
                        "name": name,
                        "evidence_ids": entity.get("evidence_ids", []),
                        "verification_status": entity.get("verification_status", ""),
                    }
                )
    return rows


def build_fallback(
    spec: AgentSpec,
    observations: list[ToolObservation],
    context: AgentContext,
    task: ResearchTask,
) -> dict[str, Any]:
    items = filter_items(observation_evidence(observations, context), GEO_HINTS)
    claims = claims_from_items(items, max_claims=6)
    parks = _graph_parks(observations)
    known = {p["name"] for p in parks}
    for item in items:
        for token in ("园区", "开发区", "工业园", "产业园", "基地"):
            if token in item.claim:
                snippet = item.claim.strip()[:120]
                if snippet not in known:
                    known.add(snippet)
                    parks.append(
                        {"name": snippet, "evidence_ids": [item.id], "verification_status": "verified"}
                    )
                break
    summary = (
        f"{context.county} {context.focus or '产业'}：识别 {len(parks)} 个园区/载体线索，"
        f"整理 {len(claims)} 条区位证据。"
    )
    return {
        "summary": summary,
        "claims": claims,
        "gaps": build_gaps(items, required=("园区", "交通")),
        "confidence": confidence_for(items, base=0.3),
        "metrics": {"evidence_count": len(items), "park_count": len(parks)},
        "parks": parks[:12],
        "transport": first_claim(items, "交通", "铁路", "高速", "港口", "机场"),
        "land": first_claim(items, "土地", "用地", "供地"),
        "resource_endowment": first_claim(items, "资源", "矿产", "农林", "能源"),
    }


SPEC = AgentSpec(
    kind=AgentKind.GEO,
    name="地理与载体分析师",
    description="县域产业园区、土地、交通区位与资源禀赋",
    system_prompt=SYSTEM_PROMPT,
    tools=(
        "search_web",
        "search_industry",
        "evidence_search",
        "graph_query",
        "graph_clusters",
        "graph_park_enterprises",
        "graph_multi_hop",
    ),
    output_model=GeoFindings,
    fallback_calls=(
        {
            "tool": "search_web",
            "arguments": {
                "query": "{county} {focus} 产业园区 开发区 土地 交通 区位",
                "limit": 8,
            },
        },
        {
            "tool": "graph_clusters",
            "arguments": {"county": "{county}", "industry": "{focus}"},
        },
        {
            "tool": "evidence_search",
            "arguments": {
                "keywords": ["园区", "开发区", "基地", "交通", "土地", "资源"],
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
