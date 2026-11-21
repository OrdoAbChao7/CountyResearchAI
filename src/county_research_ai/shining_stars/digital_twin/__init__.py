"""Star B: 产业数字孪生。

领域模型 + 引擎端口 + 确定性基线引擎。Mesa 等经校准的仿真引擎
通过 ``SimulationEngine`` 协议扩展，不在本阶段伪造。
"""
from .baseline_engine import BaselineAccountingEngine
from .models import (
    BaselineProfile,
    ScenarioShock,
    SimulationAssumption,
    SimulationEngine,
    SimulationEngineUnavailable,
    SimulationOutcome,
    SimulationRequest,
    SimulationScenario,
    SimulationVariable,
    YearProjection,
)
from .service import DigitalTwinService

__all__ = [
    "BaselineAccountingEngine",
    "BaselineProfile",
    "DigitalTwinService",
    "ScenarioShock",
    "SimulationAssumption",
    "SimulationEngine",
    "SimulationEngineUnavailable",
    "SimulationOutcome",
    "SimulationRequest",
    "SimulationScenario",
    "SimulationVariable",
    "YearProjection",
]
