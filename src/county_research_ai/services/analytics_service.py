"""分析服务:复用既有 LLM 产业分析器与历史/兴衰分析器。

新 Agent 架构不依赖固定 Workflow，但保留这些经过测试的分析能力，
供 Report Agent、Macro Agent 和历史专题工具按需调用。
"""
from __future__ import annotations

import logging

from ..domain.modes import normalize_mode
from ..models import (
    AnalysisResult,
    CountyInfo,
    CountyLongHistoryAnalysis,
    CountyRiseFallAnalysis,
    DiscoveryResult,
    ProcessedData,
    RawDoc,
)

logger = logging.getLogger(__name__)


class AnalyticsService:
    """对既有分析器的薄封装，统一输入输出。"""

    def __init__(
        self,
        *,
        snapshot_analyzer: object | None = None,
        rise_fall_analyzer: object | None = None,
        long_history_analyzer: object | None = None,
    ) -> None:
        self._snapshot = snapshot_analyzer
        self._rise_fall = rise_fall_analyzer
        self._long_history = long_history_analyzer

    @property
    def has_snapshot_analyzer(self) -> bool:
        return self._snapshot is not None

    def analyze_snapshot(
        self,
        county: CountyInfo,
        focus: str,
        processed: ProcessedData,
        *,
        tasks: list[str] | None = None,
    ) -> list[AnalysisResult]:
        if self._snapshot is None:
            return []
        return self._snapshot.analyze(county=county, focus=focus, data=processed, tasks=tasks)  # type: ignore[attr-defined]

    def generate_summary(
        self,
        county: CountyInfo,
        focus: str,
        analyses: list[AnalysisResult],
    ) -> str:
        if self._snapshot is None:
            return ""
        return self._snapshot.generate_summary(  # type: ignore[attr-defined]
            county=county, focus=focus, analyses=analyses
        )

    def discover_focus(self, county: CountyInfo, raw_docs: list[RawDoc]) -> DiscoveryResult | None:
        if self._snapshot is None:
            return None
        try:
            return self._snapshot.discover_focus(county=county, raw_docs=raw_docs)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("discover_focus 失败 | err=%s", exc)
            return None

    def analyze_mode(
        self,
        mode: str,
        county: CountyInfo,
        focus: str,
        processed: ProcessedData,
    ) -> CountyRiseFallAnalysis | CountyLongHistoryAnalysis | None:
        """保留 rise-fall / long-history 专题分析能力。"""
        normalized = normalize_mode(mode)
        if normalized == "rise-fall" and self._rise_fall is not None:
            return self._rise_fall.analyze(county=county, data=processed)  # type: ignore[attr-defined]
        if normalized == "long-history" and self._long_history is not None:
            return self._long_history.analyze(county=county, data=processed)  # type: ignore[attr-defined]
        return None


__all__ = ["AnalyticsService"]
