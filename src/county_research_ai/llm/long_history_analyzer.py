"""县域长周期兴衰史分析器(long-history 模式)。

针对县域做**数百年尺度的历史命运分析**,回答 9 个核心问题:
    1. 为什么这个县会形成?
    2. 最初依靠什么地理/资源/交通/行政功能存在?
    3. 传统时代主要经济来源是什么?
    4. 近代受到哪些战争/交通/市场变化影响?
    5. 计划经济时期是否被国营工业/水利/矿山等重新组织?
    6. 改革开放后靠什么发展?
    7. 新世纪为何再兴/停滞/边缘化?
    8. 决定该县长期命运的关键变量是什么?
    9. 属于哪一种县域长周期模型?

设计要点(与 RiseFallAnalyzer 保持一致):
    - 任务 → 模板映射:优先用 prompts/ 下模板,不存在用 fallback
    - 单任务失败不阻断整体(fail_fast=False 时降级为空)
    - JSON 解析容错:```json 代码块 / 纯 JSON / 文本嵌入
    - 长周期模型 10 类 + mixed
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import Settings, get_settings
from ..models import (
    CountyInfo,
    CountyLongHistoryAnalysis,
    GeoHistoricalFactor,
    HistoricalPeriod,
    LongHistoryPattern,
    ProcessedData,
)
from .base import LLMClient
from .client import OpenAICompatibleClient
from .prompt_loader import PromptLoader

logger = logging.getLogger(__name__)


def _safe_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]


def _parse_json_lenient(content: str) -> dict | list | None:
    """容错解析 LLM 返回的 JSON(支持数组/对象)。"""
    if not content:
        return None
    text = content.strip()
    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. 剥离 ```json ... ``` 代码块
    fence_match = re.search(r"```(?:json)?\s*([\[\{][\s\S]*?[\]\}])\s*```", text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass
    # 3. 文本中提取首个 {...} 或 [...] 对象
    obj_match = re.search(r"[\[\{][\s\S]*[\]\}]", text)
    if obj_match:
        try:
            return json.loads(obj_match.group())
        except json.JSONDecodeError:
            pass
    return None


@dataclass(frozen=True)
class _TaskConfig:
    template_name: str | None
    fallback_prompt: str
    description: str = ""
    output_type: str = "json"  # "json" / "markdown"


class LongHistoryAnalyzer:
    """县域长周期兴衰史分析器。

    Usage:
        a = LongHistoryAnalyzer()
        result = a.analyze(county=ci, data=processed)
    """

    PERIODS_CONFIG = _TaskConfig(
        template_name="long_history_periods",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:将该县从建县至今划分 4-7 个历史阶段。\n"
            "输出严格 JSON: {periods: [{name, start, end, summary, dominant_logic, key_events: [], evidence: []}]}\n"
            "只输出 JSON。"
        ),
        description="长周期历史阶段划分",
        output_type="json",
    )

    GEO_ORIGIN_CONFIG = _TaskConfig(
        template_name="geo_origin_analysis",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:分析该县形成的 3-6 个地理历史因子。\n"
            "输出严格 JSON: {geo_factors: [{name, description, impact, evidence: []}]}\n"
            "只输出 JSON。"
        ),
        description="建县与地理逻辑分析",
        output_type="json",
    )

    TRADITIONAL_CONFIG = _TaskConfig(
        template_name="traditional_economy",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:分析该县传统时代(1949 前)的经济社会生存方式,600-1200 字,Markdown,小标题。\n"
            "不写招商建议,区分事实与推断([推断])。"
        ),
        description="传统时代生存方式",
        output_type="markdown",
    )

    MODERN_CONFIG = _TaskConfig(
        template_name="modern_shocks",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:分析近代(1840-1949)冲击与变迁,600-1000 字,Markdown,小标题。\n"
            "不写招商建议。"
        ),
        description="近代冲击与变迁",
        output_type="markdown",
    )

    STATE_CONFIG = _TaskConfig(
        template_name="state_period",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:分析计划经济时期(1949-1978)国家再组织,600-1000 字,Markdown,小标题。\n"
            "不写招商建议。"
        ),
        description="计划经济时期再组织",
        output_type="markdown",
    )

    REFORM_CONFIG = _TaskConfig(
        template_name="reform_period",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:分析改革开放前期(1978-2000)产业重塑,600-1000 字,Markdown,小标题。\n"
            "不写招商建议。"
        ),
        description="改革开放产业重塑",
        output_type="markdown",
    )

    CONTEMPORARY_CONFIG = _TaskConfig(
        template_name="contemporary_long_view",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:长周期视角分析新世纪(2001-至今)发展,600-1000 字,Markdown,小标题。\n"
            "不写招商建议。"
        ),
        description="新世纪长周期视角分析",
        output_type="markdown",
    )

    PATTERN_CONFIG = _TaskConfig(
        template_name="long_history_pattern",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "已完成分析:\n```\n{{ analysis_content }}\n```\n\n"
            "任务:归入 10 种长周期模型之一。\n"
            "输出严格 JSON: {pattern_type, summary, confidence, dominant_variables: [], evidence: []}\n"
            "只输出 JSON。"
        ),
        description="长周期兴衰模型归纳",
        output_type="json",
    )

    SUMMARY_CONFIG = _TaskConfig(
        template_name="long_history_summary",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "已完成分析:\n```\n{{ analysis_content }}\n```\n\n"
            "任务:撰写执行摘要(600-900 字),不写招商建议,面向投资者/决策者。"
        ),
        description="长周期执行摘要",
        output_type="markdown",
    )

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt_loader: PromptLoader | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._llm = llm or OpenAICompatibleClient(settings=self._settings)
        self._prompt_loader = prompt_loader or PromptLoader(settings=self._settings)

    # ---- 总入口 ----

    def analyze(self, county: CountyInfo, data: ProcessedData) -> CountyLongHistoryAnalysis:
        """执行长周期兴衰史研究,返回 CountyLongHistoryAnalysis。

        流程: periods → geo_origin → traditional → modern → state → reform
              → contemporary → pattern → summary
        """
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data_text = data.render_for_llm(max_chars=18000)
        county_display = county.display()

        logger.info("长周期研究启动 | 县=%s", county_display)

        # 1. 历史阶段划分
        periods = self.extract_periods(
            county=county_display, date_str=date_str, data_text=data_text,
        )
        # 2. 建县与地理逻辑
        geo_factors = self.analyze_geo_origin(
            county=county_display, date_str=date_str, data_text=data_text,
        )
        # 3. 传统时代生存方式
        traditional = self.analyze_traditional_economy(
            county=county_display, date_str=date_str, data_text=data_text,
        )
        # 4. 近代冲击
        modern = self.analyze_modern_shocks(
            county=county_display, date_str=date_str, data_text=data_text,
        )
        # 5. 计划经济
        state_period = self.analyze_state_period(
            county=county_display, date_str=date_str, data_text=data_text,
        )
        # 6. 改革开放
        reform = self.analyze_reform_period(
            county=county_display, date_str=date_str, data_text=data_text,
        )
        # 7. 新世纪
        contemporary = self.analyze_contemporary_status(
            county=county_display, date_str=date_str, data_text=data_text,
        )

        # 8. 长周期模型归纳(输入前 7 项结果)
        pattern_input = self._build_pattern_input(
            periods=periods, geo_factors=geo_factors,
            traditional=traditional, modern=modern,
            state_period=state_period, reform=reform,
            contemporary=contemporary,
        )
        long_pattern = self.classify_long_history_pattern(
            county=county_display, date_str=date_str, analysis_content=pattern_input,
        )

        # 9. 执行摘要
        summary_input = self._build_summary_input(
            periods=periods, geo_factors=geo_factors,
            traditional=traditional, modern=modern,
            state_period=state_period, reform=reform,
            contemporary=contemporary, long_pattern=long_pattern,
        )
        summary = self.generate_summary(
            county=county_display, analysis_content=summary_input,
        )

        return CountyLongHistoryAnalysis(
            county=county,
            periods=periods,
            geo_factors=geo_factors,
            traditional_economy=traditional,
            modern_shocks=modern,
            state_period_reorganization=state_period,
            reform_period_transformation=reform,
            contemporary_status=contemporary,
            long_history_pattern=long_pattern,
            summary=summary,
        )

    # ---- 各子任务 ----

    def extract_periods(
        self, *, county: str, date_str: str, data_text: str,
    ) -> list[HistoricalPeriod]:
        resp = self._run_task(
            config=self.PERIODS_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        if resp is None:
            return []
        data = _parse_json_lenient(resp.content)
        if not isinstance(data, dict):
            return []
        raw_periods = data.get("periods", []) if isinstance(data, dict) else []
        periods: list[HistoricalPeriod] = []
        for p in raw_periods:
            periods.append(HistoricalPeriod(
                name=str(p.get("name", "")),
                start=str(p.get("start", "")),
                end=str(p.get("end", "")),
                summary=str(p.get("summary", "")),
                dominant_logic=str(p.get("dominant_logic", "")),
                key_events=_safe_str_list(p.get("key_events", [])),
                evidence=_safe_str_list(p.get("evidence", [])),
            ))
        logger.info("历史阶段划分完成 | 阶段数=%d", len(periods))
        return periods

    def analyze_geo_origin(
        self, *, county: str, date_str: str, data_text: str,
    ) -> list[GeoHistoricalFactor]:
        resp = self._run_task(
            config=self.GEO_ORIGIN_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        if resp is None:
            return []
        data = _parse_json_lenient(resp.content)
        if not isinstance(data, dict):
            return []
        raw_factors = data.get("geo_factors", [])
        factors: list[GeoHistoricalFactor] = []
        for f in raw_factors:
            factors.append(GeoHistoricalFactor(
                name=str(f.get("name", "")),
                description=str(f.get("description", "")),
                impact=str(f.get("impact", "")),
                evidence=_safe_str_list(f.get("evidence", [])),
            ))
        logger.info("建县与地理逻辑完成 | 因子数=%d", len(factors))
        return factors

    def analyze_traditional_economy(
        self, *, county: str, date_str: str, data_text: str,
    ) -> str:
        resp = self._run_task(
            config=self.TRADITIONAL_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        return resp.content if resp else "_传统时代生存方式资料不足,需补充县志与地方志。_"

    def analyze_modern_shocks(
        self, *, county: str, date_str: str, data_text: str,
    ) -> str:
        resp = self._run_task(
            config=self.MODERN_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        return resp.content if resp else "_近代冲击与变迁资料不足。_"

    def analyze_state_period(
        self, *, county: str, date_str: str, data_text: str,
    ) -> str:
        resp = self._run_task(
            config=self.STATE_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        return resp.content if resp else "_计划经济时期再组织资料不足。_"

    def analyze_reform_period(
        self, *, county: str, date_str: str, data_text: str,
    ) -> str:
        resp = self._run_task(
            config=self.REFORM_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        return resp.content if resp else "_改革开放产业重塑资料不足。_"

    def analyze_contemporary_status(
        self, *, county: str, date_str: str, data_text: str,
    ) -> str:
        resp = self._run_task(
            config=self.CONTEMPORARY_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        return resp.content if resp else "_新世纪以来发展变化资料不足。_"

    def classify_long_history_pattern(
        self, *, county: str, date_str: str, analysis_content: str,
    ) -> LongHistoryPattern:
        resp = self._run_task(
            config=self.PATTERN_CONFIG,
            county=county, date=date_str, analysis_content=analysis_content,
        )
        if resp is None:
            return LongHistoryPattern()
        data = _parse_json_lenient(resp.content)
        if not isinstance(data, dict):
            return LongHistoryPattern()
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        pattern = LongHistoryPattern(
            pattern_type=str(data.get("pattern_type", "unknown")),
            summary=str(data.get("summary", "")),
            confidence=confidence,
            dominant_variables=_safe_str_list(data.get("dominant_variables", [])),
            evidence=_safe_str_list(data.get("evidence", [])),
        )
        logger.info(
            "长周期模型归纳完成 | type=%s | confidence=%.2f | dominant=%s",
            pattern.pattern_type, pattern.confidence, pattern.dominant_variables,
        )
        return pattern

    def generate_summary(self, *, county: str, analysis_content: str) -> str:
        resp = self._run_task(
            config=self.SUMMARY_CONFIG,
            county=county, date="", analysis_content=analysis_content,
        )
        if resp is None:
            return (
                f"本报告针对 {county} 县域开展长周期兴衰史研究,"
                "覆盖建县逻辑、传统经济、近代冲击、计划经济重塑、"
                "改革开放转型与新世纪变化,并归纳其长周期兴衰模型。"
            )
        return resp.content

    # ---- 内部方法 ----

    def _run_task(self, config: _TaskConfig, **context: object):
        prompt = self._build_prompt_from_config(config=config, **context)
        try:
            resp = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=self._settings.llm.temperature,
                max_tokens=self._settings.llm.max_tokens,
            )
            logger.info(
                "%s 完成 | model=%s | tokens=%d",
                config.description, resp.model, resp.total_tokens,
            )
            return resp
        except Exception as e:
            logger.warning(
                "%s 失败(降级) | err=%s", config.description, e, exc_info=True,
            )
            if self._settings.pipeline.fail_fast:
                raise
            return None

    def _build_prompt_from_config(self, config: _TaskConfig, **context: object) -> str:
        if config.template_name and self._prompt_loader.has_template(config.template_name):
            return self._prompt_loader.render(config.template_name, **context)
        return self._prompt_loader.render_string(config.fallback_prompt, **context)

    @staticmethod
    def _build_pattern_input(
        periods: list[HistoricalPeriod],
        geo_factors: list[GeoHistoricalFactor],
        traditional: str, modern: str,
        state_period: str, reform: str, contemporary: str,
    ) -> str:
        blocks: list[str] = []
        if periods:
            p_lines = []
            for p in periods:
                rng = f"{p.start}–{p.end}" if (p.start or p.end) else "(时间不详)"
                logic = f" | 逻辑:{p.dominant_logic}" if p.dominant_logic else ""
                p_lines.append(f"- **{p.name}** ({rng}){logic}\n  {p.summary}")
            blocks.append("## 历史阶段\n" + "\n".join(p_lines))
        if geo_factors:
            g_lines = [f"- {f.name}: {f.impact}" for f in geo_factors]
            blocks.append("## 地理历史因子\n" + "\n".join(g_lines))
        if traditional:
            blocks.append(f"## 传统时代生存方式\n{traditional[:800]}")
        if modern:
            blocks.append(f"## 近代冲击与变迁\n{modern[:600]}")
        if state_period:
            blocks.append(f"## 计划经济时期再组织\n{state_period[:600]}")
        if reform:
            blocks.append(f"## 改革开放产业重塑\n{reform[:600]}")
        if contemporary:
            blocks.append(f"## 新世纪发展变化\n{contemporary[:600]}")
        return "\n\n".join(blocks)

    @staticmethod
    def _build_summary_input(
        periods: list[HistoricalPeriod],
        geo_factors: list[GeoHistoricalFactor],
        traditional: str, modern: str,
        state_period: str, reform: str, contemporary: str,
        long_pattern: LongHistoryPattern,
    ) -> str:
        blocks: list[str] = []
        blocks.append(f"## 长周期模型\n{long_pattern.pattern_type}: {long_pattern.summary}")
        if long_pattern.dominant_variables:
            blocks.append(f"**主导变量**: {', '.join(long_pattern.dominant_variables)}")
        if periods:
            p_lines = [f"- {p.name}({p.start}–{p.end}): {p.dominant_logic or p.summary[:40]}" for p in periods]
            blocks.append("## 历史阶段\n" + "\n".join(p_lines))
        if geo_factors:
            g_lines = [f"- {f.name}: {f.impact}" for f in geo_factors]
            blocks.append("## 地理因子\n" + "\n".join(g_lines))
        sections = [
            ("传统时代", traditional),
            ("近代冲击", modern),
            ("计划经济", state_period),
            ("改革开放", reform),
            ("新世纪", contemporary),
        ]
        for title, content in sections:
            if content and not content.startswith("_"):
                blocks.append(f"## {title}\n{content[:300]}")
        return "\n\n".join(blocks)
