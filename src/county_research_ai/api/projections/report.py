"""Program-generated report projection from verified structured facts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...evidence.graph import EvidenceGraphStore, VerificationStatus, VerifiedFinding
from ..jobs import JobRecord
from .citations import build_citations, citation_numbers
from .common import truncate
from .models import (
    NarrativeSectionView,
    NarrativeView,
    ReportSectionView,
    ReportView,
    VerificationView,
)

_DISPUTE_STATUSES = {
    VerificationStatus.NEEDS_REVIEW,
    VerificationStatus.CONTRADICTED,
    VerificationStatus.NOT_COMPARABLE,
    VerificationStatus.OUTDATED,
}
_STATUS_LABELS = {
    "SUPPORTED": "已支持",
    "NEEDS_REVIEW": "冲突待复核",
    "CONTRADICTED": "被反证",
    "NOT_COMPARABLE": "不可比",
    "OUTDATED": "已被更新版本取代",
    "INSUFFICIENT": "证据不足",
}


def build_report_view(
    *,
    job: JobRecord,
    graph: EvidenceGraphStore,
    legacy_markdown: str | None = None,
) -> ReportView:
    findings = graph.list_findings(job.job_id)
    citations = build_citations(findings)
    numbers = citation_numbers(citations)
    deep = (job.result or {}).get("deep_research") or {}
    gaps = list(deep.get("gaps") or [])
    conflicts = list(deep.get("conflicts") or [])
    supported = [
        finding
        for finding in findings
        if finding.finding.status is VerificationStatus.SUPPORTED
    ]
    disputes = [
        finding for finding in findings if finding.finding.status in _DISPUTE_STATUSES
    ]
    claim_conflicts = [
        {
            "claim_id": finding.chain.claim.claim_id,
            "conflicting_claim_ids": list(
                (finding.chain.verification.deterministic_checks or {}).get(
                    "contradicting_supported_claims", []
                )
                or []
            ),
            "reason": (
                finding.chain.verification.reason
                if finding.chain.verification
                else ""
            ),
        }
        for finding in findings
        if finding.chain.verification
        and (finding.chain.verification.deterministic_checks or {}).get(
            "contradicting_supported_claims"
        )
    ]

    sections: list[ReportSectionView] = []
    summary_content = _summary_content(job, deep, findings)
    sections.append(
        ReportSectionView(
            id="summary",
            order=1,
            title="研究结论摘要",
            content=summary_content,
            citation_ids=[],
        )
    )
    verified_content, verified_ids = _verified_content(supported, numbers)
    sections.append(
        ReportSectionView(
            id="verified-facts",
            order=2,
            title="已核实事实",
            content=verified_content,
            sources=_section_sources(supported),
            citation_ids=verified_ids,
        )
    )
    disputes_content, dispute_ids = _disputes_content(disputes, conflicts, numbers)
    sections.append(
        ReportSectionView(
            id="disputes",
            order=3,
            title="冲突、反证与不可比",
            content=disputes_content,
            sources=_section_sources(disputes),
            citation_ids=dispute_ids,
        )
    )
    sections.append(
        ReportSectionView(
            id="gaps",
            order=4,
            title="证据缺口",
            content=_gaps_content(gaps),
            citation_ids=[],
        )
    )
    snapshots = graph.list_run_snapshots(job.job_id)
    sections.append(
        ReportSectionView(
            id="sources",
            order=5,
            title="来源快照",
            content=_sources_content(snapshots),
            sources=[snapshot.canonical_url for snapshot in snapshots if snapshot.canonical_url],
            citation_ids=[],
        )
    )
    sections.append(
        ReportSectionView(
            id="method",
            order=6,
            title="方法与限制",
            content=_method_content(job),
            citation_ids=[],
        )
    )

    markdown = _render_markdown(job, sections)
    narrative = _build_narrative(job, legacy_markdown)
    return ReportView(
        run_id=job.job_id,
        county=job.county,
        focus=job.focus or job.contract.research_focus,
        mode=job.mode,
        generated_at=datetime.now(timezone.utc),
        sections=sections,
        citations=citations,
        conflicts=conflicts,
        claim_conflicts=claim_conflicts,
        gaps=gaps,
        verification=VerificationView(
            verified=len(supported),
            unverified=len(findings) - len(supported),
            total=len(findings),
            notes=_verification_notes(findings),
            per_section={
                "verified": len(supported),
                "disputes": len(disputes),
                "gaps": len(gaps),
            },
        ),
        narrative=narrative,
        markdown_available=bool(legacy_markdown),
        markdown=markdown,
    )


def _summary_content(
    job: JobRecord, deep: dict[str, Any], findings: list[VerifiedFinding]
) -> str:
    counts: dict[str, int] = {}
    for finding in findings:
        status = finding.finding.status.value
        counts[status] = counts.get(status, 0) + 1
    coverage = deep.get("coverage_rate")
    lines = [
        f"- 研究目标：{job.contract.objective}",
        f"- 地区：{'、'.join(job.contract.regions)}",
        f"- 模式：`{job.mode}`；运行模式：`{job.mode_label}`",
        f"- 运行结果：`{job.outcome.value if job.outcome else 'IN_PROGRESS'}`"
        + (f"（{job.outcome_reason}）" if job.outcome_reason else ""),
        f"- 结构化结论：{len(findings)} 条；其中已支持 {counts.get('SUPPORTED', 0)} 条，"
        f"冲突待复核 {counts.get('NEEDS_REVIEW', 0)} 条，"
        f"证据不足 {counts.get('INSUFFICIENT', 0)} 条",
        f"- 问题覆盖率：{coverage:.0%}" if isinstance(coverage, (int, float)) else "- 问题覆盖率：未记录",
        "- 本报告由程序根据本次运行的结构化事实生成；未通过确定性校验的结论不进入事实表。",
    ]
    return "\n".join(lines)


def _verified_content(
    supported: list[VerifiedFinding], numbers: dict[str, int]
) -> tuple[str, list[str]]:
    if not supported:
        return (
            "本次运行没有通过确定性校验的结构化事实，因此不生成数值结论。",
            [],
        )
    lines = [
        "| 引用 | 指标 | 数值 | 期间 | 结论 | 原文引文 | 来源 |",
        "| :---: | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    citation_ids: list[str] = []
    for finding in supported:
        claim = finding.chain.claim
        link = next(
            (
                item
                for item in finding.chain.links
                if item.edge.relation.value != "contradicts"
            ),
            None,
        )
        if link is None:
            continue
        number = numbers.get(claim.claim_id)
        citation_ids.append(claim.claim_id)
        lines.append(
            "| "
            + " | ".join(
                [
                    f"[{number}]" if number is not None else "—",
                    _cell(claim.metric_id or claim.measure_id or "未标指标"),
                    _cell(f"{claim.value}{claim.unit}".strip() or "—"),
                    _cell(claim.period or "未标期间"),
                    _cell(claim.statement),
                    _cell(truncate(link.span.quote, 120)),
                    _cell(f"[{link.snapshot.title or '来源'}]({link.snapshot.canonical_url})"),
                ]
            )
            + " |"
        )
    return "\n".join(lines), citation_ids


def _disputes_content(
    disputes: list[VerifiedFinding],
    conflicts: list[dict[str, Any]],
    numbers: dict[str, int],
) -> tuple[str, list[str]]:
    lines: list[str] = []
    if conflicts:
        lines.append("### 多来源数值冲突")
        lines.append("")
        for conflict in conflicts:
            lines.append(
                f"- **{conflict.get('indicator', '未标指标')}**"
                f"（{conflict.get('conflict_type', 'discrepancy')}）："
                f"{conflict.get('description', '')}"
            )
            suggestion = conflict.get("resolution_suggestion")
            if suggestion:
                lines.append(f"  - 核验建议：{suggestion}")
        lines.append("")
    if disputes:
        lines.append("### 未采信结论")
        lines.append("")
        citation_ids: list[str] = []
        for finding in disputes:
            claim = finding.chain.claim
            number = numbers.get(claim.claim_id)
            citation_ids.append(claim.claim_id)
            reason = (
                finding.chain.verification.reason
                if finding.chain.verification
                else ""
            )
            lines.append(
                f"- `{claim.claim_id}` {claim.statement} "
                f"（{_STATUS_LABELS.get(finding.finding.status.value, finding.finding.status.value)}"
                + (f"；{reason}" if reason else "")
                + (f"；引用 [{number}]" if number is not None else "")
                + "）"
            )
        return "\n".join(lines), citation_ids
    if not lines:
        return "本次运行未记录冲突、反证或不可比结论；这不代表来源之间不存在差异。", []
    return "\n".join(lines), []


def _gaps_content(gaps: list[dict[str, Any]]) -> str:
    if not gaps:
        return "本次运行未记录结构化证据缺口；这不代表现有证据已经充分。"
    lines = ["| 子问题 | 缺口 | 缺失方面 | 严重度 |", "| :--- | :--- | :--- | :--- |"]
    for gap in gaps:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(str(gap.get("question_id", ""))),
                    _cell(str(gap.get("description", ""))),
                    _cell(str(gap.get("missing_aspect", ""))),
                    _cell(str(gap.get("severity", ""))),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _sources_content(snapshots: list[Any]) -> str:
    if not snapshots:
        return "本次运行没有保存来源快照。"
    lines = ["| 来源 | URL | 类型 | 抓取状态 | 发布/观测时间 |", "| :--- | :--- | :--- | :--- | :--- |"]
    for snapshot in snapshots:
        observed = snapshot.observed_at.isoformat() if snapshot.observed_at else "未知"
        published = snapshot.published_at.isoformat() if snapshot.published_at else "未知"
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(snapshot.title or snapshot.snapshot_id),
                    _cell(snapshot.canonical_url or "（无 URL）"),
                    _cell(snapshot.source_type),
                    _cell(snapshot.fetch_status),
                    _cell(f"发布 {published} / 观测 {observed}"),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _method_content(job: JobRecord) -> str:
    return "\n".join(
        [
            "- 事实表只使用本次运行中通过确定性校验的结构化结论。",
            "- 校验覆盖引文偏移、内容哈希、数值、单位、期间、行政范围与统计口径；"
            "它不能证明语义改写等价，也不等同于人工事实核查。",
            "- 未通过校验的结论不进入事实表；冲突、不可比与证据不足的条目"
            "在对应章节中按状态标明。",
            f"- 当前运行模式为 `{job.mode_label}`；MOCK 数据仅用于验证流程，"
            "不代表真实检索或模型质量。",
            "- 叙述稿（如界面中提供）是旧版分析文本，仅作背景材料，不参与本报告事实表。",
        ]
    )


def _verification_notes(findings: list[VerifiedFinding]) -> list[str]:
    counts: dict[str, int] = {}
    for finding in findings:
        status = finding.finding.status.value
        counts[status] = counts.get(status, 0) + 1
    notes = [
        f"{status}: {counts[status]}"
        for status in _STATUS_LABELS
        if counts.get(status)
    ]
    notes.append("证据不足的结论不在事实表中复述。")
    return notes


def _section_sources(findings: list[VerifiedFinding]) -> list[str]:
    urls: list[str] = []
    for finding in findings:
        for link in finding.chain.links:
            if link.snapshot.canonical_url:
                urls.append(link.snapshot.canonical_url)
    return list(dict.fromkeys(urls))


def _build_narrative(
    job: JobRecord, legacy_markdown: str | None
) -> NarrativeView:
    stored = (job.result or {}).get("report") or {}
    provenance = stored.get("provenance") or (
        "native_sections" if job.mode == "snapshot" else "markdown_split"
    )
    sections: list[NarrativeSectionView] = []
    if provenance == "native_sections":
        for index, section in enumerate(stored.get("sections", []) or [], start=1):
            sections.append(
                NarrativeSectionView(
                    id=f"narrative-{index}",
                    order=int(section.get("order", index) or index),
                    title=str(section.get("title", "")),
                    content=str(section.get("content", "")),
                    sources=list(section.get("sources", []) or []),
                )
            )
    elif legacy_markdown:
        sections = split_markdown_sections(legacy_markdown)
    if provenance != "native_sections" and not sections:
        provenance = "markdown_split"
    return NarrativeView(
        provenance=provenance,  # type: ignore[arg-type]
        sections=sections,
        markdown_available=bool(legacy_markdown),
    )


def split_markdown_sections(markdown: str) -> list[NarrativeSectionView]:
    lines = markdown.splitlines()
    sections: list[NarrativeSectionView] = []
    current_title = "全文"
    current: list[str] = []
    started = False

    def flush() -> None:
        content = "\n".join(current).strip()
        if not started:
            content = "\n".join(
                line for line in content.splitlines() if not line.startswith("# ")
            ).strip()
            if not content:
                return
        sections.append(
            NarrativeSectionView(
                id=f"narrative-{len(sections) + 1}",
                order=len(sections) + 1,
                title=current_title,
                content=content,
            )
        )

    for line in lines:
        if line.startswith("## "):
            flush()
            current_title = line[3:].strip()
            current = []
            started = True
        else:
            current.append(line)
    flush()
    return [section for section in sections if section.content or section.title != "全文"]


def _render_markdown(job: JobRecord, sections: list[ReportSectionView]) -> str:
    heading = f"# {job.county}{job.focus or job.contract.research_focus}研究报告"
    lines = [
        heading,
        "",
        f"> 运行 `{job.job_id}` · 模式 `{job.mode}` · "
        f"生成方式：程序根据已验证结构化事实生成",
        "",
    ]
    for section in sections:
        lines.extend([f"## {section.title}", "", section.content, ""])
    return "\n".join(lines).rstrip() + "\n"


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


__all__ = ["build_report_view", "split_markdown_sections"]
