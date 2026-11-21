"""Critic Agent：证据审计、覆盖度评估与补充检索建议。

Critic 不负责写报告，也不直接改变其他 Agent 的结论；它只输出结构化审计结果，
由 Supervisor / 路由决定是否进入补充研究轮次。
"""
from __future__ import annotations

import logging
from typing import Any

from ...domain.intelligence import (
    AgentKind,
    AgentResult,
    CritiqueFinding,
    CritiqueReport,
)
from ...llm.structured import parse_json_object
from ..base import AgentContext, AgentSpec, ToolObservation

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是县域产业研究团队的首席证据审计员（Critic）。

职责：
- 审计其他 Agent 的结论是否被证据支持，找出无证据、弱证据、口径冲突、推断当事实的问题。
- 评估研究覆盖度：宏观、产业、企业、政策、创新、地理、定量等维度是否都有结论。
- 指出仍缺失的关键信息，并提出可执行的补充检索查询。
- 你不负责撰写报告，也不替其他 Agent 补充结论。

审计规则：
1. 一条结论若没有 evidence_ids，或引用的 Evidence ID 不存在，视为 unsupported（high）。
2. 只有弱来源（可信度低、非官方转载）支撑的关键数字，视为 weak_source。
3. 把 inferred/pending 的图谱关系写成确定事实，视为 overclaim。
4. 不同证据数字冲突且未说明，视为 conflict。
5. 覆盖度不足或关键维度缺失，视为 gap。
6. 不得为了让报告"看起来完整"而判定充分；宁可指出缺口。

只输出一个 JSON 对象：
{
  "is_sufficient": bool,
  "coverage": 0-1,
  "findings": [{"kind": "...", "description": "...", "severity": "high|medium|low",
                "agent": "...", "evidence_ids": [], "followup_queries": []}],
  "followup_queries": ["..."],
  "reasoning": "..."
}
followup_queries 必须是可直接用于搜索的具体查询（包含县域与产业关键词），最多 4 条。"""

SPEC = AgentSpec(
    kind=AgentKind.CRITIC,
    name="证据审计员",
    description="审计结论的证据支撑、覆盖度与冲突，提出补充检索",
    system_prompt=SYSTEM_PROMPT,
    tools=("evidence_search", "evidence_summary", "graph_evidence_trace"),
    output_model=CritiqueReport,
    max_steps=2,
    max_llm_calls=1,
)

_AGENT_LABELS = {
    AgentKind.MACRO: "宏观",
    AgentKind.INDUSTRY: "产业",
    AgentKind.ENTERPRISE: "企业",
    AgentKind.POLICY: "政策",
    AgentKind.INNOVATION: "创新",
    AgentKind.GEO: "地理",
    AgentKind.QUANTITATIVE: "定量",
    AgentKind.OPPORTUNITY: "机会",
}


class CriticAgent:
    """LLM 审计 + 确定性证据校验的混合 Critic。"""

    def __init__(self, llm: Any, tools: Any) -> None:
        self.spec = SPEC
        self._llm = llm
        self._tools = tools

    def review(
        self,
        context: AgentContext,
        results: list[AgentResult],
        *,
        round_no: int = 1,
        max_followups: int = 4,
    ) -> CritiqueReport:
        audit = self._deterministic_audit(context, results, round_no=round_no)
        if self._llm is None:
            audit.followup_queries = audit.followup_queries[:max_followups]
            return audit
        try:
            refined = self._llm_review(context, results, audit, round_no=round_no)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Critic LLM 审计失败，使用确定性审计 | err=%s", exc)
            refined = None
        report = refined or audit
        # 安全护栏：不允许多轮把"无证据结论"判为充分
        if audit.unsupported_claims > 0 or audit.coverage < 0.5:
            report.is_sufficient = False
        report.audited_claims = max(report.audited_claims, audit.audited_claims)
        report.unsupported_claims = max(report.unsupported_claims, audit.unsupported_claims)
        if not report.followup_queries:
            report.followup_queries = audit.followup_queries
        report.followup_queries = list(dict.fromkeys(report.followup_queries))[:max_followups]
        report.round = round_no
        return report

    # ---- 确定性审计 ----

    def _deterministic_audit(
        self, context: AgentContext, results: list[AgentResult], *, round_no: int
    ) -> CritiqueReport:
        findings: list[CritiqueFinding] = []
        total = 0
        unsupported = 0
        supported = 0
        agents_with_claims: set[str] = set()
        for result in results:
            for claim in result.claims:
                total += 1
                agents_with_claims.add(result.agent.value)
                valid = [i for i in claim.evidence_ids if context.evidence.get(i) is not None]
                if not valid:
                    unsupported += 1
                    findings.append(
                        CritiqueFinding(
                            kind="unsupported_claim",
                            description=f"{_AGENT_LABELS.get(result.agent, result.agent.value)}"
                            f"结论缺少有效证据：{claim.text[:120]}",
                            severity="high",
                            agent=result.agent.value,
                            evidence_ids=claim.evidence_ids,
                        )
                    )
                elif len(valid) != len(claim.evidence_ids):
                    findings.append(
                        CritiqueFinding(
                            kind="invalid_evidence_ref",
                            description=f"结论引用了不存在的证据 ID：{claim.text[:100]}",
                            severity="high",
                            agent=result.agent.value,
                            evidence_ids=claim.evidence_ids,
                        )
                    )
                else:
                    supported += 1
                    weak = [
                        i
                        for i in valid
                        if (item := context.evidence.get(i)) is not None
                        and item.credibility_score < 0.4
                    ]
                    if weak:
                        findings.append(
                            CritiqueFinding(
                                kind="weak_source",
                                description=f"结论主要依赖低可信度来源：{claim.text[:100]}",
                                severity="low",
                                agent=result.agent.value,
                                evidence_ids=weak,
                                followup_queries=[
                                    f"{context.county} {context.focus or ''} {claim.text[:30]} 官方"
                                ],
                            )
                        )
            if result.degraded:
                findings.append(
                    CritiqueFinding(
                        kind="degraded_agent",
                        description=f"{result.agent.value} 以降级模式完成，结论稳定性较低"
                        + (f"（{result.error}）" if result.error else ""),
                        severity="medium",
                        agent=result.agent.value,
                    )
                )
            for gap in result.gaps[:3]:
                findings.append(
                    CritiqueFinding(
                        kind="gap",
                        description=f"{result.agent.value}: {gap[:160]}",
                        severity="medium" if result.agent != AgentKind.OPPORTUNITY else "low",
                        agent=result.agent.value,
                    )
                )

        required = {
            AgentKind.MACRO,
            AgentKind.INDUSTRY,
            AgentKind.ENTERPRISE,
        }
        missing_agents = [k for k in required if k.value not in agents_with_claims]
        if missing_agents:
            findings.append(
                CritiqueFinding(
                    kind="coverage_gap",
                    description="缺少关键维度结论：" + "、".join(k.value for k in missing_agents),
                    severity="high" if len(missing_agents) >= 2 else "medium",
                )
            )
        coverage = round(supported / total, 3) if total else 0.0
        if total >= 8 and coverage < 0.7:
            findings.append(
                CritiqueFinding(
                    kind="low_evidence_coverage",
                    description=f"仅 {coverage:.0%} 的结论有有效证据支撑",
                    severity="medium",
                )
            )
        if context.evidence.conflicts():
            findings.append(
                CritiqueFinding(
                    kind="conflict",
                    description=f"证据库存在 {len(context.evidence.conflicts())} 组数字/口径冲突，需人工复核",
                    severity="medium",
                )
            )
        followups = self._followups(context, results, findings)
        high = [f for f in findings if f.severity == "high"]
        is_sufficient = (
            total > 0
            and len(high) == 0
            and coverage >= 0.7
            and len(agents_with_claims) >= 3
            and len(context.evidence.all()) >= 5
        )
        return CritiqueReport(
            is_sufficient=is_sufficient,
            coverage=coverage,
            findings=findings[:20],
            followup_queries=followups,
            audited_claims=total,
            unsupported_claims=unsupported,
            round=round_no,
            reasoning=(
                f"确定性审计：{total} 条结论，{supported} 条有有效证据，"
                f"{unsupported} 条无有效证据；覆盖 Agent {len(agents_with_claims)} 个。"
            ),
        )

    def _followups(
        self,
        context: AgentContext,
        results: list[AgentResult],
        findings: list[CritiqueFinding],
    ) -> list[str]:
        queries: list[str] = []
        for finding in findings:
            queries.extend(finding.followup_queries)
        for result in results:
            for gap in result.gaps[:2]:
                if len(gap) > 60:
                    continue
                queries.append(f"{context.county} {context.focus or ''} {gap[:40]}")
        if not queries:
            queries = [
                f"{context.county} {context.focus or '产业'} 统计局 主导产业 产值",
                f"{context.county} {context.focus or '产业'} 产业链 配套企业",
            ]
        return list(dict.fromkeys(q.strip() for q in queries if q.strip()))[:6]

    # ---- LLM 审计 ----

    def _llm_review(
        self,
        context: AgentContext,
        results: list[AgentResult],
        audit: CritiqueReport,
        *,
        round_no: int,
    ) -> CritiqueReport | None:
        assert self._llm is not None
        blocks: list[str] = []
        char_budget = 9000
        used = 0
        for result in results:
            lines = [f"## Agent: {result.agent.value}（置信度 {result.confidence}）", result.summary[:500]]
            for claim in result.claims[:8]:
                evidence_text = " | ".join(
                    (item.claim[:120] if (item := context.evidence.get(i)) else f"未知证据 {i}")
                    for i in claim.evidence_ids
                )
                lines.append(f"- [{claim.verification_status.value}] {claim.text[:220]} ← {evidence_text}")
            for gap in result.gaps[:3]:
                lines.append(f"- GAP: {gap[:160]}")
            block = "\n".join(lines)
            if used + len(block) > char_budget:
                break
            blocks.append(block)
            used += len(block)
        user = (
            f"县域：{context.county}\n产业方向：{context.focus or '待发现'}\n"
            f"轮次：{round_no}\n证据库规模：{len(context.evidence.all())} 条\n"
            f"确定性审计基线：coverage={audit.coverage}, "
            f"unsupported={audit.unsupported_claims}, 结论数={audit.audited_claims}\n\n"
            + "\n\n".join(blocks)
            + "\n\n请按要求输出审计 JSON。"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        response = self._llm.chat(messages, temperature=0.0, max_tokens=1800)
        data = parse_json_object(response.content)
        findings: list[CritiqueFinding] = []
        known_ids = set(context.evidence.evidence_ids(limit=500))
        for raw in data.get("findings", []) or []:
            if not isinstance(raw, dict):
                continue
            try:
                finding = CritiqueFinding(
                    kind=str(raw.get("kind", "gap"))[:40],
                    description=str(raw.get("description", ""))[:400],
                    severity=str(raw.get("severity", "medium")),
                    agent=str(raw.get("agent", ""))[:40],
                    evidence_ids=[i for i in raw.get("evidence_ids", []) if i in known_ids],
                    followup_queries=[str(q)[:160] for q in raw.get("followup_queries", [])][:3],
                )
            except Exception:  # noqa: BLE001
                continue
            if finding.description:
                findings.append(finding)
        coverage = data.get("coverage")
        try:
            coverage_value = max(0.0, min(float(coverage), 1.0))
        except (TypeError, ValueError):
            coverage_value = audit.coverage
        followups = [
            str(q).strip()[:160]
            for q in data.get("followup_queries", []) or []
            if str(q).strip()
        ][:4]
        return CritiqueReport(
            is_sufficient=bool(data.get("is_sufficient", False)),
            coverage=coverage_value,
            findings=findings or audit.findings,
            followup_queries=followups or audit.followup_queries,
            audited_claims=audit.audited_claims,
            unsupported_claims=audit.unsupported_claims,
            round=round_no,
            reasoning=str(data.get("reasoning", ""))[:1500],
        )

    def tool_observations(self, context: AgentContext) -> list[ToolObservation]:
        """供调试/测试：执行一次证据摘要工具。"""
        return [self._tools.execute("evidence_summary", {"limit": 20}, context)]


def build(llm: Any, tools: Any) -> CriticAgent:
    return CriticAgent(llm, tools)


__all__ = ["CriticAgent", "SPEC", "SYSTEM_PROMPT", "build"]
