"""企业、产业链与市场竞争专业研究智能体 (IndustryResearchAgent)。

聚焦：
1. 骨干龙头企业、链主企业与专精特新中小企业；
2. 产业链上下游协同配套与空间园区分布；
3. 销售渠道体系、电商流通与国内外市场竞争力；
4. 发展面临的短板痛点与潜在风险挑战。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...evidence.store import EvidenceStore
from ...models import EvidenceItem


@dataclass
class IndustryAnalysisOutput:
    summary: str
    leading_enterprises: list[str] = field(default_factory=list)
    supply_chain_layout: str = ""
    market_channels: str = ""
    bottlenecks_and_risks: list[str] = field(default_factory=list)
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    markdown_content: str = ""


class IndustryResearchAgent:
    """产业链、企业生态与市场竞争分析师。"""

    def analyze(
        self,
        county: str,
        focus: str,
        evidence_store: EvidenceStore,
    ) -> IndustryAnalysisOutput:
        industry_evidence = evidence_store.get_by_topic("industry")
        risk_evidence = evidence_store.get_by_topic("risk")

        enterprises = []
        for it in industry_evidence:
            if "骨干企业" in it.indicator_caliber or "企业" in it.claim:
                enterprises.append(it.claim)

        bottlenecks = []
        for it in risk_evidence:
            bottlenecks.append(f"{it.claim}（依据: [{it.title}]({it.url})）")

        lines = [
            f"### 三、{county}{focus}产业链结构、龙头企业与竞争态势",
            "",
            "**1. 产业链分工与重点骨干企业**",
        ]

        if enterprises:
            for ent in enterprises[:6]:
                lines.append(f"- {ent}")
        else:
            lines.append("- _注：检索材料中暂未直接提取到该县明确标明的单家专精特新链主企业名单。_")

        lines.extend(["", "**2. 销售流通渠道与市场拓展**"])
        channel_evidence = [
            item for item in industry_evidence
            if any(term in item.claim for term in ("市场", "销售", "电商"))
        ]
        if channel_evidence:
            lines.extend(f"- {item.claim}（来源: [{item.title}]({item.url})）" for item in channel_evidence[:5])
        else:
            lines.append("- 证据不足：未找到可追溯材料说明本地销售渠道或市场格局。")
        lines.extend(["", "**3. 突出短板瓶颈与外部风险**"])

        for b in bottlenecks[:5]:
            lines.append(f"- {b}")
        if not bottlenecks:
            lines.append("- 证据不足：未找到可追溯材料支持具体瓶颈判断。")
        lines.append("")

        md = "\n".join(lines)
        return IndustryAnalysisOutput(
            summary=(
                f"已提取 {len(enterprises)} 家重点企业线索与 {len(bottlenecks)} 条风险材料。"
                if bottlenecks
                else f"已提取 {len(enterprises)} 家重点企业线索；当前材料未支持具体瓶颈判断。"
            ),
            leading_enterprises=enterprises,
            bottlenecks_and_risks=bottlenecks,
            evidence_items=industry_evidence + risk_evidence,
            markdown_content=md,
        )
