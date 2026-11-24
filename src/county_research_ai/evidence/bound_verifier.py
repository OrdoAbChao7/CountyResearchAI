"""Conservative report-line verification against the canonical evidence graph."""
from __future__ import annotations

import json
import re

from ..domain.research_contracts import EvidencePack, SourceDocument
from .claim_region import statistical_value_context
from .measure import canonical_reporting_period, local_reporting_period
from .numeric_support import numeric_context_matches
from .source_contract import meets_source_credibility_threshold
from .verifier import VerificationReport

_NUMBER_UNIT = re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)(\s*(?:亿元|万元|万亩|亩|万吨|吨|%|个|家|户|处|座|万人|人|平方公里|株|万株))")
_METRIC_ALIASES = {
    "地区生产总值": {"地区生产总值", "GDP"},
    "国内生产总值": {"国内生产总值", "GDP"},
    "宏观GDP": {"地区生产总值", "国内生产总值", "GDP"},
    "工业增加值": {"工业增加值", "规上工业增加值"},
    "规上工业增加值": {"工业增加值", "规上工业增加值"},
    "人口": {"人口", "常住人口", "户籍人口"},
    "常住人口": {"人口", "常住人口"},
    "产值": {"产值", "总产值", "产业产值"},
    "总产值": {"产值", "总产值", "产业产值"},
}


class EvidenceBoundVerifier:
    """Verify numeric report statements only when metric/value/region/source link agree."""

    def verify_markdown(
        self,
        markdown: str,
        evidence_packs: list[EvidencePack],
        *,
        county: str,
    ) -> tuple[str, VerificationReport]:
        report = VerificationReport()
        output: list[str] = []
        claims = [claim for pack in evidence_packs for claim in pack.selected_claims]
        chunks = {
            chunk.chunk_id: chunk
            for pack in evidence_packs
            for chunk in pack.selected_chunks
        }
        sources = {
            source_id: source
            for pack in evidence_packs
            for source_id, source in pack.source_map.items()
        }

        for line in markdown.splitlines():
            values = list(_NUMBER_UNIT.finditer(line))
            if not values or line.lstrip().startswith("```"):
                if not values:
                    annotated, verified, note = _audit_unquantified_line(
                        line, county, claims, chunks, sources
                    )
                    if verified:
                        report.verified_claims_count += 1
                    elif note:
                        report.unverified_claims_count += 1
                        report.uncertainty_notes.append(f"{note}: {line[:80]}")
                    output.append(annotated)
                else:
                    output.append(line)
                continue
            matched_links: list[str] = []
            line_has_unverified = False
            for match in values:
                citation = _find_numeric_citation(line, match, county, claims, chunks, sources)
                if citation:
                    matched_links.append(citation)
                    report.verified_claims_count += 1
                else:
                    line_has_unverified = True
                    report.unverified_claims_count += 1
                    report.uncertainty_notes.append(f"未找到匹配的指标、数值和来源证据: {line[:80]}")

            unique_links = list(dict.fromkeys(matched_links))
            missing_links = [link for link in unique_links if link not in line]
            if unique_links and not line_has_unverified:
                output.append(
                    line if not missing_links else f"{line} _[{'; '.join(missing_links)}]_"
                )
            elif matched_links:
                output.append(f"{line} _[存在未核实数值；匹配来源：{'; '.join(dict.fromkeys(matched_links))}]_")
            else:
                output.append(f"{line} _[注: 未找到匹配的指标、数值和来源证据]_ ")

        report.is_valid = report.unverified_claims_count == 0
        return "\n".join(output), report


def metric_aliases(metric: str) -> set[str]:
    """Expose canonical metric labels for focused downstream tests and adapters."""
    return _METRIC_ALIASES.get(metric, {metric})


def _reliable_source(source: SourceDocument | None) -> bool:
    return bool(source and source.canonical_url and meets_source_credibility_threshold(source.metadata))


def _audit_unquantified_line(line, county, claims, chunks, sources):
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "---", "```")):
        return line, False, ""
    if stripped.startswith("|") and re.fullmatch(r"[|\s:-]+", stripped):
        return line, False, ""
    if stripped.startswith("|"):
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        known_headers = {"年份", "年度", "指标", "单位", "数值", "地区", "指标名称"}
        metric_headers = {alias for aliases in _METRIC_ALIASES.values() for alias in aliases}
        if cells and all(cell in known_headers or cell in metric_headers for cell in cells):
            return line, False, ""
    visible_text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", stripped)
    visible_text = visible_text.replace("**", "").replace("__", "").replace("`", "")
    gap_markers = ("证据不足", "未找到", "待核实")
    inference_markers = ("不代表现有证据", "建议先", "建议优先")
    if any(marker in visible_text for marker in gap_markers):
        return (line if "[资料缺口]" in line else f"{line} _[资料缺口]_"), False, ""
    if any(marker in visible_text for marker in inference_markers):
        return (line if "[推断/建议]" in line else f"{line} _[推断/建议]_"), False, ""

    links = []
    for claim in claims:
        if not claim.statement or claim.statement not in visible_text:
            continue
        if county in visible_text and claim.region_id != county:
            continue
        for chunk_id in claim.evidence_chunk_ids:
            chunk = chunks.get(chunk_id)
            if chunk is None or chunk.document_id not in claim.source_ids or claim.statement not in chunk.text:
                continue
            source = sources.get(chunk.document_id)
            if _reliable_source(source):
                links.append(f"[支持事实：{source.source_title or source.doc_id}]({source.canonical_url})")
                break
    if links:
        return f"{line} _[{'; '.join(dict.fromkeys(links))}]_", True, ""
    note = "未找到匹配的县域事实 Claim/Chunk/Source" if county in visible_text else "未映射的事实/分析陈述"
    return f"{line} _[注: {note}]_", False, note


def _find_numeric_citation(line, match: re.Match[str], county, claims, chunks, sources):
    number, unit = match[1].replace(",", ""), match[2].strip()
    number_offset = match.start()
    observation = statistical_value_context(line, number_offset, match.end())
    if observation.retracted:
        return ""
    period = local_reporting_period(observation.statement, preceding=observation.preceding_clauses)
    metric_alias_occurrences = []
    all_aliases = {alias for aliases in _METRIC_ALIASES.values() for alias in aliases}
    for alias in all_aliases:
        start = 0
        while (position := line.find(alias, start)) >= 0:
            metric_alias_occurrences.append((abs(position - number_offset), position, alias))
            start = position + len(alias)
    closest_metric_distance = min((item[0] for item in metric_alias_occurrences), default=None)
    for claim in claims:
        aliases = metric_aliases(claim.metric_id)
        candidate_metric_distance = min(
            (distance for distance, _, alias in metric_alias_occurrences if alias in aliases),
            default=None,
        )
        caliber_aliases = metric_aliases(claim.statistical_caliber) if claim.statistical_caliber else set()
        if (
            claim.region_id != county
            or claim.value.replace(",", "") != number
            or claim.unit != unit
            or (claim.period and period != canonical_reporting_period(claim.period))
            or (claim.series_version and claim.series_version not in line)
            or (caliber_aliases and not any(alias in line for alias in caliber_aliases))
            or not claim.metric_id
            or not any(alias in line for alias in aliases)
            or (closest_metric_distance is not None and candidate_metric_distance != closest_metric_distance)
            or (
                claim.administrative_scope
                and any(scope in claim.administrative_scope for scope in ("全国", "全省", "全市"))
                and county not in claim.administrative_scope
            )
        ):
            continue
        for chunk_id in claim.evidence_chunk_ids:
            chunk = chunks.get(chunk_id)
            if (
                chunk is None
                or chunk.document_id not in claim.source_ids
                or county not in chunk.text
                or not any(alias in chunk.text for alias in aliases)
                or (caliber_aliases and not any(alias in chunk.text for alias in caliber_aliases))
            ):
                continue
            chunk_values = {
                (value.replace(",", ""), item_unit.strip())
                for value, item_unit in _NUMBER_UNIT.findall(chunk.text)
            }
            if (number, unit) not in chunk_values:
                continue
            source = sources.get(chunk.document_id)
            if source is None or not _reliable_source(source):
                continue
            if not numeric_context_matches(claim, chunk.text, title=source.source_title, url=source.canonical_url):
                continue
            quote = json.dumps(chunk.text[:160], ensure_ascii=False)
            return (
                f"[证据：{source.source_title or source.doc_id}]({source.canonical_url})"
                f"（片段 {chunk_id}，原文：{quote}）"
            )
    return ""
