"""创新 Agent：技术能力、专利、研发平台与科研机构。"""
from __future__ import annotations

import re
from typing import Any

from ...domain.intelligence import AgentKind, ResearchTask
from ..base import AgentContext, AgentSpec, SpecialistAgent, ToolObservation
from ..fallbacks import (
    INNOVATION_HINTS,
    build_gaps,
    claims_from_items,
    confidence_for,
    filter_items,
    observation_evidence,
)
from ..findings import InnovationFindings

SYSTEM_PROMPT = """你是县域产业研究团队的创新与技术分析师。

职责边界：
- 只负责创新体系：研发投入、专利、技术创新平台、科研院所、实验室、企业技术中心、
  产学研合作。
- 不把"企业名称含科技二字"当作技术能力证据；不编造专利数量、研发投入比例或平台等级。
- 专利数据必须注明是申请量/授权量、发明/实用新型，以及年份与来源；口径不明时写入 gaps。
- 推断性的"技术短板"必须标注为推断，并说明缺少哪类证据。

方法要求：
1. 用 search_web / search_industry 检索专利、研发平台、产学研合作信息；
2. 用 graph_query 查询已入库的技术/专利/机构实体及其与产业的支撑关系；
3. 每条结论给出 evidence_ids；
4. 区分企业自建平台与政府/高校共建平台。

除通用字段外，尽量填写 technologies / patents / institutions。"""

_INSTITUTION_RE = re.compile(
    r"([一-龥A-Za-z0-9（）()·]{2,40}?(?:研究院|研究所|大学|学院|实验室|技术中心|工程中心|创新中心))"
)


def build_fallback(
    spec: AgentSpec,
    observations: list[ToolObservation],
    context: AgentContext,
    task: ResearchTask,
) -> dict[str, Any]:
    items = filter_items(observation_evidence(observations, context), INNOVATION_HINTS)
    claims = claims_from_items(items, max_claims=6)
    technologies: list[str] = []
    patents: list[str] = []
    institutions: list[str] = []
    for item in items:
        text = item.claim.strip()
        if "专利" in text:
            patents.append(text[:160])
        if any(k in text for k in ("技术", "工艺", "研发", "创新")):
            technologies.append(text[:160])
        institutions.extend(m.group(1) for m in _INSTITUTION_RE.finditer(text))
    summary = (
        f"{context.county} {context.focus or '产业'}：整理 {len(technologies)} 条技术线索、"
        f"{len(patents)} 条专利线索、{len(set(institutions))} 个创新机构线索。"
    )
    return {
        "summary": summary,
        "claims": claims,
        "gaps": build_gaps(items, required=("专利", "研发")),
        "confidence": confidence_for(items, base=0.3),
        "metrics": {"evidence_count": len(items)},
        "technologies": list(dict.fromkeys(technologies))[:10],
        "patents": list(dict.fromkeys(patents))[:10],
        "institutions": list(dict.fromkeys(institutions))[:10],
    }


SPEC = AgentSpec(
    kind=AgentKind.INNOVATION,
    name="创新与技术分析师",
    description="县域研发投入、专利、创新平台与科研机构",
    system_prompt=SYSTEM_PROMPT,
    tools=(
        "search_web",
        "search_industry",
        "evidence_search",
        "graph_query",
        "graph_multi_hop",
    ),
    output_model=InnovationFindings,
    fallback_calls=(
        {
            "tool": "search_web",
            "arguments": {
                "query": "{county} {focus} 专利 研发 技术创新 科研平台 产学研",
                "limit": 8,
            },
        },
        {
            "tool": "evidence_search",
            "arguments": {
                "keywords": ["专利", "研发", "技术", "科研", "创新", "实验室"],
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
