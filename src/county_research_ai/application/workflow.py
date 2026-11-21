"""研究工作流的唯一阶段编排入口。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..config import PipelineStages
from ..exceptions import ResearchCancelledError
from ..models import ResearchRequest
from .context import ResearchContext
from .results import ResearchRunResult


class ResearchApplicationPort(Protocol):
    def collect_materials(self, context: ResearchContext) -> ResearchContext: ...

    def discover_focus(self, context: ResearchContext) -> ResearchContext: ...

    def build_evidence(self, context: ResearchContext) -> ResearchContext: ...

    def analyze(self, context: ResearchContext) -> ResearchContext: ...

    def render_report(self, context: ResearchContext) -> ResearchRunResult: ...


class WorkflowRunner:
    """按配置顺序驱动 ResearchApplication，不承载具体业务实现。"""

    def __init__(
        self,
        *,
        application: ResearchApplicationPort,
        stages: PipelineStages | None = None,
        fail_fast: bool = True,
    ) -> None:
        self.application = application
        self.stages = stages or PipelineStages()
        self.fail_fast = fail_fast

    def run(
        self,
        request: ResearchRequest,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ResearchRunResult:
        context = ResearchContext.from_request(request)

        def check(stage: str) -> None:
            if should_cancel is not None and should_cancel():
                raise ResearchCancelledError(stage)

        if self.stages.search:
            check("collect")
            context = self.application.collect_materials(context)

        if not context.focus and not context.request.focus:
            check("discover")
            context = self.application.discover_focus(context)

        if self.stages.process:
            check("evidence")
            context = self.application.build_evidence(context)
        if self.stages.analyze:
            check("analyze")
            context = self.application.analyze(context)
        if self.stages.report:
            check("report")
            result = self.application.render_report(context)
            context = context.model_copy(
                update={"report": result.report, "report_path": result.report_path}
            )
            return result.model_copy(update={"context": context})

        # A report is the public result of a pipeline run. The disabled-report
        # path remains explicit so callers get a useful configuration error.
        raise RuntimeError("report stage is disabled; no ResearchRunResult exists")

    @staticmethod
    def _raise_if_cancelled(
        should_cancel: Callable[[], bool] | None,
        stage: str,
    ) -> None:
        if should_cancel is not None and should_cancel():
            raise ResearchCancelledError(stage)
