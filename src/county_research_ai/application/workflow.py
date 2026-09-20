"""研究工作流的唯一阶段编排入口。"""
from __future__ import annotations

from typing import Protocol

from ..config import PipelineStages
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

    def run(self, request: ResearchRequest) -> ResearchRunResult:
        context = ResearchContext.from_request(request)
        if self.stages.search:
            context = self.application.collect_materials(context)

        if not context.focus and not context.request.focus:
            context = self.application.discover_focus(context)

        if self.stages.process:
            context = self.application.build_evidence(context)
        if self.stages.analyze:
            context = self.application.analyze(context)
        if self.stages.report:
            return self.application.render_report(context)

        # A report is the public result of a pipeline run. The disabled-report
        # path remains explicit so callers get a useful configuration error.
        raise RuntimeError("report stage is disabled; no ResearchRunResult exists")
