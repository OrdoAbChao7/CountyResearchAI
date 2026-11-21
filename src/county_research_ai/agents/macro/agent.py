"""宏观环境 Agent：经济总量、增长、财政、人口与产业结构。"""
from __future__ import annotations

from typing import Any

from ...domain.intelligence import AgentKind, ResearchTask
from ..base import AgentContext, AgentSpec, SpecialistAgent, ToolObservation
from ..fallbacks import (
    ECONOMIC_HINTS,
    build_gaps,
    claims_from_items,
    confidence_for,
    evidence_rows,
    filter_items,
    first_claim,
    observation_evidence,
)
from ..findings import MacroFindings

SYSTEM_PROMPT = """你是县域产业研究团队的宏观经济分析师。

职责边界：
- 只分析县域宏观经济基本面：GDP/生产总值、增长速度、财政收支、人口、居民收入、
  三次产业结构、规上工业增加值等统计指标。
- 不分析具体企业的经营与竞争关系（交给企业 Agent），不分析政策文本（交给政策 Agent），
  不判断产业链缺失环节（交给机会 Agent）。
- 数据必须来自工具返回的证据；禁止凭常识编造数字、年份或统计口径。
- 如果不同来源的数字冲突，保留冲突并在 gaps 中指出；不要擅自选择"更好看"的数字。

方法要求：
1. 优先使用统计公报、政府工作报告、统计年鉴类来源；
2. 每条结论标注 evidence_ids，并说明指标口径与年份（若证据中有）；
3. 区分"总量"与"增速"、"规上"与"全口径"；
4. 证据不足时明确写 gaps，而不是补全为完整叙事。

除通用字段外，尽量填写 gdp / growth / fiscal / population / indicators。"""


def build_fallback(
    spec: AgentSpec,
    observations: list[ToolObservation],
    context: AgentContext,
    task: ResearchTask,
) -> dict[str, Any]:
    items = filter_items(observation_evidence(observations, context), ECONOMIC_HINTS)
    claims = claims_from_items(items, max_claims=6)
    summary = (
        f"{context.county} 宏观经济：从 {len(items)} 条证据中整理出 "
        f"{len(claims)} 条可追溯结论。"
        if items
        else f"{context.county} 宏观经济：未获得可用统计数据。"
    )
    return {
        "summary": summary,
        "claims": claims,
        "gaps": build_gaps(items, required=("GDP", "增长")),
        "confidence": confidence_for(items, base=0.35),
        "metrics": {"evidence_count": len(items)},
        "gdp": first_claim(items, "GDP", "生产总值"),
        "growth": first_claim(items, "增长", "增速"),
        "fiscal": first_claim(items, "财政", "一般公共预算", "税收"),
        "population": first_claim(items, "人口", "常住"),
        "indicators": evidence_rows(items, limit=8),
    }


SPEC = AgentSpec(
    kind=AgentKind.MACRO,
    name="宏观环境分析师",
    description="县域宏观经济、统计指标与产业结构基本面",
    system_prompt=SYSTEM_PROMPT,
    tools=(
        "search_industry",
        "search_web",
        "evidence_search",
        "evidence_summary",
        "graph_query",
    ),
    output_model=MacroFindings,
    fallback_calls=(
        {
            "tool": "search_industry",
            "arguments": {"county": "{county}", "focus": "{focus}", "limit": 10},
        },
        {
            "tool": "evidence_search",
            "arguments": {
                "keywords": ["GDP", "生产总值", "产值", "增长", "财政", "人口"],
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
