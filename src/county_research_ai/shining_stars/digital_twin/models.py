"""Star B: 产业数字孪生的领域模型与边界。

当前阶段只定义可验证的领域契约与一个确定性基线引擎。
真正的 Mesa/ABM 仿真必须建立在校准数据与明确假设之上，未经验证的
大型模拟器不作为本阶段的交付物。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator

from ...domain.intelligence import VerificationStatus


class SimulationVariable(str, Enum):
    INDUSTRIAL_OUTPUT = "industrial_output"  # 规上工业/产业产值（亿元）
    EMPLOYMENT = "employment"                # 从业人数
    ENTERPRISE_COUNT = "enterprise_count"    # 企业数量
    PRODUCTIVITY = "productivity"            # 人均产值（万元/人）


class BaselineProfile(BaseModel):
    """仿真基线：必须来自证据，而不是模型猜测。"""

    county: str
    industry: str
    output_yi: float = Field(gt=0, description="基期产值，亿元")
    growth_rate: float = Field(default=0.05, ge=-0.5, le=0.5)
    employment: int = Field(default=0, ge=0)
    enterprise_count: int = Field(default=0, ge=0)
    source_year: int | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.PENDING
    notes: list[str] = Field(default_factory=list)

    @field_validator("evidence_ids")
    @classmethod
    def _dedupe_evidence(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(i for i in value if i))


class ScenarioShock(BaseModel):
    """情景冲击。

    所有参数都是"可解释的杠杆"，不是对现实的政策效果承诺。
    """

    growth_delta_pp: float = Field(
        default=0.0, ge=-30, le=30, description="年均增速变化（百分点）"
    )
    investment_yi: float = Field(
        default=0.0, ge=0, description="新增产业投资（亿元，按年投入）"
    )
    investment_output_ratio: float = Field(
        default=1.0,
        ge=0,
        le=5,
        description="每 1 元投资形成的年产值（显式假设，默认 1.0）",
    )
    productivity_delta: float = Field(
        default=0.0, ge=-0.5, le=0.5, description="人均产值年变化率"
    )
    enterprise_growth_delta_pp: float = Field(
        default=0.0, ge=-20, le=20, description="企业数量年增速变化（百分点）"
    )


class SimulationScenario(BaseModel):
    name: str = "baseline"
    description: str = ""
    horizon_years: int = Field(default=5, ge=1, le=20)
    shocks: ScenarioShock = Field(default_factory=ScenarioShock)


class SimulationRequest(BaseModel):
    baseline: BaselineProfile
    scenario: SimulationScenario = Field(default_factory=SimulationScenario)


class SimulationAssumption(BaseModel):
    key: str
    description: str
    value: float | str


class YearProjection(BaseModel):
    year_index: int
    year: int | None = None
    output_yi: float
    growth_rate: float
    employment: int
    enterprise_count: int
    productivity_wan_per_person: float


class SimulationOutcome(BaseModel):
    county: str
    industry: str
    scenario: SimulationScenario
    baseline: BaselineProfile
    projections: list[YearProjection] = Field(default_factory=list)
    assumptions: list[SimulationAssumption] = Field(default_factory=list)
    model_type: str = "deterministic_accounting_baseline"
    model_version: str = "0.1"
    verification_status: VerificationStatus = VerificationStatus.INFERRED
    degraded: bool = False
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimulationEngine(Protocol):
    """仿真引擎端口。

    任何新引擎（Mesa、系统动力学、CGE）都必须实现该协议，并通过
    ``engine_registry`` 注册；API 与应用层不依赖具体实现。
    """

    name: str
    version: str

    def simulate(self, request: SimulationRequest) -> SimulationOutcome: ...


class SimulationEngineUnavailable(RuntimeError):
    """请求的引擎未安装/未校准，明确拒绝而不是返回伪仿真结果。"""


__all__ = [
    "BaselineProfile",
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
