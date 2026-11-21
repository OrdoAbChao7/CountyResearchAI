"""三颗星（Shining Stars）。

- Star A 产业链缺口雷达：确定性缺口识别 + 机会 Agent
- Star B 产业数字孪生：领域模型 + 引擎端口 + 基线引擎
- Star C 时序产业智能：as-of 查询、差异比较与版本模型
"""
from .digital_twin import DigitalTwinService, SimulationRequest
from .gap_radar import GapRadarService, OpportunityReport
from .temporal import TemporalDiff, TemporalQuery

__all__ = [
    "DigitalTwinService",
    "GapRadarService",
    "OpportunityReport",
    "SimulationRequest",
    "TemporalDiff",
    "TemporalQuery",
]
