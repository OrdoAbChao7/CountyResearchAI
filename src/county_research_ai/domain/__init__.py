"""研究领域规则与稳定值对象。"""

from .modes import ResearchMode, normalize_mode, normalize_request
from .common import CountyInfo, ResearchRequest
from .evidence import DiscoveryCandidate, DiscoveryResult, ProcessedData, RawDoc
from .reports import ReportSection, ResearchReport
from .snapshot import AnalysisResult
from .rise_fall import (
    CountyRiseFallAnalysis, DeclineFactor, HistoricalPattern, IndustryLifecycle,
    RiseFactor, TimelineEvent,
)
from .long_history import (
    CountyLongHistoryAnalysis, GeoHistoricalFactor, HistoricalPeriod,
    LongHistoryPattern,
)

__all__ = [
    "AnalysisResult", "CountyInfo", "CountyLongHistoryAnalysis",
    "CountyRiseFallAnalysis", "DeclineFactor", "DiscoveryCandidate",
    "DiscoveryResult", "GeoHistoricalFactor", "HistoricalPattern",
    "HistoricalPeriod", "IndustryLifecycle", "LongHistoryPattern",
    "ProcessedData", "RawDoc", "ReportSection", "ResearchReport",
    "ResearchRequest", "RiseFactor", "TimelineEvent", "ResearchMode",
    "normalize_mode", "normalize_request",
]

__all__ = ["ResearchMode", "normalize_mode", "normalize_request"]
