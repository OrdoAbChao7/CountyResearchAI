"""有界的 Plan-and-Execute Agent Runtime。"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from ..models import ResearchRequest
from .base import ToolResult
from .models import (
    AgentError,
    AgentObservation,
    AgentRunResult,
    AgentState,
    AgentStatus,
    AgentTrace,
    ToolStatus,
)
from .planner import Planner
from .registry import AgentToolError, ToolRegistry
from .trace import TraceStore
from .verifier import AgentVerifier


class AgentRuntime:
    """协调 Planner、工具、Verifier 和 TraceStore 的单次运行器。"""

    def __init__(
        self,
        *,
        planner: Planner,
        registry: ToolRegistry,
        verifier: AgentVerifier,
        trace_store: TraceStore | None = None,
        max_steps: int = 8,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.planner = planner
        self.registry = registry
        self.verifier = verifier
        self.trace_store = trace_store
        self.max_steps = max_steps

    def run(self, request: ResearchRequest) -> AgentRunResult:
        state = AgentState.from_request(request)
        state.status = AgentStatus.RUNNING
        trace = AgentTrace(request=state.request, status=AgentStatus.RUNNING)
        failure_code = ""

        while state.steps_used < self.max_steps:
            step_index = state.steps_used + 1
            try:
                step = self.planner.next_step(state, self.registry.describe())
            except Exception as exc:  # noqa: BLE001
                failure_code = "planner_error"
                self._record_error(
                    state,
                    code=failure_code,
                    message=str(exc),
                    step_index=step_index,
                )
                break

            state.current_step = step_index
            state.steps_used = step_index
            state.plan.append(step)

            if step.tool == "finish" or step.is_final:
                verification = self.verifier.verify_final(state)
                status = ToolStatus.SUCCESS if verification.ok else ToolStatus.ERROR
                self._record_observation(
                    state,
                    step_index=step_index,
                    tool_name="finish",
                    status=status,
                    reason=step.reason,
                    input_summary=self._summarize(step.arguments),
                    output_summary=verification.message or "final verification passed",
                    error="" if verification.ok else verification.message,
                    elapsed_ms=0,
                )
                if verification.ok:
                    state.status = AgentStatus.COMPLETED
                    return self._finish(state, trace, failure_code="")
                failure_code = verification.code or "final_verification_failed"
                self._record_error(
                    state,
                    code=failure_code,
                    message=verification.message,
                    step_index=step_index,
                )
                break

            started = time.perf_counter()
            try:
                tool = self.registry.get(step.tool)
            except AgentToolError as exc:
                elapsed_ms = self._elapsed_ms(started)
                self._record_error(
                    state,
                    code="invalid_tool",
                    message=str(exc),
                    tool_name=step.tool,
                    step_index=step_index,
                )
                self._record_observation(
                    state,
                    step_index=step_index,
                    tool_name=step.tool,
                    status=ToolStatus.ERROR,
                    reason=step.reason,
                    input_summary=self._summarize(step.arguments),
                    output_summary="tool is not registered",
                    error=str(exc),
                    elapsed_ms=elapsed_ms,
                )
                continue

            try:
                result = tool.execute(state, step.arguments)
            except Exception as exc:  # noqa: BLE001
                result = ToolResult(
                    tool_name=step.tool,
                    status=ToolStatus.ERROR,
                    observation="tool raised an exception",
                    error=str(exc),
                )
                self._record_error(
                    state,
                    code="tool_exception",
                    message=str(exc),
                    tool_name=step.tool,
                    step_index=step_index,
                )

            if result.status == ToolStatus.SUCCESS:
                try:
                    state.apply_patch(result.state_patch)
                except Exception as exc:  # noqa: BLE001
                    result = result.model_copy(
                        update={
                            "status": ToolStatus.ERROR,
                            "error": f"invalid state patch: {exc}",
                        }
                    )
                    self._record_error(
                        state,
                        code="state_patch_error",
                        message=str(exc),
                        tool_name=step.tool,
                        step_index=step_index,
                    )

            verification = self.verifier.verify_step(state, step, result)
            elapsed_ms = self._elapsed_ms(started)
            observation_status = result.status
            observation_error = result.error
            if not verification.ok:
                observation_status = ToolStatus.ERROR
                observation_error = verification.message
                self._record_error(
                    state,
                    code=verification.code or "step_verification_failed",
                    message=verification.message,
                    tool_name=step.tool,
                    step_index=step_index,
                )
                if verification.fatal:
                    failure_code = verification.code or "fatal_step_verification"
                    self._record_observation(
                        state,
                        step_index=step_index,
                        tool_name=step.tool,
                        status=observation_status,
                        reason=step.reason,
                        input_summary=self._summarize(step.arguments),
                        output_summary=result.observation,
                        error=observation_error,
                        elapsed_ms=elapsed_ms,
                    )
                    break

            if result.status != ToolStatus.SUCCESS and not result.error:
                self._record_error(
                    state,
                    code="tool_error",
                    message=result.observation,
                    tool_name=step.tool,
                    step_index=step_index,
                )
            self._record_observation(
                state,
                step_index=step_index,
                tool_name=step.tool,
                status=observation_status,
                reason=step.reason,
                input_summary=self._summarize(step.arguments),
                output_summary=result.observation,
                error=observation_error,
                elapsed_ms=elapsed_ms,
            )

        if not failure_code:
            failure_code = "max_steps_exceeded"
            self._record_error(
                state,
                code=failure_code,
                message=f"Agent exceeded max_steps={self.max_steps}",
                step_index=state.steps_used,
            )
        state.status = AgentStatus.FAILED
        return self._finish(state, trace, failure_code=failure_code)

    def _finish(self, state: AgentState, trace: AgentTrace, *, failure_code: str) -> AgentRunResult:
        trace.request = state.request
        trace.status = state.status
        trace.completed_at = datetime.now(timezone.utc)
        trace.observations = list(state.observations)
        trace.errors = list(state.errors)
        trace.report_path = state.report_path
        trace.failure_code = failure_code
        trace_path = self.trace_store.save(trace) if self.trace_store else None
        report_path = state.report_path or None
        return AgentRunResult(
            state=state,
            trace=trace,
            report_path=report_path,
            trace_path=trace_path,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, int((time.perf_counter() - started) * 1000))

    @staticmethod
    def _summarize(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)[:500]

    @staticmethod
    def _record_error(
        state: AgentState,
        *,
        code: str,
        message: str,
        tool_name: str = "",
        step_index: int | None = None,
    ) -> None:
        state.errors.append(
            AgentError(
                code=code,
                message=message,
                tool_name=tool_name,
                step_index=step_index,
            )
        )

    @staticmethod
    def _record_observation(
        state: AgentState,
        *,
        step_index: int,
        tool_name: str,
        status: ToolStatus,
        reason: str,
        input_summary: str,
        output_summary: str,
        error: str,
        elapsed_ms: int,
    ) -> None:
        state.observations.append(
            AgentObservation(
                step_index=step_index,
                tool_name=tool_name,
                status=status,
                reason=reason,
                input_summary=input_summary,
                output_summary=output_summary[:500],
                error=error[:500],
                elapsed_ms=elapsed_ms,
            )
        )
