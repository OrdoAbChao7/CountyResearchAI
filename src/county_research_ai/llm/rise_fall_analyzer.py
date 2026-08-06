"""县域产业兴衰规律分析器(rise-fall 模式)。

针对县域产业做历史兴衰规律研究,回答 7 个核心问题:
    1. 县域基本画像
    2. 靠什么起家
    3. 为什么能发展
    4. 靠什么创收壮大
    5. 何时拐点
    6. 为什么衰败
    7. 属于哪种兴衰模型

设计要点(与 LLMAnalyzer 保持一致):
    - 任务 → 模板映射:优先用 prompts/ 下的模板,不存在则用内联 fallback
    - 单任务失败不阻断整体(fail_fast=False 时降级为空结果)
    - JSON 解析容错:容忍 ```json 代码块包裹 / 字段缺失
    - 与 pipeline 解耦:pipeline 调用 analyze() 即可

任务模板映射:
    timeline_extraction  → timeline_extraction.md
    origin_industry      → origin_industry.md
    rise_analysis        → rise_analysis.md
    decline_analysis     → decline_analysis.md
    talent_loss          → talent_loss.md
    historical_pattern   → historical_pattern.md
    summary              → rise_fall_summary.md
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
    CountyRiseFallAnalysis,
    DeclineFactor,
    HistoricalPattern,
    IndustryLifecycle,
    ProcessedData,
    RiseFactor,
    TimelineEvent,
)
from .base import LLMClient
from .client import OpenAICompatibleClient
from .prompt_loader import PromptLoader

logger = logging.getLogger(__name__)


def _safe_str_list(value) -> list[str]:
    """将任意值安全转换为 list[str](容忍 None / 单值 / 列表)。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]


def _parse_json_lenient(content: str) -> dict | None:
    """容错解析 LLM 返回的 JSON。

    支持三种形态:
        1. 纯 JSON
        2. ```json ... ``` 代码块包裹
        3. 文本中嵌入的 { ... }(取第一个完整对象)
    """
    if not content:
        return None
    text = content.strip()
    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. 剥离 ```json ... ``` 代码块
    fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass
    # 3. 文本中提取首个 {...} 对象
    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        try:
            return json.loads(obj_match.group())
        except json.JSONDecodeError:
            pass
    return None


@dataclass(frozen=True)
class _TaskConfig:
    """单个兴衰分析任务的配置(参考 LLMAnalyzer.TaskConfig)。"""

    template_name: str | None
    fallback_prompt: str
    description: str = ""


class RiseFallAnalyzer:
    """县域产业兴衰规律分析器。

    Usage:
        analyzer = RiseFallAnalyzer()  # 默认 OpenAICompatibleClient + PromptLoader
        result = analyzer.analyze(county=ci, data=processed)
        # result: CountyRiseFallAnalysis
    """

    TIMELINE_CONFIG = _TaskConfig(
        template_name="timeline_extraction",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n- 日期: {{ date }}\n\n"
            "## 参考数据\n```\n{{ processed_data }}\n```\n\n"
            "## 任务\n提取该县产业发展的关键历史时间线事件(5-15 个),"
            "覆盖起家/扩张/拐点/衰落/政策/外部冲击。\n"
            "输出严格 JSON: {events: [{year, event, category, impact, source_url}]}。\n"
            "只输出 JSON。"
        ),
        description="历史时间线提取",
    )

    ORIGIN_CONFIG = _TaskConfig(
        template_name="origin_industry",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n- 日期: {{ date }}\n\n"
            "## 参考数据\n```\n{{ processed_data }}\n```\n\n"
            "## 任务\n识别该县的'起家产业'(早期立县之本)。\n"
            "输出严格 JSON: {origin_industry, period, reason, evidence:[]}。\n"
            "只输出 JSON。"
        ),
        description="起家产业识别",
    )

    RISE_CONFIG = _TaskConfig(
        template_name="rise_analysis",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n- 日期: {{ date }}\n\n"
            "## 参考数据\n```\n{{ processed_data }}\n```\n\n"
            "## 任务\n分析该县产业兴起的 3-6 个核心因子。\n"
            "输出严格 JSON: {rise_factors: [{name, description, evidence:[]}]}。\n"
            "只输出 JSON。"
        ),
        description="兴起因子分析",
    )

    DECLINE_CONFIG = _TaskConfig(
        template_name="decline_analysis",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n- 日期: {{ date }}\n\n"
            "## 参考数据\n```\n{{ processed_data }}\n```\n\n"
            "## 任务\n分析该县产业衰落的 2-5 个核心因子。\n"
            "输出严格 JSON: {decline_factors: [{name, description, severity, evidence:[]}]}。\n"
            "只输出 JSON。"
        ),
        description="衰落因子分析",
    )

    TALENT_LOSS_CONFIG = _TaskConfig(
        template_name="talent_loss",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n- 日期: {{ date }}\n\n"
            "## 参考数据\n```\n{{ processed_data }}\n```\n\n"
            "## 任务\n分析该县人才流失现状与成因。\n"
            "输出严格 JSON: {talent_loss_reasons: [], evidence_urls: []}。\n"
            "只输出 JSON。"
        ),
        description="人才流失分析",
    )

    PATTERN_CONFIG = _TaskConfig(
        template_name="historical_pattern",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n- 日期: {{ date }}\n\n"
            "## 已完成的兴衰分析\n```\n{{ analysis_content }}\n```\n\n"
            "## 任务\n将该县产业兴衰归类为典型兴衰模型,并提炼规律。\n"
            "模型类型: resource_curse/policy_driven/market_cycle/industry_transfer/"
            "talent_drain/path_lock/diversified_growth/mixed。\n"
            "输出严格 JSON: {pattern_type, summary, confidence, evidence:[]}。\n"
            "只输出 JSON。"
        ),
        description="兴衰模型归纳",
    )

    SUMMARY_CONFIG = _TaskConfig(
        template_name="rise_fall_summary",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n\n"
            "## 已完成的兴衰分析\n```\n{{ analysis_content }}\n```\n\n"
            "## 任务\n撰写执行摘要(500-800 字),面向投资者/创业者,突出历史规律,不写成招商建议。"
        ),
        description="兴衰研究执行摘要",
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

    # ---- 公开入口 ----

    def analyze(
        self,
        county: CountyInfo,
        data: ProcessedData,
    ) -> CountyRiseFallAnalysis:
        """执行完整的兴衰规律研究,返回 CountyRiseFallAnalysis。

        流程: timeline → origin → rise → decline → talent_loss → pattern → summary
        每个子任务失败时降级为空结果(fail_fast=True 时抛出)。
        """
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data_text = data.render_for_llm(max_chars=15000)
        county_display = county.display()
        total_tokens = 0
        model_name = ""

        logger.info("兴衰规律研究启动 | 县=%s", county_display)

        # 1. 时间线提取
        timeline_events = self.extract_timeline(
            county=county_display, date_str=date_str, data_text=data_text,
        )
        # 2. 起家产业识别
        origin_result = self.identify_origin_industry(
            county=county_display, date_str=date_str, data_text=data_text,
        )
        # 3. 兴起因子
        rise_factors = self.analyze_rise_factors(
            county=county_display, date_str=date_str, data_text=data_text,
        )
        # 4. 衰落因子
        decline_factors = self.analyze_decline_factors(
            county=county_display, date_str=date_str, data_text=data_text,
        )
        # 5. 人才流失
        talent_loss_reasons = self.analyze_talent_loss(
            county=county_display, date_str=date_str, data_text=data_text,
        )

        # 组装生命周期画像
        growth_industries = [
            rf.name for rf in rise_factors if "产业" in rf.name or "资源" in rf.name
        ][:5]
        # 当前主导产业:无专门分析任务,留空(由报告其他章节呈现,避免误推断)
        current_industries: list[str] = []

        lifecycle = IndustryLifecycle(
            origin_industry=origin_result.get("origin_industry", ""),
            origin_period=origin_result.get("period", ""),
            origin_reason=origin_result.get("reason", ""),
            growth_industries=growth_industries,
            current_industries=current_industries,
            stage=self._infer_stage(timeline_events, decline_factors),
            turning_points=timeline_events,
        )

        # 6. 兴衰模型归纳(输入前面所有分析)
        pattern_input = self._build_pattern_input(
            lifecycle=lifecycle,
            rise_factors=rise_factors,
            decline_factors=decline_factors,
            talent_loss_reasons=talent_loss_reasons,
        )
        historical_pattern = self.classify_historical_pattern(
            county=county_display, date_str=date_str, analysis_content=pattern_input,
        )

        # 7. 执行摘要
        summary_input = self._build_summary_input(
            lifecycle=lifecycle,
            rise_factors=rise_factors,
            decline_factors=decline_factors,
            talent_loss_reasons=talent_loss_reasons,
            historical_pattern=historical_pattern,
        )
        summary_text = self.generate_summary(
            county=county_display, analysis_content=summary_input,
        )

        return CountyRiseFallAnalysis(
            county=county,
            lifecycle=lifecycle,
            rise_factors=rise_factors,
            decline_factors=decline_factors,
            talent_loss_reasons=talent_loss_reasons,
            historical_pattern=historical_pattern,
            summary=summary_text,
            model=model_name,
            tokens_used=total_tokens,
        )

    # ---- 各子任务 ----

    def extract_timeline(
        self, *, county: str, date_str: str, data_text: str,
    ) -> list[TimelineEvent]:
        """提取历史时间线事件。"""
        resp = self._run_task(
            config=self.TIMELINE_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        if resp is None:
            return []
        data = _parse_json_lenient(resp.content)
        if not data:
            logger.warning("时间线解析失败(降级为空) | raw_len=%d", len(resp.content))
            return []
        events_data = data.get("events", [])
        events: list[TimelineEvent] = []
        for e in events_data:
            events.append(TimelineEvent(
                year=str(e.get("year", "")),
                event=str(e.get("event", "")),
                category=str(e.get("category", "unknown")),
                impact=str(e.get("impact", "")),
                source_url=str(e.get("source_url", "")),
            ))
        logger.info("时间线提取完成 | 事件数=%d", len(events))
        return events

    def identify_origin_industry(
        self, *, county: str, date_str: str, data_text: str,
    ) -> dict:
        """识别起家产业,返回原始 dict(origin_industry/period/reason/evidence)。"""
        resp = self._run_task(
            config=self.ORIGIN_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        if resp is None:
            return {"origin_industry": "", "reason": "", "evidence": []}
        data = _parse_json_lenient(resp.content)
        if not data:
            logger.warning("起家产业解析失败(降级为空) | raw_len=%d", len(resp.content))
            return {"origin_industry": "", "reason": "", "evidence": []}
        return {
            "origin_industry": str(data.get("origin_industry", "")),
            "period": str(data.get("period", "")),
            "reason": str(data.get("reason", "")),
            "evidence": _safe_str_list(data.get("evidence", [])),
        }

    def analyze_rise_factors(
        self, *, county: str, date_str: str, data_text: str,
    ) -> list[RiseFactor]:
        """分析产业兴起因子。"""
        resp = self._run_task(
            config=self.RISE_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        if resp is None:
            return []
        data = _parse_json_lenient(resp.content)
        if not data:
            logger.warning("兴起因子解析失败(降级为空) | raw_len=%d", len(resp.content))
            return []
        factors_data = data.get("rise_factors", [])
        factors: list[RiseFactor] = []
        for f in factors_data:
            factors.append(RiseFactor(
                name=str(f.get("name", "")),
                description=str(f.get("description", "")),
                evidence=_safe_str_list(f.get("evidence", [])),
            ))
        logger.info("兴起因子分析完成 | 因子数=%d", len(factors))
        return factors

    def analyze_decline_factors(
        self, *, county: str, date_str: str, data_text: str,
    ) -> list[DeclineFactor]:
        """分析产业衰落因子。"""
        resp = self._run_task(
            config=self.DECLINE_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        if resp is None:
            return []
        data = _parse_json_lenient(resp.content)
        if not data:
            logger.warning("衰落因子解析失败(降级为空) | raw_len=%d", len(resp.content))
            return []
        factors_data = data.get("decline_factors", [])
        factors: list[DeclineFactor] = []
        for f in factors_data:
            try:
                severity = float(f.get("severity", 0.5))
            except (TypeError, ValueError):
                severity = 0.5
            severity = max(0.0, min(1.0, severity))
            factors.append(DeclineFactor(
                name=str(f.get("name", "")),
                description=str(f.get("description", "")),
                severity=severity,
                evidence=_safe_str_list(f.get("evidence", [])),
            ))
        logger.info("衰落因子分析完成 | 因子数=%d", len(factors))
        return factors

    def analyze_talent_loss(
        self, *, county: str, date_str: str, data_text: str,
    ) -> list[str]:
        """分析人才流失,返回原因列表。"""
        resp = self._run_task(
            config=self.TALENT_LOSS_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        if resp is None:
            return []
        data = _parse_json_lenient(resp.content)
        if not data:
            logger.warning("人才流失解析失败(降级为空) | raw_len=%d", len(resp.content))
            return []
        reasons = _safe_str_list(data.get("talent_loss_reasons", []))
        logger.info("人才流失分析完成 | 原因数=%d", len(reasons))
        return reasons

    def classify_historical_pattern(
        self, *, county: str, date_str: str, analysis_content: str,
    ) -> HistoricalPattern:
        """归纳兴衰模型。"""
        resp = self._run_task(
            config=self.PATTERN_CONFIG,
            county=county, date=date_str, analysis_content=analysis_content,
        )
        if resp is None:
            return HistoricalPattern()
        data = _parse_json_lenient(resp.content)
        if not data:
            logger.warning("兴衰模型解析失败(降级为空) | raw_len=%d", len(resp.content))
            return HistoricalPattern()
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        pattern = HistoricalPattern(
            pattern_type=str(data.get("pattern_type", "unknown")),
            summary=str(data.get("summary", "")),
            confidence=confidence,
            evidence=_safe_str_list(data.get("evidence", [])),
        )
        logger.info(
            "兴衰模型归纳完成 | type=%s | confidence=%.2f",
            pattern.pattern_type, pattern.confidence,
        )
        return pattern

    def generate_summary(self, *, county: str, analysis_content: str) -> str:
        """生成执行摘要(使用 rise_fall_summary.md 模板或 fallback)。"""
        resp = self._run_task(
            config=self.SUMMARY_CONFIG,
            county=county, date="", processed_data=analysis_content,
            analysis_content=analysis_content,
        )
        if resp is None:
            return self._fallback_summary(county, analysis_content)
        return resp.content

    # ---- 内部方法 ----

    def _run_task(self, config: _TaskConfig, **context: object):
        """执行单个任务,返回 LLMResponse;失败时按 fail_fast 决策。"""
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
        """根据 _TaskConfig 构建 prompt:优先模板,否则 fallback。"""
        if config.template_name and self._prompt_loader.has_template(config.template_name):
            return self._prompt_loader.render(config.template_name, **context)
        return self._prompt_loader.render_string(config.fallback_prompt, **context)

    @staticmethod
    def _infer_stage(
        timeline_events: list[TimelineEvent],
        decline_factors: list[DeclineFactor],
    ) -> str:
        """根据时间线与衰落因子推断当前阶段。"""
        if not timeline_events and not decline_factors:
            return "unknown"
        # 有显著衰落因子(平均 severity > 0.5)且近期有 decline 事件
        has_decline_event = any(e.category == "decline" for e in timeline_events)
        avg_severity = (
            sum(f.severity for f in decline_factors) / len(decline_factors)
            if decline_factors else 0.0
        )
        if has_decline_event and avg_severity > 0.6:
            return "decline"
        if avg_severity > 0.3 or has_decline_event:
            return "transition"
        has_growth = any(e.category == "growth" for e in timeline_events)
        if has_growth and not has_decline_event:
            return "growth"
        return "mature"

    @staticmethod
    def _build_pattern_input(
        lifecycle: IndustryLifecycle,
        rise_factors: list[RiseFactor],
        decline_factors: list[DeclineFactor],
        talent_loss_reasons: list[str],
    ) -> str:
        """为兴衰模型归纳任务拼接输入文本。"""
        blocks: list[str] = []
        blocks.append(f"## 起家产业\n{lifecycle.origin_industry or '(未识别)'}")
        blocks.append(f"## 当前阶段\n{lifecycle.stage}")
        if lifecycle.turning_points:
            tp_lines = [
                f"- {e.year} [{e.category}] {e.event} — {e.impact}"
                for e in lifecycle.turning_points
            ]
            blocks.append("## 关键时间线\n" + "\n".join(tp_lines))
        if rise_factors:
            rf_lines = [
                f"- {f.name}: {f.description}" for f in rise_factors
            ]
            blocks.append("## 兴起因子\n" + "\n".join(rf_lines))
        if decline_factors:
            df_lines = [
                f"- {f.name}(severity={f.severity:.1f}): {f.description}"
                for f in decline_factors
            ]
            blocks.append("## 衰落因子\n" + "\n".join(df_lines))
        if talent_loss_reasons:
            blocks.append("## 人才流失原因\n" + "\n".join(f"- {r}" for r in talent_loss_reasons))
        return "\n\n".join(blocks)

    @staticmethod
    def _build_summary_input(
        lifecycle: IndustryLifecycle,
        rise_factors: list[RiseFactor],
        decline_factors: list[DeclineFactor],
        talent_loss_reasons: list[str],
        historical_pattern: HistoricalPattern,
    ) -> str:
        """为执行摘要任务拼接输入文本。"""
        blocks: list[str] = []
        blocks.append(f"## 兴衰模型\n{historical_pattern.pattern_type}: {historical_pattern.summary}")
        blocks.append(f"## 起家产业\n{lifecycle.origin_industry or '(未识别)'}")
        blocks.append(f"## 当前阶段\n{lifecycle.stage}")
        if lifecycle.turning_points:
            tp_lines = [
                f"- {e.year} [{e.category}] {e.event}" for e in lifecycle.turning_points
            ]
            blocks.append("## 关键时间线\n" + "\n".join(tp_lines))
        if rise_factors:
            blocks.append("## 兴起因子\n" + "\n".join(f"- {f.name}" for f in rise_factors))
        if decline_factors:
            blocks.append(
                "## 衰落因子\n" + "\n".join(f"- {f.name}(severity={f.severity:.1f})" for f in decline_factors)
            )
        if talent_loss_reasons:
            blocks.append("## 人才流失原因\n" + "\n".join(f"- {r}" for r in talent_loss_reasons))
        return "\n\n".join(blocks)

    @staticmethod
    def _fallback_summary(county: str, analysis_content: str) -> str:
        """摘要生成失败时的简易降级。"""
        return (
            f"本报告针对 {county} 县域产业开展兴衰规律研究。\n\n"
            f"基于历史时间线、起家产业、兴起与衰落因子的综合分析,"
            f"归纳其产业兴衰模型与可迁移的历史规律。\n\n"
            f"_{analysis_content[:200]}..._"
        )
