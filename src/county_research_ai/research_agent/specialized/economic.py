"""经济与统计数据专业研究智能体 (EconomicResearchAgent)。

聚焦：
1. 宏观经济与县域生产总值 (GDP)；
2. 重点产业总产值、规上工业产值、综合产值与增速；
3. 农业种植面积、工业产能等实物指标；
4. 统计公报时效性核验。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...evidence.store import EvidenceStore
from ...models import EvidenceItem


@dataclass
class EconomicAnalysisOutput:
    """经济专业分析输出。"""
    summary: str
    output_values: list[str] = field(default_factory=list)
    scale_metrics: list[str] = field(default_factory=list)
    recent_growth: str = ""
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    markdown_content: str = ""


class EconomicResearchAgent:
    """经济与统计公报分析师。"""

    def analyze(
        self,
        county: str,
        focus: str,
        evidence_store: EvidenceStore,
    ) -> EconomicAnalysisOutput:
        economic_evidence = evidence_store.get_by_topic("economic")

        output_values = []
        scale_metrics = []
        recent_years = set()

        for it in economic_evidence:
            if "产值" in it.indicator_caliber or "产值" in it.claim:
                output_values.append(it.claim)
            elif "面积" in it.indicator_caliber or "产量" in it.indicator_caliber or "面积" in it.claim:
                scale_metrics.append(it.claim)
            if it.year:
                recent_years.add(it.year)

        year_str = f"（涉及统计年份: {', '.join(sorted(recent_years))}）" if recent_years else ""

        lines = [
            f"### 一、{county}{focus}产业经济规模与产值统计",
            "",
            f"根据官方国民经济统计公报及行业公开数据{year_str}，核心经济规模指标如下：",
            "",
        ]

        if output_values:
            lines.append("**1. 产值与综合效益**")
            for ov in output_values[:5]:
                lines.append(f"- {ov}")
            lines.append("")
        else:
            lines.append(f"- _注：检索材料中暂未直接查得明确的{focus}最新年度产值统计数据。_")

        if scale_metrics:
            lines.append("**2. 实物规模与种植/产能体量**")
            for sm in scale_metrics[:5]:
                lines.append(f"- {sm}")
            lines.append("")

        md = "\n".join(lines)
        return EconomicAnalysisOutput(
            summary=f"{county}{focus}经济指标梳理完毕，包含 {len(output_values)} 项产值陈述与 {len(scale_metrics)} 项实物规模指标。",
            output_values=output_values,
            scale_metrics=scale_metrics,
            evidence_items=economic_evidence,
            markdown_content=md,
        )
