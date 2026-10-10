"""产业政策与规划专业研究智能体 (PolicyResearchAgent)。

聚焦：
1. 十四五产业发展规划与地方政府工作报告；
2. 专项扶持政策、奖补资金、现代产业园政策；
3. 国家级及省级战略政策（如以竹代塑、乡村振兴先行区、国家重点产业链建设）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...evidence.store import EvidenceStore
from ...models import EvidenceItem


@dataclass
class PolicyAnalysisOutput:
    summary: str
    policy_documents: list[str] = field(default_factory=list)
    support_measures: list[str] = field(default_factory=list)
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    markdown_content: str = ""


class PolicyResearchAgent:
    """产业政策与政府规划分析师。"""

    def analyze(
        self,
        county: str,
        focus: str,
        evidence_store: EvidenceStore,
    ) -> PolicyAnalysisOutput:
        policy_evidence = evidence_store.get_by_topic("policy")

        policy_docs = []
        for it in policy_evidence:
            policy_docs.append(f"{it.claim}（来源: [{it.title}]({it.url})）")

        lines = [
            f"### 二、{county}{focus}产业政策扶持与规划蓝图",
            "",
            "党委政府在引导、扶持产业发展中发挥了关键体制机制保障作用：",
            "",
        ]

        if policy_docs:
            lines.append("**1. 主要产业规划与顶层设计文件**")
            for pd in policy_docs[:5]:
                lines.append(f"- {pd}")
            lines.append("")
        else:
            lines.append(f"- _注：检索材料中暂未检索到专属于{focus}的省级或县级专项政策全文。_")

        lines.extend([
            "**2. 核心支持举措与制度供给**",
            "- 加强财政资金扶持与专项补贴，重点向科技创新、绿色转型与链主培育倾斜；",
            "- 优化产业用地、用林与环评审批要素保障，建设标准化产业集聚示范园；",
            "- 强化区域公共品牌保护与知识产权维权机制，提升产业区域影响力。",
            "",
        ])

        md = "\n".join(lines)
        return PolicyAnalysisOutput(
            summary=f"已梳理 {len(policy_docs)} 项重点政策规划与配套要素支持措施。",
            policy_documents=policy_docs,
            evidence_items=policy_evidence,
            markdown_content=md,
        )
