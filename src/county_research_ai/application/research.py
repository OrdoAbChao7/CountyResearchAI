"""Workflow 与 Agent 共用的研究应用用例。"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from socket import timeout as SocketTimeout
from typing import NoReturn

from ..domain.modes import normalize_mode
from ..domain.research_contracts import QuestionSlot, ResearchSpec
from ..evidence.ledger import build_evidence_ledger
from ..exceptions import ResearchStageError
from ..models import ProcessedData
from ..modes.registry import ModeRegistry
from ..ports.discovery import DiscoveryPort
from ..ports.processing import ProcessingPort
from ..ports.reporting import FilenameRenderer
from ..ports.search import SearchPort
from ..ports.storage import StoragePort
from .config import ResearchApplicationConfig
from .context import ResearchContext
from .results import ResearchRunResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchApplication:
    def __init__(
        self,
        *,
        search: SearchPort,
        storage: StoragePort,
        processor: ProcessingPort,
        discovery: DiscoveryPort,
        modes: ModeRegistry,
        config: ResearchApplicationConfig,
        render_filename: FilenameRenderer,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.search = search
        self.storage = storage
        self.processor = processor
        self.discovery = discovery
        self.modes = modes
        self.config = config
        self.render_filename = render_filename
        self.clock = clock

    def collect_materials(self, context: ResearchContext) -> ResearchContext:
        try:
            docs = self.search.collect(
                context.county.display(),
                context.focus,
                self.config.max_search_results,
                mode=normalize_mode(context.request.mode),
            )
            return context.model_copy(update={"raw_docs": docs})
        except Exception as exc:  # noqa: BLE001
            self._raise_stage("collect", context, exc)

    def discover_focus(self, context: ResearchContext) -> ResearchContext:
        try:
            handler = self.modes.get(normalize_mode(context.request.mode))
            discovery = self.discovery.discover_focus(
                county=context.county,
                raw_docs=context.raw_docs,
            )
            # An explicit contract focus is authoritative. Discovery still runs
            # so its candidates can be shown, but it must not replace a focus
            # the caller already chose (notably on the API/JobRunner path).
            explicit_focus = (context.request.focus or "").strip()
            focus = explicit_focus or discovery.selected_focus or handler.default_focus
            request = context.request.model_copy(update={"focus": focus})
            return context.model_copy(
                update={"discovery": discovery, "focus": focus, "request": request}
            )
        except Exception as exc:  # noqa: BLE001
            self._raise_stage("discover", context, exc)

    def build_evidence(self, context: ResearchContext) -> ResearchContext:
        try:
            focus = context.focus or context.request.focus or "特色农业"
            no_cache = bool(context.request.options.get("no_cache"))
            cache_hours = (
                self.config.cache_ttl_hours
                if self.config.cache_enabled and not no_cache
                else 0
            )
            if cache_hours > 0:
                cached = self.storage.load_processed(
                    context.county.name,
                    focus,
                    max_age_hours=cache_hours,
                )
                if cached is not None:
                    return self._attach_structured_evidence(context, cached, focus)

            processed = self.processor.process(
                context.raw_docs,
                county=context.county,
                focus=focus,
            )
            structured_context = self._attach_structured_evidence(context, processed, focus)
            self.storage.save_raw(context.county.name, context.raw_docs)
            self.storage.save_processed(
                context.county.name,
                focus,
                structured_context.processed or processed,
            )
            return structured_context
        except Exception as exc:  # noqa: BLE001
            self._raise_stage("process", context, exc)

    @staticmethod
    def _attach_structured_evidence(
        context: ResearchContext,
        processed: ProcessedData,
        focus: str,
    ) -> ResearchContext:
        mode = normalize_mode(context.request.mode)
        research_spec = ResearchSpec(
            region_id=context.county.name,
            region_name=context.county.name,
            research_focus=focus,
            mode=mode,
            architecture_version="evidence_first_v2",
            required_question_slots=[
                QuestionSlot(
                    slot_id=f"legacy:{mode}:overview",
                    research_question=f"{context.county.name} 的 {focus} 研究概览",
                    region=context.county.name,
                    budget_chars=12000,
                )
            ],
        )
        evidence_ledger = build_evidence_ledger(processed)
        evidence_pack = evidence_ledger.select_evidence_pack(
            research_spec.required_question_slots[0]
        )
        processed = processed.model_copy(update={"evidence_pack": evidence_pack})
        return context.model_copy(
            update={
                "focus": focus,
                "processed": processed,
                "research_spec": research_spec,
                "evidence_ledger": evidence_ledger,
                "evidence_pack": evidence_pack,
                "evidence_packs": [evidence_pack],
            }
        )

    def analyze(self, context: ResearchContext) -> ResearchContext:
        try:
            handler = self.modes.get(normalize_mode(context.request.mode))
            return handler.analyze(context)
        except Exception as exc:  # noqa: BLE001
            self._raise_stage("analyze", context, exc)

    def render_report(self, context: ResearchContext) -> ResearchRunResult:
        try:
            handler = self.modes.get(normalize_mode(context.request.mode))
            rendered = handler.render(context)
            date_str = self.clock().astimezone(timezone.utc).strftime("%Y%m%d")
            filename = self.render_filename(
                self.config.report_filename_template,
                {
                    "county": context.county.name,
                    "focus": context.focus,
                    "date": date_str,
                },
            )
            report_path = self.storage.save_report(filename, rendered.markdown)
            return ResearchRunResult(
                report=rendered.report,
                report_path=report_path,
                markdown=rendered.markdown,
            )
        except Exception as exc:  # noqa: BLE001
            self._raise_stage("report", context, exc)

    @staticmethod
    def _raise_stage(stage: str, context: ResearchContext, exc: Exception) -> NoReturn:
        if isinstance(exc, ResearchStageError):
            raise exc
        status_code = getattr(exc, "status_code", None)
        if status_code is None and hasattr(exc, "context"):
            status_code = getattr(exc, "context", {}).get("status_code")
        retryable = status_code in {408, 429, 500, 502, 503, 504} or isinstance(
            exc, (TimeoutError, SocketTimeout, ConnectionError)
        )
        safe_context: dict[str, object] = {
            "county": context.county.name,
            "focus": context.focus or context.request.focus or "",
            "mode": context.request.mode,
        }
        if isinstance(status_code, int):
            safe_context["status_code"] = status_code
        raise ResearchStageError(
            f"research stage failed: {stage}",
            code=f"{stage}_failed",
            stage=stage,
            retryable=retryable,
            context=safe_context,
        ) from exc
