"""政策 Agent：产业政策、规划、扶持措施与政策-产业关联。"""
from __future__ import annotations

import re
from typing import Any

from ...domain.intelligence import AgentKind, ResearchTask
from ..base import AgentContext, AgentSpec, SpecialistAgent, ToolObservation
from ..fallbacks import (
    POLICY_HINTS,
    build_gaps,
    claims_from_items,
    confidence_for,
    filter_items,
    graph_observations,
    observation_evidence,
)
from ..findings import PolicyFindings

SYSTEM_PROMPT = """你是县域产业研究团队的政策研究分析师。

职责边界：
- 只负责政策文本与政策工具：产业规划、实施方案、财政补贴、税收优惠、土地/人才政策、
  政策与产业的对应关系。
- 必须区分"政策已发布"与"政策只是提及/建议"；必须标注政策名称、发布主体与时间（有则标）。
- 不评价政策执行效果（无证据时），不把企业宣传稿中的"将获得政策支持"当作既定政策。
- 不编造文号、发文时间或补贴金额。

方法要求：
1. 用 search_web / search_industry 检索政府网站与官方文件；
2. 用 graph_policy_links 查询已入库的政策-产业关系（inferred 关系需标注）；
3. 逐条给出 evidence_ids，并在 gaps 中记录政策空白或证据缺失；
4. 区分县级、市级、省级政策，避免把上级政策写成县级政策。

除通用字段外，尽量填写 policies / support_measures。"""

_POLICY_TITLE_RE = re.compile(r"《([^》]{2,60})》")


def _graph_policies(observations: list[ToolObservation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in graph_observations(observations):
        for entity in observation.data.get("entities", []) or []:
            if not isinstance(entity, dict) or entity.get("type") != "policy":
                continue
            name = str(entity.get("name", "")).strip()
            if name and name not in seen:
                seen.add(name)
                rows.append(
                    {
                        "title": name,
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
    items = filter_items(observation_evidence(observations, context), POLICY_HINTS)
    claims = claims_from_items(items, max_claims=6)
    policies = _graph_policies(observations)
    known = {p["title"] for p in policies}
    support: list[str] = []
    for item in items:
        for title in _POLICY_TITLE_RE.findall(item.claim):
            if title not in known:
                known.add(title)
                policies.append(
                    {
                        "title": title,
                        "evidence_ids": [item.id],
                        "verification_status": "verified",
                    }
                )
        if any(k in item.claim for k in ("补贴", "奖励", "税收", "用地", "人才", "基金")):
            support.append(item.claim.strip()[:160])
        if len(policies) >= 15 and len(support) >= 8:
            break
    summary = (
        f"{context.county} {context.focus or '产业'}：识别 {len(policies)} 项政策文本、"
        f"{len(support)} 条扶持措施线索。"
    )
    return {
        "summary": summary,
        "claims": claims,
        "gaps": build_gaps(items, required=("政策", "规划")),
        "confidence": confidence_for(items, base=0.32),
        "metrics": {"evidence_count": len(items), "policy_count": len(policies)},
        "policies": policies[:15],
        "support_measures": list(dict.fromkeys(support))[:10],
    }


SPEC = AgentSpec(
    kind=AgentKind.POLICY,
    name="政策研究分析师",
    description="县域产业政策、规划、扶持措施及政策-产业关联",
    system_prompt=SYSTEM_PROMPT,
    tools=(
        "search_web",
        "search_industry",
        "evidence_search",
        "evidence_summary",
        "graph_policy_links",
        "graph_query",
    ),
    output_model=PolicyFindings,
    fallback_calls=(
        {
            "tool": "search_web",
            "arguments": {"query": "{county} {focus} 产业政策 规划 扶持 实施方案", "limit": 8},
        },
        {
            "tool": "evidence_search",
            "arguments": {
                "keywords": ["政策", "规划", "意见", "方案", "补贴", "扶持"],
                "limit": 15,
            },
        },
        {
            "tool": "graph_policy_links",
            "arguments": {"industry": "{focus}"},
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
