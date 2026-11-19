"""Agent 基类：有界 ReAct 工具循环 + 确定性降级。

真正的自主性体现在：模型自行选择工具、组织证据、决定何时结束。
当 LLM 不可用或输出无法解析时，才使用每个 Agent 明确定义的降级工具序列，
并在结果中标记 ``degraded=True``——降级不会伪装成自主推理。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from ..domain.events import EventCallback, EventType
from ..domain.intelligence import (
    AgentKind,
    AgentResult,
    Claim,
    ResearchTask,
    VerificationStatus,
)
from ..evidence.support import check_claim_evidence
from ..llm.base import LLMClient
from ..llm.structured import StructuredOutputError, parse_json_object
from ..models import RawDoc

logger = logging.getLogger(__name__)


class ToolObservation(BaseModel):
    """一次工具调用的结果。"""

    tool: str
    ok: bool = True
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0


FallbackBuilder = Callable[
    ["AgentSpec", list[ToolObservation], "AgentContext", ResearchTask], dict[str, Any]
]


@dataclass(frozen=True)
class AgentSpec:
    """Agent 的静态定义。"""

    kind: AgentKind
    name: str
    description: str
    system_prompt: str
    tools: tuple[str, ...]
    output_model: type[BaseModel]
    fallback_calls: tuple[dict[str, Any], ...] = ()
    fallback_builder: FallbackBuilder | None = None
    max_steps: int = 6
    max_llm_calls: int = 6


@dataclass
class AgentContext:
    """单次研究运行内所有 Agent 共享的服务容器。"""

    run_id: str
    county: str
    focus: str
    evidence: Any
    search: Any
    documents: Any
    graph: Any
    quant: Any
    analytics: Any = None
    graph_store: Any = None
    gap_radar: Any = None
    emitter: EventCallback | None = None
    round: int = 1
    raw_docs: list[RawDoc] = field(default_factory=list)
    _docs_lock: threading.RLock = field(default_factory=threading.RLock)

    # ---- 文档共享 ----

    def add_docs(self, docs: list[RawDoc]) -> int:
        with self._docs_lock:
            known = {(d.url or d.title) for d in self.raw_docs}
            added = 0
            for doc in docs:
                key = doc.url or doc.title
                if key and key not in known:
                    self.raw_docs.append(doc)
                    known.add(key)
                    added += 1
            return added

    def document_text(self, *, limit: int = 20, max_chars: int = 6000) -> str:
        with self._docs_lock:
            docs = list(self.raw_docs[:limit])
        blocks = []
        used = 0
        for doc in docs:
            block = f"{doc.title}\n{doc.url}\n{(doc.content or doc.snippet)[:600]}"
            if used + len(block) > max_chars:
                break
            blocks.append(block)
            used += len(block)
        return "\n\n---\n\n".join(blocks)

    # ---- 事件 ----

    def emit(self, event_type: str, message: str, *, agent: str = "", **data: Any) -> None:
        if self.emitter is not None:
            try:
                self.emitter(event_type, agent, message, data)
            except Exception:  # noqa: BLE001
                logger.debug("event emitter failed", exc_info=True)


class SpecialistAgent:
    """按 AgentSpec 运行的专业 Agent。"""

    def __init__(
        self,
        spec: AgentSpec,
        *,
        llm: LLMClient | None,
        tools: Any,
        max_steps: int | None = None,
        max_llm_calls: int | None = None,
    ) -> None:
        self.spec = spec
        self._llm = llm
        self._tools = tools
        self.max_steps = max_steps or spec.max_steps
        self.max_llm_calls = max_llm_calls or spec.max_llm_calls

    # ---- 入口 ----

    def run(self, task: ResearchTask, context: AgentContext) -> AgentResult:
        started = datetime.now(timezone.utc)
        context.emit(
            EventType.AGENT_STARTED,
            f"{self.spec.name} 开始执行：{task.objective[:120]}",
            agent=self.spec.kind.value,
            task_id=task.task_id,
            round=task.round,
        )
        observations: list[ToolObservation] = []
        degraded = False
        error = ""

        if self._llm is not None:
            try:
                result = self._run_llm(task, context, observations)
                if result is not None:
                    result.started_at = started
                    result.finished_at = datetime.now(timezone.utc)
                    self._emit_done(result, context)
                    return result
                degraded = True
            except Exception as exc:  # noqa: BLE001
                degraded = True
                error = str(exc)
                logger.warning("%s LLM 循环失败，降级 | err=%s", self.spec.name, exc)
        else:
            degraded = True
            error = "llm_unavailable"

        result = self._run_fallback(task, context, observations, degraded=degraded, error=error)
        result.started_at = started
        result.finished_at = datetime.now(timezone.utc)
        self._emit_done(result, context)
        return result

    # ---- LLM ReAct 循环 ----

    def _run_llm(
        self,
        task: ResearchTask,
        context: AgentContext,
        observations: list[ToolObservation],
    ) -> AgentResult | None:
        assert self._llm is not None
        specs = self._tools.specs(self.spec.tools)
        tools_text = "\n".join(
            f"- {item['name']}: {item['description']} 参数: "
            f"{json.dumps(item.get('parameters', {}), ensure_ascii=False)}"
            for item in specs
        )
        schema = json.dumps(
            self.spec.output_model.model_json_schema(), ensure_ascii=False
        )[:3500]
        system = (
            f"{self.spec.system_prompt}\n\n"
            f"可用工具：\n{tools_text}\n\n"
            "每一步只输出一个 JSON：\n"
            '{"action":"tool","tool":"工具名","arguments":{...},"reason":"为什么调用"}\n'
            '或 {"action":"finish","output":{...结构化结论...}}\n'
            f"finish 的 output 必须符合以下 JSON Schema：\n{schema}\n"
            "所有事实性结论必须给出 evidence_ids（来自工具结果中的 Evidence ID）。"
            "没有证据的结论必须降低 confidence。不要编造证据 ID。"
        )
        evidence_text = context.evidence.render_for_prompt(limit=25, max_chars=5000)
        user = (
            f"研究任务：{task.objective}\n"
            f"县域：{context.county}\n产业方向：{context.focus or '待发现'}\n"
            f"研究轮次：{task.round}\n"
            f"已有证据（可直接引用）：\n{evidence_text}"
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        tool_calls = 0
        llm_calls = 0
        errors: list[str] = []

        while True:
            if llm_calls >= self.max_llm_calls:
                errors.append(f"llm_call_budget_exceeded({self.max_llm_calls})")
                break
            if tool_calls >= self.max_steps:
                errors.append(f"tool_step_budget_exceeded({self.max_steps})")
                break
            response = self._llm.chat(messages, temperature=0.1, max_tokens=2200)
            llm_calls += 1
            try:
                action = parse_json_object(response.content)
            except StructuredOutputError as exc:
                errors.append(f"unparseable_action: {exc}")
                messages.append({"role": "assistant", "content": response.content[:1500]})
                messages.append(
                    {
                        "role": "user",
                        "content": '输出无法解析。只输出一个 JSON：{"action":"tool",...} 或 {"action":"finish","output":{...}}。',
                    }
                )
                continue

            if str(action.get("action", "")).lower() == "finish" or "output" in action:
                output = action.get("output")
                if not isinstance(output, dict):
                    errors.append("finish_without_output")
                    continue
                result = self._build_result(
                    task, context, output, observations, llm_calls=llm_calls,
                    tool_calls=tool_calls, degraded=False, error="",
                )
                result.gaps.extend(errors)
                return result

            tool_name = str(action.get("tool", ""))
            arguments = action.get("arguments") or {}
            if not isinstance(arguments, dict):
                errors.append("tool_arguments_not_object")
                continue
            if tool_name not in self.spec.tools:
                errors.append(f"tool_not_allowed: {tool_name}")
                messages.append({"role": "assistant", "content": response.content[:1500]})
                messages.append(
                    {"role": "user", "content": f"工具 {tool_name} 不在允许列表，请改用 {list(self.spec.tools)}。"}
                )
                continue

            context.emit(
                EventType.AGENT_TOOL_CALL,
                f"{self.spec.name} 调用 {tool_name}",
                agent=self.spec.kind.value,
                tool=tool_name,
                arguments=arguments,
                reason=str(action.get("reason", ""))[:300],
            )
            observation = self._tools.execute(tool_name, arguments, context)
            observations.append(observation)
            tool_calls += 1
            context.emit(
                EventType.AGENT_TOOL_RESULT,
                f"{tool_name} {'成功' if observation.ok else '失败'}: {observation.summary[:160]}",
                agent=self.spec.kind.value,
                tool=tool_name,
                ok=observation.ok,
                evidence_ids=observation.evidence_ids[:20],
                error=observation.error[:300],
            )
            payload = json.dumps(
                observation.model_dump(mode="json"), ensure_ascii=False
            )[:3500]
            messages.append({"role": "assistant", "content": response.content[:1500]})
            messages.append(
                {
                    "role": "user",
                    "content": f"工具 {tool_name} 返回：\n{payload}\n\n继续下一步，或 finish。",
                }
            )

        # 预算耗尽：用已有观察做结构化降级
        partial = self._build_from_observations(task, context, observations)
        partial.llm_calls = llm_calls
        partial.tool_calls = tool_calls
        partial.degraded = True
        partial.error = "; ".join(errors)
        partial.gaps.extend(errors)
        return partial

    # ---- 确定性降级 ----

    def _run_fallback(
        self,
        task: ResearchTask,
        context: AgentContext,
        observations: list[ToolObservation],
        *,
        degraded: bool,
        error: str,
    ) -> AgentResult:
        context.emit(
            EventType.AGENT_TOOL_CALL,
            f"{self.spec.name} 使用确定性降级工具序列",
            agent=self.spec.kind.value,
            mode="fallback",
        )
        for call in self.spec.fallback_calls:
            tool_name = call.get("tool", "")
            if tool_name not in self.spec.tools:
                continue
            arguments = dict(call.get("arguments", {}))
            arguments = self._render_arguments(arguments, context)
            observation = self._tools.execute(tool_name, arguments, context)
            observations.append(observation)
            context.emit(
                EventType.AGENT_TOOL_RESULT,
                f"{tool_name} {'成功' if observation.ok else '失败'}: {observation.summary[:160]}",
                agent=self.spec.kind.value,
                tool=tool_name,
                ok=observation.ok,
                evidence_ids=observation.evidence_ids[:20],
            )
            if len(observations) >= self.max_steps:
                break
        result = self._build_from_observations(task, context, observations)
        result.degraded = degraded
        result.error = error
        return result

    @staticmethod
    def _render_arguments(arguments: dict[str, Any], context: AgentContext) -> dict[str, Any]:
        rendered: dict[str, Any] = {}
        for key, value in arguments.items():
            if isinstance(value, str):
                rendered[key] = value.format(
                    county=context.county,
                    focus=context.focus or "产业",
                )
            elif isinstance(value, list):
                rendered[key] = [
                    item.format(county=context.county, focus=context.focus or "产业")
                    if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                rendered[key] = value
        return rendered

    def _build_from_observations(
        self,
        task: ResearchTask,
        context: AgentContext,
        observations: list[ToolObservation],
    ) -> AgentResult:
        output: dict[str, Any] = {}
        if self.spec.fallback_builder is not None:
            try:
                output = self.spec.fallback_builder(self.spec, observations, context, task)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s fallback builder failed | err=%s", self.spec.name, exc)
                output = {"summary": f"{self.spec.name} 降级分析失败：{exc}"}
        if not output:
            output = {"summary": self._observations_summary(observations)}
        return self._build_result(
            task,
            context,
            output,
            observations,
            llm_calls=0,
            tool_calls=len(observations),
            degraded=True,
            error="",
        )

    @staticmethod
    def _observations_summary(observations: list[ToolObservation]) -> str:
        lines = []
        for obs in observations:
            lines.append(f"- {obs.tool}: {obs.summary}")
        return "\n".join(lines) or "（无工具结果）"

    # ---- 结果构造 ----

    def _build_result(
        self,
        task: ResearchTask,
        context: AgentContext,
        output: dict[str, Any],
        observations: list[ToolObservation],
        *,
        llm_calls: int,
        tool_calls: int,
        degraded: bool,
        error: str,
    ) -> AgentResult:
        claims: list[Claim] = []
        gaps: list[str] = [str(g) for g in output.get("gaps", []) if g]
        for entry in output.get("claims", []) or []:
            raw = {"text": entry} if isinstance(entry, str) else entry
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or raw.get("claim") or "").strip()
            if not text:
                continue
            check = check_claim_evidence(
                text,
                [str(i) for i in raw.get("evidence_ids", []) if i],
                context.evidence.get,
            )
            if check.unknown:
                gaps.append(f"claim references unknown evidence ids: {set(check.unknown)}")
            if check.unsupported:
                gaps.append(
                    "claim cites evidence that is not verified or does not support the claim: "
                    f"{set(check.unsupported)}"
                )
            if check.fully_supported:
                status = VerificationStatus.VERIFIED
            elif check.existing:
                # Evidence exists but has not been verified / does not directly
                # support the claim.  Keep the IDs for traceability but never
                # mark the claim as a verified fact.
                status = VerificationStatus.PENDING
            else:
                status = VerificationStatus.UNVERIFIED
            claims.append(
                Claim(
                    claim_id=f"{task.task_id}-c{len(claims) + 1}",
                    text=text,
                    evidence_ids=check.existing,
                    confidence=float(raw.get("confidence", 0.5) or 0.5),
                    verification_status=status,
                    source_agent=self.spec.kind.value,
                )
            )
        if not claims:
            gaps.append("agent produced no evidence-bound claims")

        observation_ids = list(
            dict.fromkeys(i for obs in observations for i in obs.evidence_ids if i)
        )
        valid_observation_ids = [
            i for i in observation_ids if context.evidence.get(i) is not None
        ]
        if len(valid_observation_ids) != len(observation_ids):
            gaps.append(
                "tool observations referenced unknown evidence ids: "
                f"{set(observation_ids) - set(valid_observation_ids)}"
            )
        evidence_ids = list(valid_observation_ids)
        for claim in claims:
            evidence_ids.extend(claim.evidence_ids)
        evidence_ids = list(dict.fromkeys(evidence_ids))
        findings = {
            k: v
            for k, v in output.items()
            if k not in {"claims", "summary", "gaps", "confidence", "metrics"}
        }
        confidence = output.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = (
                round(sum(c.confidence for c in claims) / len(claims), 3)
                if claims
                else 0.3
            )
        metrics = output.get("metrics") if isinstance(output.get("metrics"), dict) else {}
        return AgentResult(
            task_id=task.task_id,
            agent=self.spec.kind,
            summary=str(output.get("summary", ""))[:2000],
            claims=claims,
            evidence_ids=evidence_ids,
            findings=findings,
            confidence=max(0.0, min(float(confidence), 1.0)),
            gaps=gaps,
            metrics=metrics,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            degraded=degraded,
            error=error,
        )

    def _emit_done(self, result: AgentResult, context: AgentContext) -> None:
        # 降级完成仍然是"完成"；只有完全没有产出（无摘要且无结论）才算失败。
        failed = not result.summary and not result.claims
        context.emit(
            EventType.AGENT_FAILED if failed else EventType.AGENT_COMPLETED,
            f"{self.spec.name} 完成：{len(result.claims)} 条结论、"
            f"{len(result.evidence_ids)} 个证据引用"
            + ("（降级）" if result.degraded else ""),
            agent=self.spec.kind.value,
            task_id=result.task_id,
            claims=len(result.claims),
            evidence=len(result.evidence_ids),
            degraded=result.degraded,
            error=result.error[:300],
        )


def timed(fn: Callable[[], ToolObservation]) -> ToolObservation:
    started = time.perf_counter()
    observation = fn()
    observation.elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
    return observation


__all__ = ["AgentContext", "AgentSpec", "SpecialistAgent", "ToolObservation", "timed"]
