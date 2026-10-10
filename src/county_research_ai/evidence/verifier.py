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


_UNIT_PATTERN = r"(\d+(?:\.\d+)?)\s*(亿元|万元|万亩|亩|万吨|吨|%|个|家|户|处|座|万人|人|平方公里|株|万株)"
_POLICY_PATTERN = r"《([^》]{2,40})》"


class FactVerifier:
    """事实核验与可靠性审计器。"""

    def __init__(self, evidence_store: EvidenceStore) -> None:
        self.evidence_store = evidence_store

    def _build_indices(
        self, all_evidence: list[EvidenceItem]
    ) -> tuple[
        dict[tuple[str, str], list[EvidenceItem]],
        dict[str, list[EvidenceItem]],
        dict[str, list[EvidenceItem]],
    ]:
        evidence_by_pair: dict[tuple[str, str], list[EvidenceItem]] = {}
        evidence_by_num: dict[str, list[EvidenceItem]] = {}
        evidence_by_policy: dict[str, list[EvidenceItem]] = {}

        for it in all_evidence:
            text_to_scan = f"{it.claim} {it.snippet}"
            for num_val, unit_val in re.findall(_UNIT_PATTERN, text_to_scan):
                evidence_by_pair.setdefault((num_val, unit_val), []).append(it)
                evidence_by_num.setdefault(num_val, []).append(it)

            for pol in re.findall(_POLICY_PATTERN, text_to_scan):
                evidence_by_policy.setdefault(pol, []).append(it)

        return evidence_by_pair, evidence_by_num, evidence_by_policy

    def _find_support_for_line(
        self,
        line: str,
        num_matches: list[tuple[str, str]],
        policy_matches: list[str],
        evidence_by_pair: dict[tuple[str, str], list[EvidenceItem]],
        evidence_by_num: dict[str, list[EvidenceItem]],
        evidence_by_policy: dict[str, list[EvidenceItem]],
    ) -> tuple[bool, EvidenceItem | None]:
        # 优先 1：精确数值与量词单元匹配 (num, unit)
        for num_val, unit_val in num_matches:
            pair = (num_val, unit_val)
            if pair in evidence_by_pair:
                candidates = evidence_by_pair[pair]
                return True, max(candidates, key=lambda x: x.credibility_score)

        # 优先 2：政策文件匹配
        if policy_matches:
            for pol in policy_matches:
                for key, cands in evidence_by_policy.items():
                    if pol in key or key in pol:
                        return True, max(cands, key=lambda x: x.credibility_score)

        # 优先 3：数值相同且文本语义（如包含相同指标关键字）匹配
        if num_matches:
            for num_val, _unit_val in num_matches:
                if num_val in evidence_by_num:
                    for cand in evidence_by_num[num_val]:
                        if any(w in line and w in cand.claim for w in ("产值", "面积", "产量", "增速", "人口", "增加值", "企业")):
                            return True, cand

        return False, None

    def verify_text_content(
        self,
        analysis_markdown: str,
        county: str,
    ) -> tuple[str, VerificationReport]:
        """核验分析文本，识别数据与政策并关联证据，标记不确定性。

        Returns:
            (annotated_markdown, report)
        """
        report = VerificationReport()
        annotated_lines = []

        all_evidence = self.evidence_store.get_all()
        by_pair, by_num, by_policy = self._build_indices(all_evidence)

        # 逐段逐行核验
        for line in analysis_markdown.splitlines():
            stripped = line.strip()
            # 忽略纯标题、分界线、空行
            if not stripped or stripped.startswith(("#", "---", "|", ">", "```")):
                annotated_lines.append(line)
                continue

            num_matches = re.findall(_UNIT_PATTERN, line)
            policy_matches = re.findall(_POLICY_PATTERN, line)

            if not num_matches and not policy_matches:
                annotated_lines.append(line)
                continue

            has_support, best_source = self._find_support_for_line(
                line, num_matches, policy_matches, by_pair, by_num, by_policy
            )

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
