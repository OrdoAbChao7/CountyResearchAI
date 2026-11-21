"""确定性产业定量分析。

**所有数学计算都在 Python 中完成**，LLM 只负责理解问题、选择算法和解释结果。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class QuantResult:
    metric: str
    value: float
    unit: str = ""
    inputs: dict[str, float] = field(default_factory=dict)
    interpretation: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "value": round(self.value, 6),
            "unit": self.unit,
            "inputs": self.inputs,
            "interpretation": self.interpretation,
            "warnings": self.warnings,
        }


class QuantService:
    """区位熵、Shift-Share、HHI 等确定性算法。"""

    # ---- 区位熵 ----

    @staticmethod
    def location_quotient(
        local_industry: float,
        local_total: float,
        reference_industry: float,
        reference_total: float,
        *,
        industry_name: str = "",
        region_name: str = "",
    ) -> QuantResult:
        """LQ = (e_i / e) / (E_i / E)。

        LQ > 1 表示该产业在本地区相对专业化；< 1 表示相对不足。
        """
        for name, value in (
            ("local_industry", local_industry),
            ("local_total", local_total),
            ("reference_industry", reference_industry),
            ("reference_total", reference_total),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if local_total <= 0 or reference_total <= 0 or reference_industry <= 0:
            raise ValueError("denominators and reference_industry must be positive")
        local_share = local_industry / local_total
        ref_share = reference_industry / reference_total
        lq = local_share / ref_share
        if lq >= 1.5:
            interp = f"{region_name}{industry_name}具有显著专业化优势（LQ={lq:.2f}≥1.5）"
        elif lq >= 1.0:
            interp = f"{region_name}{industry_name}具备一定专业化基础（LQ={lq:.2f}）"
        else:
            interp = f"{region_name}{industry_name}本地专业化不足（LQ={lq:.2f}<1）"
        return QuantResult(
            metric="location_quotient",
            value=lq,
            inputs={
                "local_industry": local_industry,
                "local_total": local_total,
                "reference_industry": reference_industry,
                "reference_total": reference_total,
            },
            interpretation=interp,
        )

    # ---- Shift-Share ----

    @staticmethod
    def shift_share(
        local_start: float,
        local_end: float,
        reference_start: float,
        reference_end: float,
        *,
        reference_industry_start: float | None = None,
        reference_industry_end: float | None = None,
        industry_name: str = "",
    ) -> dict:
        """三因素 Shift-Share 分解。

        RS（区域增长分量）= local_start * g
        PS（产业结构分量）= local_start * (g_i - g)
        DS（竞争力分量）= local_start * (g_local - g_i)
        其中 g 为参照区总体增速，g_i 为参照区该产业增速，g_local 为本地该产业增速。

        没有参照区该产业数据时，g_i 退化为 g（PS=0），并在
        ``industry_growth_source`` 中明确标注，避免把缺失数据伪装成结构效应。
        """
        if local_start <= 0 or reference_start <= 0:
            raise ValueError("local_start and reference_start must be positive")
        g = (reference_end - reference_start) / reference_start
        if reference_industry_start and reference_industry_start > 0:
            g_i = (reference_industry_end - reference_industry_start) / reference_industry_start  # type: ignore[operator]
            growth_source = "reference_industry"
        else:
            g_i = g
            growth_source = "reference_total_proxy"
        g_local = (local_end - local_start) / local_start
        rs = local_start * g
        ps = local_start * (g_i - g)
        ds = local_start * (g_local - g_i)
        return {
            "metric": "shift_share",
            "industry": industry_name,
            "regional_share": round(rs, 6),
            "structural_share": round(ps, 6),
            "competitive_share": round(ds, 6),
            "total_change": round(local_end - local_start, 6),
            "reference_growth": round(g, 6),
            "industry_growth": round(g_i, 6),
            "industry_growth_source": growth_source,
            "local_growth": round(g_local, 6),
            "interpretation": (
                f"{industry_name}总变动 {local_end - local_start:.2f}，其中区域增长 {rs:.2f}、"
                f"结构效应 {ps:.2f}、竞争力效应 {ds:.2f}"
                + (
                    "（缺少参照区行业数据，结构效应按总体增速代理，仅供参考）"
                    if growth_source == "reference_total_proxy"
                    else ""
                )
            ),
        }

    # ---- HHI ----

    @staticmethod
    def hhi(shares: list[float], *, normalize: bool = False) -> QuantResult:
        """赫芬达尔—赫希曼指数。

        Args:
            shares: 各主体市场份额（0-1 或百分比均可，内部按合计归一）。
            normalize: 是否输出 0-1 归一化 HHI。
        """
        values = [float(s) for s in shares if s is not None]
        if not values or any(v < 0 for v in values):
            raise ValueError("shares must be a non-empty list of non-negative values")
        total = sum(values)
        if total <= 0:
            raise ValueError("sum of shares must be positive")
        norm = [v / total for v in values]
        raw = sum(v * v for v in norm)
        value = (raw - 1 / len(norm)) / (1 - 1 / len(norm)) if normalize and len(norm) > 1 else raw
        if raw < 0.15:
            interp = "市场高度分散（HHI<0.15）"
        elif raw < 0.25:
            interp = "市场中度集中（0.15≤HHI<0.25）"
        else:
            interp = "市场高度集中（HHI≥0.25）"
        warnings = []
        if any(v == 0 for v in values):
            warnings.append("存在份额为 0 的主体，已保留在其市场结构计数中")
        return QuantResult(
            metric="hhi",
            value=value,
            inputs={"shares": values, "count": float(len(values))},
            interpretation=interp,
            warnings=warnings,
        )

    # ---- 集中度辅助 ----

    @staticmethod
    def cr_n(shares: list[float], n: int = 4) -> QuantResult:
        """CRn:前 n 位主体市场份额之和。"""
        if n < 1:
            raise ValueError("n must be >= 1")
        values = sorted((float(s) for s in shares if s is not None), reverse=True)
        total = sum(values)
        if total <= 0:
            raise ValueError("sum of shares must be positive")
        value = sum(values[:n]) / total
        return QuantResult(
            metric=f"cr_{n}",
            value=value,
            inputs={"shares": values, "n": float(n)},
            interpretation=f"前 {n} 位主体合计份额 {value:.2%}",
        )

    # ---- 增长分解辅助 ----

    @staticmethod
    def cagr(start: float, end: float, years: float) -> QuantResult:
        if start <= 0 or years <= 0:
            raise ValueError("start and years must be positive")
        value = (end / start) ** (1 / years) - 1
        if math.isnan(value) or math.isinf(value):
            raise ValueError("cagr is undefined for the given inputs")
        return QuantResult(
            metric="cagr",
            value=value,
            inputs={"start": start, "end": end, "years": years},
            interpretation=f"年均复合增长率 {value:.2%}",
        )


__all__ = ["QuantResult", "QuantService"]
