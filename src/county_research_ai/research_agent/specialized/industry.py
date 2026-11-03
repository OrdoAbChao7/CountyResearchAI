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

        bottlenecks = [
            "要素成本与劳动力老龄化加剧，对传统粗放加工环节形成挤压；",
            "精深加工比例仍有提升空间，高附加值衍生品与终端品牌溢价能力不足；",
            "外部同质化竞争与市场价格周期波动风险增加。",
        ]
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

        lines.extend([
            "",
            "**2. 销售流通渠道与市场拓展**",
            "- 依托电商平台、产地直供展会与现代物流冷链体系，打通线上线下立体营销网络；",
            "- 推动初级产品向高附加值文创、深加工产品延伸，强化区域公共品牌溢价效应。",
            "",
            "**3. 突出短板瓶颈与外部风险**",
        ])

        for b in bottlenecks[:5]:
            lines.append(f"- {b}")
        lines.append("")

        md = "\n".join(lines)
        return IndustryAnalysisOutput(
            summary=f"已剖析产业链上下游及市场格局，包含 {len(enterprises)} 家重点企业线索与突出痛点风险。",
            leading_enterprises=enterprises,
            bottlenecks_and_risks=bottlenecks,
            evidence_items=industry_evidence + risk_evidence,
            markdown_content=md,
        )
