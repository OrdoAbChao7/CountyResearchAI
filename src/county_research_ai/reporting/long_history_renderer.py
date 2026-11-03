"""县域长周期兴衰史报告渲染器(long-history 模式)。

将 CountyLongHistoryAnalysis 渲染为 9 节固定结构 Markdown 报告。
"""
from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..exceptions import ConfigError
from ..models import CountyLongHistoryAnalysis, RawDoc

logger = logging.getLogger(__name__)

_DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# 长周期模型类型 → 中文标签
_PATTERN_LABELS: dict[str, str] = {
    "geo_corridor": "交通通道型(因驿道/河流/省界通道立县,交通线迁移则衰)",
    "resource_frontier": "资源开发型(因林/矿/垦殖设治,资源枯竭则萧条)",
    "agricultural_hinterland": "农业腹地型(传统粮棉油主产区,近代被替代)",
    "border_governance": "边地治理型(因军事/民族/治安/边界管理设县)",
    "commercial_market": "商贸市场型(因墟镇/集散/商路立县,现代物流替代则空心化)",
    "state_industry": "国家工业嵌入型(计划经济嵌入国营/三线/矿山,转制后萧条)",
    "migration_labor": "外出务工型(人多地少→劳力持续外流,本地缺资本缺人力)",
    "policy_reactivated": "政策再激活型(长期萧条后靠新时期政策再激活)",
    "tourism_reinvention": "文旅再造型(传统衰败后靠遗产/生态/民俗重新被发明)",
    "mixed": "混合型(两种以上模型叠加)",
    "unknown": "未归类",
}

# 与 rise_fall_renderer 共用的来源优先级
_SOURCE_TYPE_PRIORITY: dict[str, int] = {
    "government": 0,
    "research": 1,
    "company": 2,
    "news": 3,
    "social": 4,
    "unknown": 5,
}


class LongHistoryReportRenderer:
    """县域长周期兴衰史报告渲染器。"""

    def __init__(self, template_dir: str | Path | None = None) -> None:
        self._template_dir = Path(template_dir) if template_dir else _DEFAULT_TEMPLATE_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=select_autoescape(default=False),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def render(
        self,
        analysis: CountyLongHistoryAnalysis,
        raw_docs: list[RawDoc] | None = None,
    ) -> str:
        """渲染为 9 节固定 Markdown 报告。"""
        p = analysis.long_history_pattern
        periods = analysis.periods

        # 历史阶段表信息(供总论引用)
        period_count = len(periods)
        geo_count = len(analysis.geo_factors)

        # 从 periods / geo_factors 提取各阶段一句话(用于第九节结论摘要)
        geo_line = ""
        if analysis.geo_factors:
            impacts = [f.impact for f in analysis.geo_factors[:2] if f.impact]
            if impacts:
                geo_line = " / ".join(impacts)
        traditional_logic = periods[0].dominant_logic if periods else ""
        # 若传统阶段 summary 很短也可兜底
        if not traditional_logic and periods and periods[0].summary:
            traditional_logic = periods[0].summary[:60]
        # 后续阶段一句话: 若有对应 stage 用其 dominant_logic / summary 首句,否则资料不足
        modern_shock_var = ""
        state_effect = ""
        reform_key = ""
        for p in periods:
            name = p.name or ""
            if ("近代" in name or "民国" in name or "1911" in name or "1949" in name):
                modern_shock_var = p.dominant_logic or (p.summary[:60] if p.summary else "")
            elif ("计划" in name or "1949" in name or "1978" in name):
                state_effect = p.dominant_logic or (p.summary[:60] if p.summary else "")
            elif ("改革" in name or "开放" in name or "1978" in name or "2000" in name):
                reform_key = p.dominant_logic or (p.summary[:60] if p.summary else "")
        if not modern_shock_var:
            modern_shock_var = "(资料不足)"
        if not state_effect:
            state_effect = "(资料不足)"
        if not reform_key:
            reform_key = "(资料不足)"
        # 新世纪命运:用 contemporary_status 首句一行(避免把整段 Markdown 塞进 bullet)
        contemporary_fate = "(资料不足)"
        if analysis.contemporary_status and not analysis.contemporary_status.startswith("_"):
            # 取第一行非空文本(<= 80 字)
            first_line = ""
            for line in analysis.contemporary_status.splitlines():
                line = line.strip().lstrip("#").strip()
                if line:
                    first_line = line
                    break
            if first_line:
                contemporary_fate = first_line[:80] + ("..." if len(first_line) > 80 else "")

        # 数据来源(按可信度排序)
        sources = self._build_sources(raw_docs or [])

        context = {
            "county_display": analysis.county.display(),
            "generated_at": analysis.analyzed_at.strftime("%Y-%m-%d %H:%M UTC"),
            "summary": analysis.summary or "(执行摘要生成失败)",
            # 一、总论 + 八、模型
            "pattern_type": p.pattern_type,
            "pattern_label": _PATTERN_LABELS.get(p.pattern_type, p.pattern_type),
            "confidence": p.confidence,
            "dominant_variables": p.dominant_variables,
            "pattern_summary": p.summary,
            "pattern_evidence": p.evidence,
            # 二、地理因子
            "geo_factors": [f.model_dump() for f in analysis.geo_factors],
            # 三~七
            "traditional_economy": analysis.traditional_economy,
            "modern_shocks": analysis.modern_shocks,
            "state_period_reorganization": analysis.state_period_reorganization,
            "reform_period_transformation": analysis.reform_period_transformation,
            "contemporary_status": analysis.contemporary_status,
            # 九、结论(预格式化一行话)
            "geo_line": geo_line,
            "traditional_logic": traditional_logic,
            "modern_shock_var": modern_shock_var,
            "state_effect": state_effect,
            "reform_key": reform_key,
            "contemporary_fate": contemporary_fate,
            # 元数据
            "period_count": period_count,
            "geo_count": geo_count,
            # 数据来源
            "sources": sources,
        }

        try:
            template = self._env.get_template("long_history_report.md.j2")
            md = template.render(**context)
        except Exception as e:
            logger.error("长周期报告渲染失败 | err=%s", e, exc_info=True)
            raise ConfigError("长周期兴衰史报告渲染失败", context={"error": str(e)}) from e
        return md

    @staticmethod
    def _build_sources(raw_docs: list[RawDoc]) -> list[dict[str, str]]:
        seen: dict[str, dict[str, str]] = {}
        for doc in raw_docs:
            if not doc.url or doc.url in seen:
                continue
            seen[doc.url] = {
                "title": doc.title or "(无标题)",
                "url": doc.url,
                "domain_type": doc.domain_type,
                "credibility": doc.credibility_score,
            }
        items = list(seen.values())
        items.sort(
            key=lambda x: (
                _SOURCE_TYPE_PRIORITY.get(x["domain_type"], 5),
                -x["credibility"],
            )
        )
        return items
