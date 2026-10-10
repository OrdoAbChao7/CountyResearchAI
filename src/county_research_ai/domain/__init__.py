"""研究领域规则与稳定值对象。"""

from .common import CountyInfo, ResearchRequest
from .evidence import (
    DiscoveryCandidate,
    DiscoveryResult,
    EvidenceConflict,
    EvidenceGap,
    EvidenceItem,
    ProcessedData,
    QuestionTree,
    RawDoc,
    ReflectionResult,
    ResearchQuestion,
)
from .long_history import (
    GeoHistoricalFactor,
    HistoricalPeriod,
    LongHistoryPattern,
)
from .modes import ResearchMode, normalize_mode, normalize_request
from .reports import ReportSection, ResearchReport
from .rise_fall import (
    CountyRiseFallAnalysis,
    DeclineFactor,
    HistoricalPattern,
    IndustryLifecycle,
    RiseFactor,
    TimelineEvent,
)
from .snapshot import AnalysisResult

__all__ = [
    "AnalysisResult", "CountyInfo", "CountyLongHistoryAnalysis",
    "CountyRiseFallAnalysis", "DeclineFactor", "DiscoveryCandidate",
    "DiscoveryResult", "EvidenceConflict", "EvidenceGap", "EvidenceItem",
    "GeoHistoricalFactor", "HistoricalPattern",
    "HistoricalPeriod", "IndustryLifecycle", "LongHistoryPattern",
    "ProcessedData", "QuestionTree", "RawDoc", "ReflectionResult",
    "ReportSection", "ResearchQuestion", "ResearchReport",
    "ResearchRequest", "RiseFactor", "TimelineEvent", "ResearchMode",
    "normalize_mode", "normalize_request",
]
