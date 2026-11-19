"""定量 Agent：只做确定性计算，LLM 负责选择算法与解释。

数学计算全部由 QuantService 完成；LLM 不得自行推算数值。
"""
from __future__ import annotations

from typing import Any

from ...domain.intelligence import AgentKind, ResearchTask
from ..base import AgentContext, AgentSpec, SpecialistAgent, ToolObservation
from ..fallbacks import (
    claims_from_items,
    confidence_for,
    metric_payloads,
    observation_evidence,
)
from ..findings import QuantFindings

SYSTEM_PROMPT = """你是县域产业研究团队的定量分析师。

最重要的规则：
- 所有数值计算必须通过工具完成（quant_location_quotient / quant_shift_share /
  quant_hhi / quant_cr_n / quant_from_evidence）。禁止心算、估算或编造数值。
- 你只负责：理解问题、选择合适的算法、准备输入、解释工具返回值。
- 输入数据必须来自证据库或明确的工具返回；使用证据数值时把 evidence_ids 传给工具。
- 如果缺少参照区域数据，不要计算区位熵；说明缺少什么数据并写入 gaps。
- 明确区分"统计口径"与"代理指标"。quant_from_evidence 的结果只是结构代理，
  必须保留工具给出的 caveat。

方法要求：
1. 先用 evidence_search 查找产值/增加值/销售额等数值证据；
2. 选择合适算法并调用工具；
3. 解释结果时说明指标含义、取值范围与局限；
4. 每条定量结论引用对应 evidence_ids，并在 caveats 中记录口径风险。

除通用字段外，尽量填写 computed_metrics / caveats。"""


def build_fallback(
    spec: AgentSpec,
    observations: list[ToolObservation],
    context: AgentContext,
    task: ResearchTask,
) -> dict[str, Any]:
    metrics = metric_payloads(observations)
    items = observation_evidence(observations, context)
    claims = claims_from_items(items, max_claims=4)
    caveats: list[str] = []
    for observation in observations:
        if observation.tool.startswith("quant_") and observation.ok:
            caveat = observation.data.get("caveat")
            if caveat:
                caveats.append(str(caveat))
    if not metrics:
        caveats.append("没有足够的同口径数值证据，未完成定量计算。")
    summary = (
        f"完成 {len(metrics)} 项确定性计算。"
        if metrics
        else "未完成定量计算：数值证据不足。"
    )
    return {
        "summary": summary,
        "claims": claims,
        "gaps": [] if metrics else ["缺少可用于定量分析的数值证据（产值/增加值/销售额）"],
        "confidence": confidence_for(items, base=0.35) if metrics else 0.2,
        "metrics": {"computations": len(metrics)},
        "computed_metrics": metrics[:8],
        "caveats": list(dict.fromkeys(caveats))[:8],
    }


SPEC = AgentSpec(
    kind=AgentKind.QUANTITATIVE,
    name="定量分析师",
    description="区位熵、Shift-Share、HHI、CRn 等确定性产业定量计算",
    system_prompt=SYSTEM_PROMPT,
    tools=(
        "evidence_search",
        "evidence_summary",
        "quant_location_quotient",
        "quant_shift_share",
        "quant_hhi",
        "quant_cr_n",
        "quant_from_evidence",
    ),
    output_model=QuantFindings,
    fallback_calls=(
        {
            "tool": "evidence_search",
            "arguments": {"keywords": ["产值", "增加值", "销售额", "营业收入"], "limit": 20},
        },
        {
            "tool": "quant_from_evidence",
            "arguments": {"keywords": ["产值", "增加值"], "limit": 20},
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
