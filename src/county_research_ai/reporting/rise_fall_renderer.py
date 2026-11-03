"""县域产业兴衰规律研究报告渲染器(rise-fall 模式)。

将 CountyRiseFallAnalysis 渲染为最终 Markdown 报告(9 节固定结构):
    # {县名}县域产业兴衰规律研究报告
    ## 执行摘要 / 一、县域基本画像 / 二、起家产业 / 三、兴起逻辑
    ## 四、壮大机制 / 五、关键拐点 / 六、衰落机制 / 七、人才流失分析
    ## 八、县域兴衰模型归纳 / 九、结论

设计原则(与 ReportRenderer 一致):
    - 渲染器只负责格式化输出,不调用 Storage
    - Pipeline 负责在 renderer 返回字符串后落盘
    - 报告拼接逻辑集中在本渲染器,不放在 pipeline.py
    - 模板使用 Jinja2,与 report.md.j2 共存于 templates/ 目录
"""
from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..exceptions import ConfigError
from ..models import CountyRiseFallAnalysis, RawDoc

logger = logging.getLogger(__name__)

# 模板目录:src/county_research_ai/reporting/templates/
_DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# 兴衰模型类型 → 中文标签
_PATTERN_LABELS: dict[str, str] = {
    "resource_curse": "资源诅咒型(资源起家→枯竭→衰退)",
    "policy_driven": "政策驱动型(红利期繁荣→政策退坡→转型)",
    "market_cycle": "市场周期型(随宏观周期起伏)",
    "industry_transfer": "产业转移型(承接→壮大→再转移出)",
    "talent_drain": "人才流失型(产业基础尚可但人力流失)",
    "path_lock": "路径锁定型(单一产业过度依赖)",
    "diversified_growth": "多元共生型(多产业协同,韧性较强)",
    "mixed": "混合型(多种模型叠加)",
    "unknown": "未归类",
}

# 生命周期阶段 → 中文标签
_STAGE_LABELS: dict[str, str] = {
    "origin": "起家期",
    "growth": "成长壮大期",
    "mature": "成熟期",
    "decline": "衰退期",
    "transition": "转型期",
    "unknown": "未判断",
}

# 来源类型排序权重(数字越小优先级越高)
_SOURCE_TYPE_PRIORITY: dict[str, int] = {
    "government": 0,
    "research": 1,
    "company": 2,
    "news": 3,
    "social": 4,
    "unknown": 5,
}


class RiseFallReportRenderer:
    """兴衰规律研究报告渲染器。

    Usage:
        renderer = RiseFallReportRenderer()
        md = renderer.render(analysis, raw_docs)
    """

    def __init__(self, template_dir: str | Path | None = None) -> None:
        """初始化渲染器。

        Args:
            template_dir: 模板目录路径;None 则使用默认 reporting/templates/
        """
        self._template_dir = Path(template_dir) if template_dir else _DEFAULT_TEMPLATE_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=select_autoescape(default=False),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        logger.debug("RiseFallReportRenderer 初始化 | template_dir=%s", self._template_dir)

    def render(
        self,
        analysis: CountyRiseFallAnalysis,
        raw_docs: list[RawDoc] | None = None,
    ) -> str:
        """渲染为 Markdown 字符串。

        Args:
            analysis: 兴衰规律研究结果
            raw_docs: 原始文档列表(用于生成"数据来源"章节,按可信度排序)

        Returns:
            Markdown 格式的字符串(9 节固定结构)
        """
        lc = analysis.lifecycle
        pattern = analysis.historical_pattern

        # 筛选壮大期事件(category=growth)
        growth_events = [e for e in lc.turning_points if e.category == "growth"]

        # 数据来源:按 domain_type 优先级排序
        sources = self._build_sources(raw_docs or [])

        # 预格式化结论行(避免模板内 {% if %} 与 trim_blocks 冲突导致换行丢失)
        origin_line = lc.origin_industry or "(未识别)"
        if lc.origin_period:
            origin_line += f"(主导期: {lc.origin_period})"
        rise_names = "、".join(f.name for f in analysis.rise_factors)
        rise_line = f"{len(analysis.rise_factors)} 项核心因子"
        if rise_names:
            rise_line += f"({rise_names})"
        decline_names = "、".join(f.name for f in analysis.decline_factors)
        decline_line = f"{len(analysis.decline_factors)} 项核心因子"
        if decline_names:
            decline_line += f"({decline_names})"

        context = {
            "county_display": analysis.county.display(),
            "county_province": analysis.county.province,
            "generated_at": analysis.analyzed_at.strftime("%Y-%m-%d %H:%M UTC"),
            "version": "0.2.0",
            "summary": analysis.summary or "(执行摘要生成失败)",
            # 一、基本画像
            "stage_label": _STAGE_LABELS.get(lc.stage, lc.stage),
            "growth_industries": lc.growth_industries,
            "current_industries": lc.current_industries,
            "turning_points": [e.model_dump() for e in lc.turning_points],
            "rise_factors": [f.model_dump() for f in analysis.rise_factors],
            "decline_factors": [f.model_dump() for f in analysis.decline_factors],
            # 二、起家产业
            "origin_industry": lc.origin_industry,
            "origin_period": lc.origin_period,
            "origin_reason": lc.origin_reason,
            # 四、壮大机制
            "growth_events": [e.model_dump() for e in growth_events],
            # 七、人才流失
            "talent_loss_reasons": analysis.talent_loss_reasons,
            # 八、兴衰模型
            "pattern_type": pattern.pattern_type,
            "pattern_label": _PATTERN_LABELS.get(
                pattern.pattern_type, pattern.pattern_type,
            ),
            "confidence": pattern.confidence,
            "pattern_summary": pattern.summary,
            "pattern_evidence": pattern.evidence,
            # 九、结论(预格式化行,避免模板换行问题)
            "origin_line": origin_line,
            "rise_line": rise_line,
            "decline_line": decline_line,
            # 数据来源
            "sources": sources,
        }

        try:
            template = self._env.get_template("rise_fall_report.md.j2")
            md = template.render(**context)
        except Exception as e:
            logger.error("兴衰报告渲染失败 | err=%s", e, exc_info=True)
            raise ConfigError(
                "兴衰规律报告渲染失败",
                context={"error": str(e)},
            ) from e
        return md

    @staticmethod
    def _build_sources(raw_docs: list[RawDoc]) -> list[dict[str, str]]:
        """从 RawDoc 列表构建数据来源(去重 + 按可信度优先级排序)。

        来源优先级:政府官网/统计公报/地方志 > 发改委/工信局/统计局
                   > 上市公司公告/论文 > 主流媒体/行业协会 > 自媒体(仅弱参考)
        """
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
        # 按来源类型优先级排序,同类型按可信度降序
        items.sort(
            key=lambda x: (
                _SOURCE_TYPE_PRIORITY.get(x["domain_type"], 5),
                -x["credibility"],
            )
        )
        return items
