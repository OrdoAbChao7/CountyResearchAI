"""故事矿工:从县域产业研究报告中提炼故事线。

输入: 研究报告 Markdown 文本
输出: StoryLine(故事线)

设计要点:
    - 以纪录片策划角色提取"值得讲述的故事"
    - 严禁编造人物、企业、年份、数据
    - 所有内容必须来源于研究报告
    - 失败时降级为空故事线(不编造)
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import Settings, get_settings
from ..llm.base import LLMClient
from ..llm.client import OpenAICompatibleClient
from ..llm.prompt_loader import PromptLoader
from ..models import StoryLine
from .templates import _TaskConfig, _parse_json_lenient, _safe_str_list

logger = logging.getLogger(__name__)


class StoryMiner:
    """故事线提炼器。

    Usage:
        miner = StoryMiner()
        story = miner.mine(county="信丰县", report_content="...")
        # story: StoryLine
    """

    STORY_CONFIG = _TaskConfig(
        template_name="story_mining",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n\n"
            "## 来源研究报告\n```\n{{ report_content }}\n```\n\n"
            "## 任务\n以纪录片策划角色,从研究报告中提炼一个'值得讲述的故事'。\n"
            "要求:\n"
            "1. 禁止编造人物、企业、年份、数据,所有内容必须来源于报告\n"
            "2. 寻找人与产业的关系、财富变化过程、冲突和转折\n"
            "3. 输出严格 JSON: {main_story, characters:[], enterprises:[], "
            "events:[], data_points:[], time_span, conflict_type, evidence_refs:[]}\n"
            "只输出 JSON。"
        ),
        description="故事线提炼",
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

    def mine(self, *, county: str, report_content: str) -> StoryLine:
        """从研究报告提炼故事线。

        Args:
            county: 县名
            report_content: 研究报告 Markdown 文本

        Returns:
            StoryLine;LLM 失败时返回空故事线(不编造)
        """
        resp = self._run_task(
            config=self.STORY_CONFIG,
            county=county, report_content=report_content,
        )
        if resp is None:
            logger.warning("故事线提取失败(降级为空) | 县=%s", county)
            return StoryLine()

        data = _parse_json_lenient(resp.content)
        if not data:
            logger.warning("故事线解析失败(降级为空) | 县=%s | raw_len=%d", county, len(resp.content))
            return StoryLine()

        story = StoryLine(
            main_story=str(data.get("main_story", "")),
            characters=_safe_str_list(data.get("characters", [])),
            enterprises=_safe_str_list(data.get("enterprises", [])),
            events=_safe_str_list(data.get("events", [])),
            data_points=_safe_str_list(data.get("data_points", [])),
            time_span=str(data.get("time_span", "")),
            conflict_type=str(data.get("conflict_type", "")),
            evidence_refs=_safe_str_list(data.get("evidence_refs", [])),
        )
        logger.info("故事线提取完成 | 主线长度=%d | 事件数=%d", len(story.main_story), len(story.events))
        return story

    # ---- 内部方法 ----

    def _run_task(self, config: _TaskConfig, **context: Any):
        """执行单个任务,返回 LLMResponse;失败时按 fail_fast 决策。"""
        prompt = self._build_prompt_from_config(config=config, **context)
        try:
            resp = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=self._settings.llm.temperature,
            )
            return resp
        except Exception as e:
            logger.error(
                "故事线提取 LLM 失败 | template=%s | error=%s",
                config.template_name, e, exc_info=True,
            )
            return None

    def _build_prompt_from_config(self, config: _TaskConfig, **context: Any) -> str:
        """从配置渲染提示词(优先模板,fallback 兜底)。"""
        try:
            return self._prompt_loader.render(config.template_name, **context)
        except Exception as e:
            logger.warning(
                "提示词模板加载失败(使用 fallback) | template=%s | error=%s",
                config.template_name, e,
            )
            return config.fallback_prompt