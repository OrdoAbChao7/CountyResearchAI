"""Long-history report renderer regression tests."""
from __future__ import annotations

from county_research_ai.models import (
    CountyInfo,
    CountyLongHistoryAnalysis,
    HistoricalPeriod,
    LongHistoryPattern,
)
from county_research_ai.reporting.long_history_renderer import LongHistoryReportRenderer


def test_render_uses_long_history_pattern_after_period_summary() -> None:
    """A historical-period loop must not replace the pattern used by the template."""
    analysis = CountyLongHistoryAnalysis(
        county=CountyInfo(name="巴中"),
        periods=[
            HistoricalPeriod(
                name="传统时代",
                dominant_logic="依托农业与区域商贸维持县域生存",
            )
        ],
        long_history_pattern=LongHistoryPattern(
            pattern_type="agricultural_hinterland",
            summary="农业腹地型县域",
        ),
        summary="巴中长期受农业腹地结构影响。",
    )

    markdown = LongHistoryReportRenderer().render(analysis)

    assert "农业腹地型" in markdown
