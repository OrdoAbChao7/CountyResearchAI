"""Decision-brief rendering from verified structured findings."""
from __future__ import annotations

from ..domain.outcomes import ResearchOutcome
from ..domain.research_contracts import ResearchContract
from ..evidence.graph import (
    EvidenceLink,
    SourceSnapshotRecord,
    VerificationStatus,
    VerifiedFinding,
)
from .contract_coverage import ContractQuestionResult
from .projections.questions import contract_question_lines


def _quote(text: str, limit: int = 240) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _finding_line(finding: VerifiedFinding, citation: EvidenceLink | None = None) -> str:
    claim = finding.chain.claim
    lines = [f"- `{claim.claim_id}` {claim.statement}"]
    for link in [citation] if citation is not None else finding.chain.links:
        source = link.snapshot
        origin = source.canonical_url or source.snapshot_id
        observed = source.observed_at.isoformat() if source.observed_at else "未知时间"
        lines.append(
            f"  - 证据 `{link.span.span_id}` · {origin} · 观测 {observed}"
        )
        lines.append(f"    > {_quote(link.span.quote)}")
    return "\n".join(lines)


def render_decision_brief(
    *,
    job_id: str,
    contract: ResearchContract,
    outcome: ResearchOutcome | None,
    outcome_reason: str,
    mode_label: str,
    findings: list[VerifiedFinding],
    sources: list[SourceSnapshotRecord],
    citation_links: dict[str, EvidenceLink] | None = None,
    contract_questions: list[ContractQuestionResult] | None = None,
) -> str:
    grouped: dict[VerificationStatus, list[VerifiedFinding]] = {}
    for item in findings:
        grouped.setdefault(item.finding.status, []).append(item)

    def section(status: VerificationStatus, title: str, *, body: str) -> list[str]:
        items = grouped.get(status, [])
        if not items:
            return []
        links = citation_links or {}
        return [f"## {title}（{len(items)}）", "", body, ""] + [
            _finding_line(item, links.get(item.finding.claim_id)) for item in items
        ] + [""]

    lines: list[str] = [
        f"# {contract.objective} — 决策简报",
        "",
        f"- 运行: `{job_id}`",
        f"- 完成状态: `{outcome.value if outcome else 'IN_PROGRESS'}`"
        + (f"（{outcome_reason}）" if outcome_reason else ""),
        f"- 模式: `{mode_label}`（MOCK 表示未调用任何外部 Provider）",
        "- 判定方式: 确定性证据校验（引文偏移/哈希/数值/单位/期间/口径），"
        "不是语义蕴含证明",
        f"- 地区: {'、'.join(contract.regions)}",
        "- 时间窗口: "
        + (
            f"{contract.date_window.start or '…'} ~ {contract.date_window.end or '…'}"
            if contract.date_window.is_set
            else "未指定"
        ),
        f"- 证据阈值: 独立来源 ≥ {contract.evidence_thresholds.min_independent_sources}，"
        f"支持结论 ≥ {contract.evidence_thresholds.min_supported_claims}，"
        f"支持率 ≥ {contract.evidence_thresholds.min_supported_ratio:.0%}",
        "",
    ]

    if contract_questions:
        lines.extend(["## 合同逐问证据", "", *contract_question_lines(contract_questions), ""])

    if not findings:
        lines += ["## 未生成可采信结论", "", "本次运行没有产生可验证的结构化结论。", ""]
    else:
        lines += section(
            VerificationStatus.SUPPORTED,
            "已支持结论",
            body="以下结论可在引文中定位到数值与单位。",
        )
        lines += section(
            VerificationStatus.NEEDS_REVIEW,
            "冲突待复核",
            body="存在来源相互矛盾且双方均有可定位证据，未自动采信任何一方。",
        )
        lines += section(
            VerificationStatus.OUTDATED,
            "已被更新版本取代",
            body="存在更晚的系列版本，以下结论不作为当前判断依据。",
        )
        lines += section(
            VerificationStatus.NOT_COMPARABLE,
            "不可比结论",
            body="年份、口径、范围或单位不可比，未计入支持率。",
        )
        lines += section(
            VerificationStatus.CONTRADICTED,
            "被反证结论",
            body="以下结论被其自身证据或更强证据否定。",
        )

        withheld = grouped.get(VerificationStatus.INSUFFICIENT, [])
        if withheld:
            lines += [
                f"## 已隐去的无支持结论（{len(withheld)}）",
                "",
                "以下结论未能定位到可核验引文，未在简报中复述其内容。",
                "",
            ]
            lines += [
                f"- `{item.chain.claim.claim_id}` · {item.chain.claim.metric_id or '未知指标'}"
                " · 原因: 证据不足"
                for item in withheld
            ]
            lines += [""]

    lines += ["## 来源", ""]
    if sources:
        for source in sorted(sources, key=lambda item: item.snapshot_id):
            observed = source.observed_at.isoformat() if source.observed_at else "未知"
            published = (
                source.published_at.isoformat() if source.published_at else "未知"
            )
            label = source.title or source.snapshot_id
            url = source.canonical_url or "（无 URL）"
            lines.append(
                f"- {label} · {url} · 类型 {source.source_type} · "
                f"抓取状态 {source.fetch_status} · 观测 {observed} · 发布 {published}"
            )
    else:
        lines.append("- 无来源记录")
    lines += [
        "",
        "## 限制",
        "",
        "- MOCK 模式仅验证管线与证据链，不代表真实检索或模型质量。",
        "- 确定性校验不会判断语义改写是否等价；未命中的结论保持 INSUFFICIENT。",
        "- 本简报不构成投资、法律或证券建议。",
        "",
    ]
    return "\n".join(lines)
