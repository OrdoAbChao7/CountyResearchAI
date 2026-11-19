"""企业 Agent：龙头企业、企业关系网络与竞争/合作关系。"""
from __future__ import annotations

import re
from typing import Any

from ...domain.intelligence import AgentKind, ResearchTask
from ..base import AgentContext, AgentSpec, SpecialistAgent, ToolObservation
from ..fallbacks import (
    build_gaps,
    claims_from_items,
    confidence_for,
    filter_items,
    graph_observations,
    observation_evidence,
)
from ..findings import EnterpriseFindings

SYSTEM_PROMPT = """你是县域产业研究团队的企业研究分析师。

职责边界：
- 只负责企业层面的信息：龙头企业、规上企业、专精特新、企业间供应/合作/竞争关系、
  企业归属的产业链环节。
- 不编造企业营收、员工人数、市场份额等数字；没有证据就写 gaps。
- 知识图谱中 inferred/pending 的企业关系只能作为"待核实线索"表述，
  不得写成确定事实。不得把"同处一个园区"推断为"存在供应关系"。
- 同名企业必须结合县域与产业方向消歧；无法确认时保留原名并标注不确定。

方法要求：
1. 用 search_web / search_industry 获取企业名单与公开报道；
2. 用 graph_enterprise_relations / graph_supply_chain 查询已入库关系；
3. 每家企业尽量给出 evidence_id 或来源链接；
4. 区分"本地企业"与"外部企业/招商目标"。

除通用字段外，尽量填写 enterprises / key_relations / concentration。"""

_ENTERPRISE_RE = re.compile(
    r"([一-龥A-Za-z0-9（）()·]{2,40}?"
    r"(?:股份有限公司|有限责任公司|有限公司|集团|厂|研究院))"
)


def _graph_enterprises(observations: list[ToolObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in graph_observations(observations):
        for entity in observation.data.get("entities", []) or []:
            if not isinstance(entity, dict) or entity.get("type") != "enterprise":
                continue
            name = str(entity.get("name", "")).strip()
            if name and name not in seen:
                seen.add(name)
                rows.append(
                    {
                        "name": name,
                        "county": entity.get("county", ""),
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
    items = filter_items(observation_evidence(observations, context), ("企业", "龙头", "规上", "专精特新"))
    claims = claims_from_items(items, max_claims=6)
    enterprises = _graph_enterprises(observations)
    known = {e["name"] for e in enterprises}
    for item in items:
        for match in _ENTERPRISE_RE.finditer(item.claim):
            name = match.group(1)
            if name not in known and len(name) >= 4:
                known.add(name)
                enterprises.append(
                    {
                        "name": name,
                        "county": context.county,
                        "evidence_ids": [item.id],
                        "verification_status": "verified",
                    }
                )
            if len(enterprises) >= 20:
                break
    relations: list[dict[str, Any]] = []
    for observation in graph_observations(observations):
        for relation in observation.data.get("relations", []) or []:
            if isinstance(relation, dict):
                relations.append(relation)
    summary = (
        f"{context.county} {context.focus or '产业'}：整理 {len(enterprises)} 家企业线索、"
        f"{len(relations)} 条图谱关系。"
    )
    return {
        "summary": summary,
        "claims": claims,
        "gaps": build_gaps(items, required=("企业",)) if enterprises else ["未识别出明确的企业主体"],
        "confidence": confidence_for(items, base=0.32),
        "metrics": {"evidence_count": len(items), "enterprise_count": len(enterprises)},
        "enterprises": enterprises[:20],
        "key_relations": relations[:20],
        "concentration": "",
    }


SPEC = AgentSpec(
    kind=AgentKind.ENTERPRISE,
    name="企业研究分析师",
    description="县域龙头企业、规上企业、企业关系网络与产业链归属",
    system_prompt=SYSTEM_PROMPT,
    tools=(
        "search_web",
        "search_industry",
        "evidence_search",
        "graph_query",
        "graph_enterprise_relations",
        "graph_supply_chain",
        "graph_multi_hop",
    ),
    output_model=EnterpriseFindings,
    fallback_calls=(
        {
            "tool": "search_web",
            "arguments": {"query": "{county} {focus} 龙头企业 规上企业 专精特新", "limit": 8},
        },
        {
            "tool": "evidence_search",
            "arguments": {
                "keywords": ["有限公司", "集团", "龙头", "规上", "专精特新"],
                "limit": 20,
            },
        },
        {
            "tool": "graph_supply_chain",
            "arguments": {"industry": "{focus}", "direction": "both", "depth": 2},
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
