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
        ]

        if policy_docs:
            lines.append("**1. 主要产业规划与顶层设计文件**")
            for pd in policy_docs[:5]:
                lines.append(f"- {pd}")
            lines.append("")
        else:
            lines.append(f"- _注：检索材料中暂未检索到专属于{focus}的省级或县级专项政策全文。_")

        if policy_docs:
            lines.extend([
                "**2. 核心支持举措与制度供给**",
                "- 上述材料仅用于确认已公开的政策依据；具体财政、土地、品牌等措施须以原文条款为准。",
                "",
            ])
        else:
            lines.append("- 证据不足：当前材料未能支持对本地政策措施作具体判断。")

        md = "\n".join(lines)
        return PolicyAnalysisOutput(
            summary=(
                f"已关联 {len(policy_docs)} 项政策材料。"
                if policy_docs
                else "未找到可追溯的专项政策材料。"
            ),
            policy_documents=policy_docs,
            evidence_items=policy_evidence,
            markdown_content=md,
        )
