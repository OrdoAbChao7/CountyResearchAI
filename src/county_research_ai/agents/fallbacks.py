"""确定性降级辅助：从工具观察与证据库生成结构化结论。

降级结论仍然只引用真实 Evidence ID；没有证据的内容只作为研究缺口出现。
"""
from __future__ import annotations

from collections.abc import Iterable

from ..models import EvidenceItem
from .base import AgentContext, ToolObservation

ECONOMIC_HINTS = ("产值", "GDP", "生产总值", "增长", "增加值", "财政", "收入", "占比")
INDUSTRY_HINTS = ("产业链", "龙头", "规上", "园区", "加工", "集群", "专精特新")
POLICY_HINTS = ("政策", "规划", "意见", "方案", "补贴", "扶持", "十四五")
INNOVATION_HINTS = ("专利", "研发", "技术", "科研", "创新", "院所", "实验室")
GEO_HINTS = ("园区", "开发区", "基地", "交通", "铁路", "高速", "土地", "资源")


def observation_evidence(
    observations: Iterable[ToolObservation], context: AgentContext
) -> list[EvidenceItem]:
    ids: list[str] = []
    for observation in observations:
        ids.extend(observation.evidence_ids)
    unique = list(dict.fromkeys(ids))
    return context.evidence.by_ids(unique)


def filter_items(items: list[EvidenceItem], hints: tuple[str, ...]) -> list[EvidenceItem]:
    selected = [
        item
        for item in items
        if any(h in item.claim or h in item.indicator_caliber for h in hints)
    ]
    return selected or items


def claims_from_items(
    items: list[EvidenceItem],
    *,
    max_claims: int = 6,
    confidence: float = 0.68,
) -> list[dict]:
    claims: list[dict] = []
    seen: set[str] = set()
    for item in sorted(items, key=lambda i: i.credibility_score, reverse=True):
        text = item.claim.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        claims.append(
            {
                "text": text,
                "evidence_ids": [item.id],
                "confidence": round(min(0.95, confidence * (0.8 + item.credibility_score / 2.5)), 3),
            }
        )
        if len(claims) >= max_claims:
            break
    return claims


def first_claim(items: list[EvidenceItem], *hints: str) -> str:
    """返回第一条命中关键词的证据原文（截断到 200 字）。"""
    for item in items:
        if any(hint in item.claim for hint in hints):
            return item.claim.strip()[:200]
    return ""


def evidence_rows(items: list[EvidenceItem], *, limit: int = 10) -> list[dict]:
    return [
        {
            "evidence_id": item.id,
            "claim": item.claim,
            "title": item.title,
            "url": item.url,
            "year": item.year,
            "credibility": item.credibility_score,
        }
        for item in items[:limit]
    ]


def graph_observations(observations: Iterable[ToolObservation]) -> list[ToolObservation]:
    return [
        o
        for o in observations
        if o.tool.startswith("graph_") and o.ok and o.data
    ]


def metric_payloads(observations: Iterable[ToolObservation]) -> list[dict]:
    metrics: list[dict] = []
    for observation in observations:
        if observation.tool.startswith("quant_") and observation.ok:
            metric = observation.data.get("metric")
            if isinstance(metric, dict):
                metrics.append(metric)
    return metrics


def summarize_graph(observations: Iterable[ToolObservation], *, max_items: int = 6) -> list[str]:
    lines: list[str] = []
    for observation in graph_observations(observations):
        answer = str(observation.data.get("answer", "")).strip()
        if answer:
            lines.append(answer[:240])
        if len(lines) >= max_items:
            break
    return lines


def build_gaps(items: list[EvidenceItem], *, required: tuple[str, ...] = ()) -> list[str]:
    gaps: list[str] = []
    text = " ".join(item.claim for item in items)
    for keyword in required:
        if keyword not in text:
            gaps.append(f"缺少「{keyword}」相关的直接证据")
    if len(items) < 3:
        gaps.append("可用证据条目较少，结论稳健性不足")
    return gaps


def confidence_for(items: list[EvidenceItem], *, base: float = 0.4) -> float:
    if not items:
        return 0.25
    avg = sum(item.credibility_score for item in items) / len(items)
    volume_bonus = min(0.15, len(items) * 0.02)
    return round(min(0.95, base + avg * 0.45 + volume_bonus), 3)


__all__ = [
    "ECONOMIC_HINTS",
    "GEO_HINTS",
    "INDUSTRY_HINTS",
    "INNOVATION_HINTS",
    "POLICY_HINTS",
    "build_gaps",
    "claims_from_items",
    "confidence_for",
    "evidence_rows",
    "filter_items",
    "first_claim",
    "graph_observations",
    "metric_payloads",
    "observation_evidence",
    "summarize_graph",
]
