"""报告 Agent：把结构化研究结果综合为可交付报告草稿。

LLM 只负责组织与表述；所有事实必须来自其他 Agent 的 claims / findings 与证据库。
没有 LLM 时使用确定性报告草稿（仍然完整、可追溯）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ...domain.intelligence import (
    AgentKind,
    AgentResult,
    CritiqueReport,
    OpportunityCandidate,
    ReportSectionV2,
)
from ...llm.structured import StructuredOutputError, parse_json_object
from ..base import AgentContext, AgentSpec
from ..findings import ReportDraft

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是县域产业研究团队的首席报告撰稿人。

职责：
- 把各专业 Agent 的结构化结论综合成一份面向政府/园区/投资机构的产业研究报告。
- 报告必须：先结论后论证；区分事实、推断与待核实；每个关键结论标注证据编号；
  明确指出研究缺口，不掩盖不确定性。
- 你不产生新事实。只能使用输入中给出的 claims、findings、opportunities 与证据；
  不得引入输入之外的数字、企业或政策。
- 机会部分必须标注为"分析推断"，不得写成已确定的招商结果。

输出 JSON：
{
  "summary": "...",
  "executive_summary": "...",
  "sections": [{"title": "...", "content": "...", "agent": "...", "evidence_ids": []}],
  "top_opportunities": [{"title": "...", "segment": "...", "description": "...", "score": 0.0,
                         "evidence_ids": []}],
  "gaps": ["..."],
  "confidence": 0.0
}
sections 按重要性排序，3-7 个；content 使用 Markdown。"""

SPEC = AgentSpec(
    kind=AgentKind.REPORT,
    name="首席报告撰稿人",
    description="综合多 Agent 结论与证据，生成结构化产业研究报告",
    system_prompt=SYSTEM_PROMPT,
    tools=("evidence_summary",),
    output_model=ReportDraft,
    max_steps=2,
    max_llm_calls=1,
)

AGENT_TITLES = {
    AgentKind.MACRO: "宏观经济与产业基本面",
    AgentKind.INDUSTRY: "产业结构与产业链",
    AgentKind.ENTERPRISE: "企业与竞争格局",
    AgentKind.POLICY: "政策环境",
    AgentKind.INNOVATION: "创新与技术能力",
    AgentKind.GEO: "空间载体与区位条件",
    AgentKind.QUANTITATIVE: "定量分析",
    AgentKind.OPPORTUNITY: "产业机会与补链方向",
    AgentKind.CRITIC: "证据审计",
    AgentKind.REPORT: "综合结论",
}


class ReportAgent:
    def __init__(self, llm: Any) -> None:
        self.spec = SPEC
        self._llm = llm

    def compose(
        self,
        context: AgentContext,
        results: list[AgentResult],
        *,
        research_question: str,
        critique: CritiqueReport | None = None,
        opportunities: list[OpportunityCandidate] | None = None,
    ) -> tuple[str, list[ReportSectionV2], list[dict[str, Any]], list[str], bool]:
        """返回 (executive_summary, sections, top_opportunities, gaps, degraded)。"""
        fallback = self._deterministic(context, results, research_question, critique, opportunities)
        if self._llm is None:
            return fallback
        try:
            composed = self._llm_compose(
                context, results, research_question, critique, opportunities
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("报告 Agent LLM 综合失败，使用确定性草稿 | err=%s", exc)
            return fallback
        if composed is None:
            return fallback
        return composed

    # ---- LLM ----

    def _llm_compose(
        self,
        context: AgentContext,
        results: list[AgentResult],
        research_question: str,
        critique: CritiqueReport | None,
        opportunities: list[OpportunityCandidate] | None,
    ) -> tuple[str, list[ReportSectionV2], list[dict[str, Any]], list[str], bool] | None:
        assert self._llm is not None
        blocks: list[str] = []
        used = 0
        for result in results:
            lines = [
                f"## {result.agent.value} | 置信度 {result.confidence} | "
                f"{'降级' if result.degraded else '正常'}",
                result.summary[:800],
            ]
            for claim in result.claims[:7]:
                ids = ",".join(claim.evidence_ids) or "无"
                lines.append(f"- [{claim.verification_status.value}] {claim.text[:220]} (证据: {ids})")
            if result.findings:
                lines.append("findings: " + json.dumps(result.findings, ensure_ascii=False)[:1200])
            block = "\n".join(lines)
            if used + len(block) > 12000:
                break
            blocks.append(block)
            used += len(block)
        opportunities_text = json.dumps(
            [op.model_dump(mode="json") for op in (opportunities or [])][:8],
            ensure_ascii=False,
        )[:3000]
        critique_text = (
            critique.model_dump_json()[:2000] if critique is not None else "（无审计报告）"
        )
        user = (
            f"研究问题：{research_question}\n县域：{context.county}\n"
            f"产业方向：{context.focus or '待发现'}\n\n"
            f"# 专业 Agent 结论\n" + "\n\n".join(blocks) +
            f"\n\n# 机会（分析推断）\n{opportunities_text}\n\n"
            f"# Critic 审计\n{critique_text}\n\n请输出报告 JSON。"
        )
        response = self._llm.chat(
            [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
            temperature=0.2,
            max_tokens=3000,
        )
        try:
            data = parse_json_object(response.content)
        except StructuredOutputError as exc:
            logger.warning("报告 JSON 解析失败：%s", exc)
            return None
        known_ids = set(context.evidence.evidence_ids(limit=500))
        sections: list[ReportSectionV2] = []
        for idx, raw in enumerate(data.get("sections", []) or []):
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title", "")).strip()
            content = str(raw.get("content", "")).strip()
            if not title or not content:
                continue
            sections.append(
                ReportSectionV2(
                    title=title[:80],
                    content=content[:6000],
                    order=idx,
                    agent=str(raw.get("agent", ""))[:30],
                    evidence_ids=[i for i in raw.get("evidence_ids", []) if i in known_ids],
                )
            )
        if not sections:
            return None
        top = [o for o in data.get("top_opportunities", []) or [] if isinstance(o, dict)][:5]
        gaps = [str(g)[:200] for g in data.get("gaps", []) or []][:10]
        return (
            str(data.get("executive_summary", "")).strip()[:3000] or "（模型未给出摘要）",
            sections,
            top,
            gaps,
            False,
        )

    # ---- 确定性草稿 ----

    @staticmethod
    def _deterministic(
        context: AgentContext,
        results: list[AgentResult],
        research_question: str,
        critique: CritiqueReport | None,
        opportunities: list[OpportunityCandidate] | None,
    ) -> tuple[str, list[ReportSectionV2], list[dict[str, Any]], list[str], bool]:
        sections: list[ReportSectionV2] = []
        gaps: list[str] = []
        order = 0
        for result in results:
            if result.agent in {AgentKind.CRITIC, AgentKind.REPORT}:
                continue
            title = AGENT_TITLES.get(result.agent, result.agent.value)
            lines = [result.summary.strip() or "（该 Agent 未给出摘要）"]
            if result.claims:
                lines.append("")
                lines.append("**主要结论**")
                for claim in result.claims[:6]:
                    refs = "、".join(claim.evidence_ids) or "无证据"
                    lines.append(f"- {claim.text}（证据：{refs}；置信度 {claim.confidence:.2f}）")
            findings = result.findings or {}
            extra_lines = _finding_lines(result.agent, findings)
            if extra_lines:
                lines.append("")
                lines.extend(extra_lines)
            if result.degraded:
                lines.append("")
                lines.append("> 该部分以降级模式生成，稳定性有限。")
            sections.append(
                ReportSectionV2(
                    title=title,
                    content="\n".join(lines),
                    order=order,
                    agent=result.agent.value,
                    evidence_ids=result.all_evidence_ids()[:40],
                )
            )
            order += 1
            gaps.extend(result.gaps[:3])

        if opportunities:
            lines = ["以下机会为基于知识图谱与证据的分析推断，需实地调研验证。", ""]
            for op in opportunities[:6]:
                refs = "、".join(op.evidence_ids) or "无直接证据"
                lines.append(
                    f"- **{op.title}**（评分 {op.score:.2f}，{op.verification_status.value}）："
                    f"{op.description} 证据：{refs}"
                )
                if op.suggested_actions:
                    lines.append("  建议：" + "；".join(op.suggested_actions[:3]))
            sections.append(
                ReportSectionV2(
                    title="产业机会与补链方向（推断）",
                    content="\n".join(lines),
                    order=order,
                    agent=AgentKind.OPPORTUNITY.value,
                    evidence_ids=[i for op in opportunities for i in op.evidence_ids][:40],
                )
            )
            order += 1

        if critique is not None:
            lines = [
                f"- 审计结论：{'充分' if critique.is_sufficient else '不充分'}",
                f"- 证据覆盖率：{critique.coverage:.0%}",
                f"- 审计结论数：{critique.audited_claims}；无有效证据：{critique.unsupported_claims}",
            ]
            for finding in critique.findings[:6]:
                lines.append(f"- [{finding.severity}] {finding.description}")
            sections.append(
                ReportSectionV2(
                    title="证据审计与不确定性",
                    content="\n".join(lines),
                    order=order,
                    agent=AgentKind.CRITIC.value,
                )
            )
            order += 1
            gaps.extend(f.description for f in critique.findings if f.severity == "high")

        if not results:
            sections.append(
                ReportSectionV2(
                    title="研究说明",
                    content="本次运行没有产生任何专业 Agent 结论。",
                    order=0,
                )
            )
        top_claims = [c for r in results for c in r.claims if c.evidence_ids][:5]
        summary_lines = [
            f"围绕「{research_question}」，本次研究组织了 {len(results)} 个专业 Agent，",
            f"形成 {sum(len(r.claims) for r in results)} 条结论、"
            f"{len(context.evidence.all())} 条证据。",
        ]
        if critique is not None:
            summary_lines.append(
                f"证据审计覆盖率 {critique.coverage:.0%}，"
                + ("结论总体可用。" if critique.is_sufficient else "仍存在需要补充的证据缺口。")
            )
        if top_claims:
            summary_lines.append(
                "核心发现：" + "；".join(c.text[:60] for c in top_claims[:3]) + "。"
            )
        degraded = any(r.degraded for r in results)
        return (
            "".join(summary_lines),
            sections,
            [op.model_dump(mode="json") for op in (opportunities or [])[:5]],
            list(dict.fromkeys(g for g in gaps if g))[:12],
            degraded,
        )


def _finding_lines(agent: AgentKind, findings: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if agent == AgentKind.MACRO and findings.get("indicators"):
        lines.append("**关键指标证据**")
        for row in findings["indicators"][:5]:
            lines.append(
                f"- {str(row.get('claim', ''))[:160]}（{row.get('evidence_id', '')}）"
            )
    elif agent == AgentKind.INDUSTRY:
        if findings.get("segments"):
            lines.append("**产业链环节**：" + "、".join(map(str, findings["segments"][:12])))
        if findings.get("chain_structure"):
            lines.append("")
            lines.append(str(findings["chain_structure"])[:800])
    elif agent == AgentKind.ENTERPRISE and findings.get("enterprises"):
        lines.append("**企业线索**")
        for row in findings["enterprises"][:10]:
            refs = "、".join(row.get("evidence_ids", []) or []) or "待核实"
            lines.append(f"- {row.get('name', '')}（{refs}）")
    elif agent == AgentKind.POLICY and findings.get("policies"):
        lines.append("**政策文本**")
        for row in findings["policies"][:8]:
            refs = "、".join(row.get("evidence_ids", []) or []) or "待核实"
            lines.append(f"- {row.get('title', '')}（{refs}）")
        if findings.get("support_measures"):
            lines.append("")
            lines.append("**扶持措施**：" + "；".join(map(str, findings["support_measures"][:5])))
    elif agent == AgentKind.INNOVATION:
        for key, label in (("technologies", "技术"), ("patents", "专利"), ("institutions", "机构")):
            if findings.get(key):
                lines.append(f"**{label}线索**：" + "；".join(map(str, findings[key][:4])))
    elif agent == AgentKind.GEO and findings.get("parks"):
        lines.append("**园区/载体**")
        for row in findings["parks"][:8]:
            lines.append(f"- {row.get('name', '')}")
    elif agent == AgentKind.QUANTITATIVE and findings.get("computed_metrics"):
        lines.append("**计算结果**")
        for metric in findings["computed_metrics"][:6]:
            lines.append(
                f"- {metric.get('metric', '')}: {metric.get('value', '')} "
                f"（{metric.get('interpretation', '')}）"
            )
        if findings.get("caveats"):
            lines.append("")
            lines.append("**口径说明**：" + "；".join(map(str, findings["caveats"][:4])))
    elif agent == AgentKind.OPPORTUNITY:
        for key, label in (
            ("missing_segments", "缺失环节"),
            ("weak_segments", "弱配套环节"),
            ("external_dependencies", "外部依赖"),
        ):
            if findings.get(key):
                lines.append(f"**{label}**：" + "、".join(map(str, findings[key][:10])))
    return lines


def build(llm: Any) -> ReportAgent:
    return ReportAgent(llm)


__all__ = ["AGENT_TITLES", "ReportAgent", "SPEC", "SYSTEM_PROMPT", "build"]
