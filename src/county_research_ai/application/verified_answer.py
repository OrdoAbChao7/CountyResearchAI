"""Deterministic Strategy D answer built from verified findings."""
from __future__ import annotations

from collections import Counter
from typing import Any

from ..evidence.graph import EvidenceGraphStore, VerificationStatus


def build_verified_answer(
    graph: EvidenceGraphStore,
    run_id: str,
    *,
    max_claims: int = 200,
) -> dict[str, Any]:
    """Render only run-scoped SUPPORTED findings, with source backlinks.

    This is an extractive, deterministic answer, not a fluent report. It exists
    so fact coverage can be measured without re-introducing unverified prose.
    The measure key supplies the subject that legacy fragments often omit.
    """
    claims = graph.list_run_claims(run_id)
    counts: Counter[str] = Counter()
    supported: list[dict[str, Any]] = []
    for claim in claims[:max_claims]:
        chain = graph.get_chain(claim.claim_id, run_id=run_id)
        status = (
            chain.verification.status
            if chain.verification is not None
            else VerificationStatus.INSUFFICIENT
        )
        counts[status.value] += 1
        if status is not VerificationStatus.SUPPORTED:
            continue
        link = chain.links[0] if chain.links else None
        supported.append(
            {
                "claim_id": claim.claim_id,
                "measure": claim.measure_id or claim.metric_id or "",
                "statement": claim.statement,
                "value": claim.value,
                "unit": claim.unit,
                "period": claim.period,
                "quote": link.span.quote if link is not None else "",
                "url": link.snapshot.canonical_url if link is not None else "",
            }
        )
    supported.sort(key=lambda item: (item["measure"], item["period"], item["statement"]))
    lines = ["# 证据校验后的结论", ""]
    if not supported:
        lines.append("本次运行没有通过确定性校验的结论。")
    for item in supported:
        measure = item["measure"] or "未标指标"
        lines.append(
            f"- {measure}：{item['statement']}"
            f"（{item['value']}{item['unit']}，{item['period']}）"
        )
        if item["url"]:
            lines.append(f"  - 来源：{item['url']}")
    return {
        "run_id": run_id,
        "text": "\n".join(lines),
        "supported_claims": supported,
        "supported_count": len(supported),
        "status_counts": dict(sorted(counts.items())),
        "generation": "deterministic_extractive_from_verified_findings",
    }


def supported_claim_ids(graph: EvidenceGraphStore, run_id: str) -> set[str]:
    return {
        item["claim_id"]
        for item in build_verified_answer(graph, run_id)["supported_claims"]
    }


__all__ = ["build_verified_answer", "supported_claim_ids"]
