"""脚本生成器:基于选题角度生成 60 秒短视频脚本。

输入: ContentAngle(选题角度)
输出: VideoScript(5 段时间轴脚本)

设计要点(复用 rise_fall_analyzer 模式):
    - 任务 → 模板映射:优先 prompts/short_video_script.md,缺失则用内联 fallback
    - LLM 漏段时按 SCRIPT_SEGMENTS 模板补空段
    - 段位按时间轴顺序排序
    - LLM 失败时降级为 _fallback_script(占位旁白)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..config import Settings, get_settings
from ..llm.base import LLMClient
from ..llm.client import OpenAICompatibleClient
from ..llm.prompt_loader import PromptLoader
from ..models import ContentAngle, ScriptSegment, VideoScript
from .templates import SCRIPT_SEGMENTS, _TaskConfig, _parse_json_lenient, _safe_str_list

logger = logging.getLogger(__name__)

# 段位排序索引(按时间轴)
_SEGMENT_ORDER: dict[str, int] = {
    tpl["segment_id"]: i for i, tpl in enumerate(SCRIPT_SEGMENTS)
}


class ScriptGenerator:
    """60 秒短视频脚本生成器。

    Usage:
        gen = ScriptGenerator()
        script = gen.generate_script(county="安吉县", angle=angle)
        # script: VideoScript
    """

    SCRIPT_CONFIG = _TaskConfig(
        template_name="short_video_script",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n\n"
            "## 选题角度(JSON)\n```\n{{ angle_json }}\n```\n\n"
            "## 任务\n撰写 60 秒短视频脚本,5 段时间轴:\n"
            "0-5s(hook) / 5-20s(origin) / 20-40s(growth) / 40-55s(decline) / 55-60s(takeaway)。\n"
            "总字数 220-260 字;旁白口语化;结论绑定证据;拒绝招商/鸡汤/虚构。\n"
            "输出严格 JSON: {angle_id, title, duration_seconds, segments:[{segment_id, "
            "time_range, narration, on_screen, visual_hint, source_refs:[]}]}。\n"
            "只输出 JSON。"
        ),
        description="短视频脚本生成",
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

    def generate_script(self, *, county: str, angle: ContentAngle) -> VideoScript:
        """基于选题角度生成 60 秒短视频脚本。

        Args:
            county: 县名
            angle: 选题角度

        Returns:
            VideoScript;LLM 失败时返回兜底脚本(占位旁白)
        """
        angle_json = json.dumps(
            angle.model_dump(mode="json"), ensure_ascii=False, indent=2,
        )
        resp = self._run_task(
            config=self.SCRIPT_CONFIG,
            county=county, angle_json=angle_json,
        )
        if resp is None:
            return self._fallback_script(angle)
        data = _parse_json_lenient(resp.content)
        if not data:
            logger.warning("脚本解析失败(降级) | raw_len=%d", len(resp.content))
            return self._fallback_script(angle)

        segments = self._build_segments(data.get("segments", []))
        total_words = sum(len(seg.narration) for seg in segments)
        try:
            duration = int(data.get("duration_seconds", 60))
        except (TypeError, ValueError):
            duration = 60
        script = VideoScript(
            angle_id=str(data.get("angle_id", angle.angle_id)),
            title=str(data.get("title", angle.title)),
            duration_seconds=duration,
            segments=segments,
            total_word_count=total_words,
        )
        logger.info(
            "脚本生成完成 | segments=%d | words=%d",
            len(script.segments), total_words,
        )
        return script

    # ---- 内部方法 ----

    @staticmethod
    def _build_segments(segments_data: list) -> list[ScriptSegment]:
        """从 LLM 返回的 segments 列表构建 ScriptSegment,补全缺失段位并按时间轴排序。"""
        segments: list[ScriptSegment] = []
        for s in segments_data:
            segments.append(ScriptSegment(
                segment_id=str(s.get("segment_id", "")),
                time_range=str(s.get("time_range", "")),
                narration=str(s.get("narration", "")),
                on_screen=str(s.get("on_screen", "")),
                visual_hint=str(s.get("visual_hint", "")),
                source_refs=_safe_str_list(s.get("source_refs", [])),
            ))
        # 段位补全:LLM 漏段时按模板补空段
        existing_ids = {seg.segment_id for seg in segments}
        for tpl in SCRIPT_SEGMENTS:
            if tpl["segment_id"] not in existing_ids:
                segments.append(ScriptSegment(
                    segment_id=tpl["segment_id"],
                    time_range=tpl["time_range"],
                    narration="(本段缺失,需补写)",
                ))
        # 按时间轴顺序排序
        segments.sort(key=lambda x: _SEGMENT_ORDER.get(x.segment_id, 99))
        return segments

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
    def _fallback_script(angle: ContentAngle) -> VideoScript:
        """LLM 失败时的兜底脚本(占位旁白,便于人工补写)。"""
        segments = [
            ScriptSegment(
                segment_id=tpl["segment_id"],
                time_range=tpl["time_range"],
                narration=f"({tpl['purpose']} - LLM 生成失败,需补写)",
                on_screen=angle.title,
                visual_hint="(待补)",
                source_refs=angle.source_refs if i == 0 else [],
            )
            for i, tpl in enumerate(SCRIPT_SEGMENTS)
        ]
        return VideoScript(
            angle_id=angle.angle_id,
            title=angle.title,
            duration_seconds=60,
            segments=segments,
            total_word_count=0,
        )
