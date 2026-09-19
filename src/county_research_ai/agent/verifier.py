"""Agent 中间结果和最终报告校验。"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from .base import ToolResult
from .models import AgentPlanStep, AgentState, ToolStatus


class VerificationResult(BaseModel):
    ok: bool
    fatal: bool = False
    code: str = ""
    message: str = ""


class AgentVerifier:
    """只校验结构、状态和证据链，不替代人工事实核验。"""

    def verify_step(
        self,
        state: AgentState,
        step: AgentPlanStep,
        result: ToolResult,
    ) -> VerificationResult:
        if result.status != ToolStatus.SUCCESS:
            return VerificationResult(
                ok=False,
                fatal=result.error.startswith("fatal:"),
                code="tool_error",
                message=result.error or result.observation,
            )

        requirements = {
            "search_materials": bool(state.raw_docs) or "empty" in result.observation.lower(),
            "discover_focus": bool(state.request.focus),
            "build_evidence_pack": state.processed is not None,
            "analyze_research": self._has_analysis(state),
            "render_report": bool(state.report_path),
            "finish": True,
        }
        if step.tool in requirements and not requirements[step.tool]:
            return VerificationResult(
                ok=False,
                code=f"{step.tool}_incomplete",
                message=f"tool completed without expected state: {step.tool}",
            )
        return VerificationResult(ok=True)

    def verify_final(self, state: AgentState) -> VerificationResult:
        if not state.report_path:
            return VerificationResult(
                ok=False, fatal=False, code="missing_report", message="报告路径为空"
            )
        path = Path(state.report_path)
        if not path.is_file():
            return VerificationResult(
                ok=False, fatal=False, code="report_not_found", message=str(path)
            )
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            return VerificationResult(
                ok=False, fatal=True, code="report_read_error", message=str(exc)
            )
        if state.request.county not in content:
            return VerificationResult(
                ok=False, code="county_missing", message="报告不包含县名"
            )
        focus = state.request.focus or self._default_focus(state.request.mode)
        if focus and focus not in content:
            return VerificationResult(
                ok=False, code="focus_missing", message="报告不包含研究方向"
            )
        if not re.search(r"https?://", content) and not any(
            marker in content for marker in ("资料不足", "数据不足", "无来源")
        ):
            return VerificationResult(
                ok=False,
                code="evidence_missing",
                message="报告没有来源 URL 或资料不足标记",
            )
        if any(error.code.startswith("fatal_") for error in state.errors):
            return VerificationResult(
                ok=False,
                fatal=True,
                code="fatal_error_present",
                message="存在未处理 fatal error",
            )
        return VerificationResult(ok=True)

    @staticmethod
    def _has_analysis(state: AgentState) -> bool:
        if state.request.mode in {"snapshot", "industry"}:
            return bool(state.snapshot_analyses)
        if state.request.mode == "rise-fall":
            return state.rise_fall_analysis is not None
        return state.long_history_analysis is not None

    @staticmethod
    def _default_focus(mode: str) -> str:
        return {
            "rise-fall": "兴衰规律",
            "long-history": "长周期兴衰史",
        }.get(mode, "")
