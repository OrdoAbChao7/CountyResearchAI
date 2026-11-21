"""Star A: 产业链缺口雷达。

确定性缺口识别位于 ``services.opportunity_service``，Agent 层位于
``agents.opportunity``；这里作为产品能力入口统一导出。
"""
from ...domain.intelligence import (
    GapType,
    OpportunityCandidate,
    OpportunityReport,
    VerificationStatus,
)
from ...services.opportunity_service import GapRadarService

__all__ = [
    "GapRadarService",
    "GapType",
    "OpportunityCandidate",
    "OpportunityReport",
    "VerificationStatus",
]
