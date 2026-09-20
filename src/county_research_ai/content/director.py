"""内容导演:从县域产业研究报告生成短视频选题角度。

输入: 研究报告 Markdown 文本
输出: ContentAngle(选题角度)

设计要点(复用 rise_fall_analyzer 模式):
    - 任务 → 模板映射:优先 prompts/content_director.md,缺失则用内联 fallback
    - LLM 失败时降级为 _fallback_angle(基于报告前 500 字的兜底角度)
    - JSON 解析容错:容忍 ```json 代码块 / 字段缺失
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import Settings, get_settings
from ..llm.base import LLMClient
from ..llm.client import OpenAICompatibleClient
from ..llm.prompt_loader import PromptLoader
from ..models import ContentAngle
from .templates import _TaskConfig, _parse_json_lenient, _safe_str_list

logger = logging.getLogger(__name__)


class ContentDirector:
    """短视频选题角度策划器。

    Usage:
        director = ContentDirector()
        angle = director.generate_angle(county="安吉县", report_content="...")
        # angle: ContentAngle
    """

    ANGLE_CONFIG = _TaskConfig(
        template_name="content_director",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n\n"
            "## 来源研究报告\n```\n{{ report_content }}\n```\n\n"
            "## 任务\n基于研究报告,策划 1 个短视频选题角度。\n"
            "要求:冲突优先、历史解释而非招商、拒绝鸡汤、拒绝虚构、面向科普。\n"
            "输出严格 JSON: {angle_id, title, hook, perspective, target_audience, "
            "key_points:[], tone, source_refs:[]}。\n"
            "只输出 JSON。"
        ),
        description="短视频选题角度策划",
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

    def generate_angle(self, *, county: str, report_content: str) -> ContentAngle:
        """从研究报告生成 1 个选题角度。

        Args:
            county: 县名
            report_content: 研究报告 Markdown 文本

        Returns:
            ContentAngle;LLM 失败时返回兜底角度
        """
        resp = self._run_task(
            config=self.ANGLE_CONFIG,
            county=county, report_content=report_content,
        )
        if resp is None:
            return self._fallback_angle(county, report_content)
        data = _parse_json_lenient(resp.content)
        if not data:
            logger.warning("选题角度解析失败(降级) | raw_len=%d", len(resp.content))
            return self._fallback_angle(county, report_content)
        angle = ContentAngle(
            angle_id=str(data.get("angle_id", "")),
            title=str(data.get("title", "")),
            hook=str(data.get("hook", "")),
            perspective=str(data.get("perspective", "")),
            target_audience=str(data.get("target_audience", "")),
            key_points=_safe_str_list(data.get("key_points", [])),
            tone=str(data.get("tone", "")),
            source_refs=_safe_str_list(data.get("source_refs", [])),
        )
        logger.info("选题角度生成完成 | angle_id=%s", angle.angle_id)
        return angle

    # ---- 内部方法 ----

    def _run_task(self, config: _TaskConfig, **context: Any):
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

    def _build_prompt_from_config(self, config: _TaskConfig, **context: Any) -> str:
        """根据 _TaskConfig 构建 prompt:优先模板,否则 fallback。"""
        if config.template_name and self._prompt_loader.has_template(config.template_name):
            return self._prompt_loader.render(config.template_name, **context)
        return self._prompt_loader.render_string(config.fallback_prompt, **context)

    @staticmethod
    def _fallback_angle(county: str, report_content: str) -> ContentAngle:
        """LLM 失败时的兜底角度(基于报告前 500 字)。"""
        snippet = report_content[:500].replace("\n", " ")
        return ContentAngle(
            angle_id="fallback-angle",
            title=f"{county}:一份产业兴衰样本",
            hook="这是一座县城的产业兴衰史。",
            perspective=f"基于研究报告概括 {county} 的产业兴衰主线,作为兜底选题。",
            target_audience="产业研究爱好者",
            key_points=[f"详见研究报告摘要: {snippet}..."],
            tone="冷静叙事",
            source_refs=["研究报告(兜底,LLM 生成失败)"],
        )
