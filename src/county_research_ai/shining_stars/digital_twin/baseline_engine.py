"""确定性基线仿真引擎。

这是一个"可解释的会计外推"模型，不是经过校准的产业系统模型：
- 只外推产值、就业、企业数量与人均产值；
- 所有假设显式输出，便于审计与后续替换；
- 输出统一标记 INFERRED（模拟值不是事实）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from ...domain.intelligence import VerificationStatus
from .models import (
    SimulationAssumption,
    SimulationOutcome,
    SimulationRequest,
    YearProjection,
)


class BaselineAccountingEngine:
    name = "baseline"
    version = "0.1"

    def simulate(self, request: SimulationRequest) -> SimulationOutcome:
        baseline = request.baseline
        scenario = request.scenario
        shock = scenario.shocks
        years = scenario.horizon_years

        output = float(baseline.output_yi)
        growth = max(-0.5, min(0.5, baseline.growth_rate + shock.growth_delta_pp / 100))
        enterprise_growth = 0.03 + shock.enterprise_growth_delta_pp / 100
        enterprise_growth = max(-0.2, min(0.3, enterprise_growth))
        enterprises = float(baseline.enterprise_count or 0)
        employment = float(baseline.employment or 0)
        productivity = (
            output * 10000 / employment if employment > 0 else 0.0
        )  # 万元/人
        current_year = datetime.now(timezone.utc).year

        projections: list[YearProjection] = [
            YearProjection(
                year_index=0,
                year=baseline.source_year or current_year,
                output_yi=round(output, 4),
                growth_rate=round(growth, 4),
                employment=int(employment),
                enterprise_count=int(enterprises),
                productivity_wan_per_person=round(productivity, 4),
            )
        ]

        investment_output = shock.investment_yi * shock.investment_output_ratio
        for year in range(1, years + 1):
            output = output * (1 + growth) + investment_output
            productivity = productivity * (1 + shock.productivity_delta) if productivity else 0.0
            if productivity > 0:
                employment = output * 10000 / productivity
            enterprises = enterprises * (1 + enterprise_growth)
            projections.append(
                YearProjection(
                    year_index=year,
                    year=(baseline.source_year + year) if baseline.source_year else current_year + year,
                    output_yi=round(output, 4),
                    growth_rate=round(growth, 4),
                    employment=int(employment),
                    enterprise_count=int(enterprises),
                    productivity_wan_per_person=round(productivity, 4),
                )
            )

        notes = list(baseline.notes)
        degraded = False
        if not baseline.evidence_ids:
            degraded = True
            notes.append("基线缺少证据引用：仿真仅用于方法演示，不能作为决策依据。")
        if baseline.verification_status != VerificationStatus.VERIFIED:
            notes.append("基线状态不是 verified，结果只能作为情景参考。")

        assumptions = [
            SimulationAssumption(
                key="growth_rate",
                description="年均产值增速（基线增速 + 情景冲击）",
                value=round(growth, 4),
            ),
            SimulationAssumption(
                key="investment_output_ratio",
                description="每 1 亿元新增投资形成的年产值（显式假设）",
                value=shock.investment_output_ratio,
            ),
            SimulationAssumption(
                key="enterprise_growth",
                description="企业数量年增速（基线 3% + 情景冲击）",
                value=round(enterprise_growth, 4),
            ),
            SimulationAssumption(
                key="productivity_delta",
                description="人均产值年变化率",
                value=shock.productivity_delta,
            ),
            SimulationAssumption(
                key="no_price_or_policy_feedback",
                description="模型不包含价格、要素替代、政策反馈与外部冲击",
                value="limitation",
            ),
        ]
        return SimulationOutcome(
            county=baseline.county,
            industry=baseline.industry,
            scenario=scenario,
            baseline=baseline,
            projections=projections,
            assumptions=assumptions,
            model_type="deterministic_accounting_baseline",
            model_version=self.version,
            verification_status=VerificationStatus.INFERRED,
            degraded=degraded,
            notes=notes,
            metadata={
                "engine": self.name,
                "calibrated": False,
                "disclaimer": (
                    "基线会计外推仅用于情景讨论；正式决策需校准数据与经评审的"
                    "产业模型（Mesa/系统动力学/CGE）。"
                ),
            },
        )


__all__ = ["BaselineAccountingEngine"]
