"""数字孪生服务：引擎选择、能力声明与调用边界。"""
from __future__ import annotations

import logging
from typing import Any

from ...config import Settings, get_settings
from .baseline_engine import BaselineAccountingEngine
from .models import (
    SimulationEngine,
    SimulationEngineUnavailable,
    SimulationOutcome,
    SimulationRequest,
)

logger = logging.getLogger(__name__)


class DigitalTwinService:
    def __init__(
        self,
        *,
        engine: SimulationEngine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._engine = engine or self._build_engine(self._settings.simulation.engine)

    @staticmethod
    def _build_engine(name: str) -> SimulationEngine:
        normalized = (name or "baseline").strip().lower()
        if normalized in {"baseline", "accounting", "default"}:
            return BaselineAccountingEngine()
        if normalized == "mesa":
            # 明确边界：Mesa 引擎需要校准数据、Agent 行为规则与验证方案，
            # 当前仓库不提供未经验证的实现。
            raise SimulationEngineUnavailable(
                "Mesa 引擎尚未实现/校准。请使用 engine=baseline，"
                "或按 docs/roadmap/shining-stars.md 的接口补齐并注册。"
            )
        raise SimulationEngineUnavailable(f"unknown simulation engine: {name}")

    @property
    def engine(self) -> SimulationEngine:
        return self._engine

    def capabilities(self) -> dict[str, Any]:
        return {
            "enabled": self._settings.simulation.enabled,
            "engine": self._engine.name,
            "engine_version": self._engine.version,
            "model_type": "deterministic_accounting_baseline",
            "supported_variables": [
                "industrial_output",
                "employment",
                "enterprise_count",
                "productivity",
            ],
            "calibrated": False,
            "mesa_boundary": (
                "Mesa/ABM 仅预留 SimulationEngine 协议；当前不提供未校准的大规模模拟。"
            ),
            "max_horizon_years": 20,
        }

    def simulate(self, request: SimulationRequest) -> SimulationOutcome:
        if not self._settings.simulation.enabled:
            raise SimulationEngineUnavailable("simulation is disabled by configuration")
        if request.scenario.horizon_years > 20:
            raise ValueError("horizon_years must be <= 20")
        return self._engine.simulate(request)


__all__ = ["DigitalTwinService"]
