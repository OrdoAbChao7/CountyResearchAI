"""产业方向发现服务。

复用既有 ``LLMAnalyzer.discover_focus``；LLM 不可用时使用确定性的
文档关键词回退，而不是空结果。
"""
from __future__ import annotations

import logging
import re
from collections import Counter

from ..models import CountyInfo, DiscoveryCandidate, DiscoveryResult, RawDoc

logger = logging.getLogger(__name__)

_INDUSTRY_TERMS = [
    "竹产业", "茶产业", "脐橙", "柑橘", "稀土", "石墨", "新材料", "装备制造",
    "电子信息", "生物医药", "文旅", "旅游", "农产品加工", "食品加工", "纺织",
    "建材", "新能源", "数字经济", "物流", "康养", "酒", "陶瓷", "化工",
]
_FOCUS_PATTERN = re.compile(r"([一-龥]{2,8}(?:产业|加工|制造|种植|文旅|旅游))")


class DiscoveryService:
    """县域重点产业方向的发现与选择。"""

    def __init__(self, analyzer: object | None = None) -> None:
        self._analyzer = analyzer

    def discover(self, county: CountyInfo, docs: list[RawDoc]) -> DiscoveryResult:
        if self._analyzer is not None:
            try:
                result = self._analyzer.discover_focus(county=county, raw_docs=docs)  # type: ignore[attr-defined]
                if result.selected_focus or result.candidates:
                    return result
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM 产业方向发现失败，使用确定性回退 | err=%s", exc)
        return self.fallback_discover(docs)

    @staticmethod
    def fallback_discover(docs: list[RawDoc]) -> DiscoveryResult:
        text = "\n".join(f"{d.title} {d.snippet} {d.content[:500]}" for d in docs)
        counts: Counter[str] = Counter()
        evidence: dict[str, list[str]] = {}
        for term in _INDUSTRY_TERMS:
            n = text.count(term)
            if n:
                counts[term] += n
        for match in _FOCUS_PATTERN.findall(text):
            if match not in counts and len(match) <= 8:
                counts[match] += 1
        for term in counts:
            for doc in docs:
                if term in f"{doc.title}{doc.snippet}{doc.content}" and doc.url:
                    evidence.setdefault(term, []).append(doc.url)
                    break
        candidates = [
            DiscoveryCandidate(
                industry=term,
                confidence=min(0.9, 0.4 + count * 0.05),
                reason=f"检索材料中出现 {count} 次",
                evidence_urls=evidence.get(term, [])[:3],
                related_keywords=[term],
                supporting_documents=[],
            )
            for term, count in counts.most_common(5)
        ]
        selected = candidates[0].industry if candidates else ""
        return DiscoveryResult(
            candidates=candidates,
            selected_focus=selected,
            model="deterministic-fallback",
            tokens_used=0,
        )


__all__ = ["DiscoveryService"]
