"""Agent Planner：LLM 规划和确定性 fallback。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from pydantic import ValidationError

from ..config import Settings, get_settings
from ..llm.base import LLMClient
from ..llm.prompt_loader import PromptLoader
from .base import ToolSpec
from .models import AgentPlanStep, AgentState

logger = logging.getLogger(__name__)


class Planner(Protocol):
    def next_step(self, state: AgentState, tool_specs: list[ToolSpec]) -> AgentPlanStep: ...


def parse_plan_step(content: str) -> AgentPlanStep:
    """解析纯 JSON、代码块或文本中嵌入的第一个 JSON 对象。"""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else text
    if not fenced and not candidate.startswith("{"):
        embedded = re.search(r"\{.*\}", candidate, re.DOTALL)
        if embedded:
            candidate = embedded.group(0)
    try:
        payload = json.loads(candidate)
        return AgentPlanStep.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ValueError("Planner response is not a valid JSON action") from exc


class FallbackPlanner:
    """依据状态补齐最小研究链路，保证 Mock 模式可运行。"""

    def next_step(self, state: AgentState, tool_specs: list[ToolSpec]) -> AgentPlanStep:
        def action(tool: str, reason: str, arguments: dict[str, Any] | None = None) -> AgentPlanStep:
            return AgentPlanStep(
                tool=tool,
                reason=reason,
                arguments=arguments or {},
                planner_source="fallback",
            )

        request = state.request
        if not state.raw_docs:
            return action(
                "search_materials",
                "当前没有原始材料，需要先收集县域研究资料",
                {"county": request.county, "focus": request.focus or "", "mode": request.mode},
            )
        if not request.focus and state.discovery is None:
            return action("discover_focus", "请求未指定研究方向，需要从搜索材料中发现焦点")
        if state.processed is None:
            return action("build_evidence_pack", "需要清洗、去重并构造证据包")
        if request.mode in {"snapshot", "industry"} and not state.snapshot_analyses:
            return action("analyze_research", "需要分析产业现状、优势、短板和建议")
        if request.mode == "rise-fall" and state.rise_fall_analysis is None:
            return action("analyze_research", "需要分析产业兴衰规律")
        if request.mode == "long-history" and state.long_history_analysis is None:
            return action("analyze_research", "需要分析县域长周期历史")
        if not state.report_path:
            return action("render_report", "研究结果已具备，需要生成可审查报告")
        return action("finish", "报告已生成，可以进行最终校验", {"is_final": True})


class LLMPlanner:
    """使用 LLM 选择动作，任何解析失败都回退到 FallbackPlanner。"""

    def __init__(
        self,
        llm: LLMClient,
        prompt_loader: PromptLoader | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._llm = llm
        self._settings = settings or get_settings()
        self._prompt_loader = prompt_loader or PromptLoader(settings=self._settings)
        self._fallback = FallbackPlanner()

    def next_step(self, state: AgentState, tool_specs: list[ToolSpec]) -> AgentPlanStep:
        try:
            prompt = self._build_prompt(state, tool_specs)
            response = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=self._settings.llm.temperature,
                max_tokens=min(self._settings.llm.max_tokens, 1000),
            )
            step = parse_plan_step(response.content)
            names = {spec.name for spec in tool_specs}
            if step.tool != "finish" and names and step.tool not in names:
                raise ValueError(f"unknown planner tool: {step.tool}")
            return step.model_copy(update={"planner_source": "llm"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agent Planner 失败，使用 fallback | err=%s", exc)
            return self._fallback.next_step(state, tool_specs)

    def _build_prompt(self, state: AgentState, tool_specs: list[ToolSpec]) -> str:
        context = {
            "goal": state.request.model_dump_json(ensure_ascii=False),
            "state_summary": json.dumps(_state_summary(state), ensure_ascii=False),
            "tool_specs": json.dumps(
                [spec.model_dump(mode="json") for spec in tool_specs],
                ensure_ascii=False,
            ),
            "remaining_steps": max(0, 8 - state.steps_used),
        }
        if self._prompt_loader.has_template("agent_planner"):
            return self._prompt_loader.render("agent_planner", **context)
        return self._prompt_loader.render_string(
            "选择下一步工具并只输出 JSON：{{ tool_specs }}", **context,
        )


def _state_summary(state: AgentState) -> dict[str, Any]:
    return {
        "county": state.request.county,
        "focus": state.request.focus,
        "mode": state.request.mode,
        "raw_docs": len(state.raw_docs),
        "has_discovery": state.discovery is not None,
        "has_processed": state.processed is not None,
        "snapshot_analyses": len(state.snapshot_analyses),
        "has_rise_fall_analysis": state.rise_fall_analysis is not None,
        "has_long_history_analysis": state.long_history_analysis is not None,
        "report_path": state.report_path,
        "steps_used": state.steps_used,
    }
