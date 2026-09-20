"""事实核查器:对短视频脚本逐条核查,以研究报告为唯一依据。

输入: VideoScript + 研究报告
输出: FactCheckResult(含 items 与 overall_status)

设计要点(复用 rise_fall_analyzer 模式):
    - 任务 → 模板映射:优先 prompts/fact_check.md,缺失则用内联 fallback
    - 三档结论: supported / unsupported / needs_revision
    - overall_status 严格判定: 含 unsupported → unsupported;否则按 needs_revision/ok
    - LLM 失败时降级为全部 needs_revision(标记需人工复核)

约束(项目硬约束):
    - 存在 unsupported 事实声明时,overall_status 必须为 unsupported(必须返修)
    - 不引入外部知识,仅以研究报告为依据
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..config import Settings, get_settings
from ..llm.base import LLMClient
from ..llm.client import OpenAICompatibleClient
from ..llm.prompt_loader import PromptLoader
from ..models import FactCheckItem, FactCheckResult, VideoScript
from .templates import _TaskConfig, _parse_json_lenient

logger = logging.getLogger(__name__)

_VALID_VERDICTS = {"supported", "unsupported", "needs_revision"}


class FactChecker:
    """短视频脚本事实核查器(以研究报告为唯一依据)。

    Usage:
        checker = FactChecker()
        result = checker.check(county="安吉县", script=script, report_content="...")
        # result: FactCheckResult
    """

    CHECK_CONFIG = _TaskConfig(
        template_name="fact_check",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n\n"
            "## 待核查脚本(JSON)\n```\n{{ script_json }}\n```\n\n"
            "## 核查依据(研究报告)\n```\n{{ report_content }}\n```\n\n"
            "## 任务\n逐条核查脚本中的事实声明,以研究报告为唯一依据。\n"
            "verdict: supported/unsupported/needs_revision;不放过模糊声明。\n"
            "输出严格 JSON: {angle_id, items:[{claim, segment_id, evidence, verdict, note}], "
            "overall_status}。\n"
            "overall_status 判定: 全部 supported→ok;含 unsupported→unsupported;"
            "否则 needs_revision。\n"
            "只输出 JSON。"
        ),
        description="短视频脚本事实核查",
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

    def check(
        self, *, county: str, script: VideoScript, report_content: str,
    ) -> FactCheckResult:
        """对脚本逐条核查,返回 FactCheckResult。

        Args:
            county: 县名
            script: 待核查脚本
            report_content: 研究报告 Markdown 文本(唯一核查依据)

        Returns:
            FactCheckResult;LLM 失败时返回兜底(全部 needs_revision)
        """
        script_json = json.dumps(
            script.model_dump(mode="json"), ensure_ascii=False, indent=2,
        )
        resp = self._run_task(
            config=self.CHECK_CONFIG,
            county=county, script_json=script_json, report_content=report_content,
        )
        if resp is None:
            return self._fallback_result(script)
        data = _parse_json_lenient(resp.content)
        if not data:
            logger.warning("事实核查解析失败(降级) | raw_len=%d", len(resp.content))
            return self._fallback_result(script)

        items = self._build_items(data.get("items", []))
        # 优先信任 LLM 的 overall_status,但若与 items 推断不一致则按 items 重算
        overall_from_items = self._infer_overall(items)
        overall_from_llm = str(data.get("overall_status", "")).strip()
        if overall_from_llm in {"ok", "needs_revision", "unsupported"}:
            # 约束:含 unsupported 必须为 unsupported(LLM 可能误判)
            if "unsupported" in {it.verdict for it in items} and overall_from_llm != "unsupported":
                overall = "unsupported"
            else:
                overall = overall_from_llm
        else:
            overall = overall_from_items

        result = FactCheckResult(
            angle_id=str(data.get("angle_id", script.angle_id)),
            items=items,
            overall_status=overall,
        )
        logger.info(
            "事实核查完成 | items=%d | status=%s",
            len(items), overall,
        )
        return result

    # ---- 内部方法 ----

    @staticmethod
    def _build_items(items_data: list) -> list[FactCheckItem]:
        """从 LLM 返回的 items 列表构建 FactCheckItem,校验 verdict 合法性。"""
        items: list[FactCheckItem] = []
        for it in items_data:
            verdict = str(it.get("verdict", "needs_revision"))
            if verdict not in _VALID_VERDICTS:
                verdict = "needs_revision"
            items.append(FactCheckItem(
                claim=str(it.get("claim", "")),
                segment_id=str(it.get("segment_id", "")),
                evidence=str(it.get("evidence", "")),
                verdict=verdict,
                note=str(it.get("note", "")),
            ))
        return items

    @staticmethod
    def _infer_overall(items: list[FactCheckItem]) -> str:
        """根据各 item verdict 推断 overall_status(严格遵守硬约束)。"""
        if not items:
            return "needs_revision"
        verdicts = {it.verdict for it in items}
        if "unsupported" in verdicts:
            return "unsupported"
        if "needs_revision" in verdicts:
            return "needs_revision"
        return "ok"

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
    def _fallback_result(script: VideoScript) -> FactCheckResult:
        """LLM 失败时的兜底(全部标为 needs_revision,需人工复核)。"""
        items = [
            FactCheckItem(
                claim=seg.narration[:80] if seg.narration else f"({seg.segment_id} 段旁白)",
                segment_id=seg.segment_id,
                evidence="(LLM 核查失败,需人工复核)",
                verdict="needs_revision",
                note="自动核查失败,需人工介入",
            )
            for seg in script.segments if seg.segment_id
        ]
        return FactCheckResult(
            angle_id=script.angle_id,
            items=items,
            overall_status="needs_revision",
        )
