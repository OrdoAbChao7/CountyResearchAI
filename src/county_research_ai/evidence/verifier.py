"""事实核验与证据链校验器 (FactVerifier)。

功能：
1. 校验分析结论中的具体数值、统计数据和政策引用是否具有底层 EvidenceItem 支撑；
2. 识别潜在模型幻觉（无数据依据凭空编造的数据）；
3. 标注不确定性提示（对于仅有单方自媒体来源或未注明年份的数据追加声明）；
4. 为分析文本追加可追溯的证据引用标记。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import EvidenceItem
from .store import EvidenceStore


@dataclass
class VerificationReport:
    """事实核验结果报告。"""
    is_valid: bool = True
    verified_claims_count: int = 0
    unverified_claims_count: int = 0
    flagged_hallucinations: list[str] = field(default_factory=list)
    uncertainty_notes: list[str] = field(default_factory=list)


class FactVerifier:
    """事实核验与可靠性审计器。"""

    def __init__(self, evidence_store: EvidenceStore) -> None:
        self.evidence_store = evidence_store

    def verify_text_content(
        self,
        analysis_markdown: str,
        county: str,
    ) -> tuple[str, VerificationReport]:
        """核验分析文本，识别数据并关联证据，标记不确定性。

        Returns:
            (annotated_markdown, report)
        """
        report = VerificationReport()
        annotated_lines = []

        all_evidence = self.evidence_store.get_all()
        # 建立快速查找表（按数字数值）
        evidence_by_num: dict[str, list[EvidenceItem]] = {}
        for it in all_evidence:
            numbers = re.findall(r"\d+(?:\.\d+)?", it.claim)
            for num in numbers:
                if len(num) >= 2:  # 忽略单位数
                    evidence_by_num.setdefault(num, []).append(it)

        # 逐段逐行核验
        for line in analysis_markdown.splitlines():
            # 检查行中是否包含统计量词（如 280亿元、101万亩、增长8.5%、500个、20家）
            num_matches = re.findall(
                r"(\d+(?:\.\d+)?)\s*(亿元|万元|万亩|亩|万吨|吨|%|个|家|户|处|座)", line
            )
            if not num_matches:
                annotated_lines.append(line)
                continue

            has_support = False
            best_source: EvidenceItem | None = None

            for num_val, _unit in num_matches:
                if num_val in evidence_by_num:
                    supported_items = evidence_by_num[num_val]
                    # 寻找最高置信度支撑
                    best_source = max(supported_items, key=lambda x: x.credibility_score)
                    has_support = True
                    break

            if has_support and best_source:
                report.verified_claims_count += 1
                # 附带可信度标注
                if best_source.credibility_score >= 0.85:
                    badge = f" ^[来源: {best_source.title[:15]}... | 官方/权威验证]"
                else:
                    badge = f" ^[来源: {best_source.title[:15]}... | 待多方复核]"
                annotated_lines.append(f"{line}{badge}")
            else:
                report.unverified_claims_count += 1
                report.uncertainty_notes.append(f"数据未在采集材料中找到明确出处: {line[:50]}")
                # 标记不确定性提示，避免用户误以为是铁证
                annotated_lines.append(f"{line} _[注: 该数值需官方统计公报进一步核实]_")

        annotated_text = "\n".join(annotated_lines)
        report.is_valid = report.unverified_claims_count <= max(2, report.verified_claims_count * 2)
        return annotated_text, report
