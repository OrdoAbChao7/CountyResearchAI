"""Background execution for local research jobs.

Runs are executed in-process by a small thread pool. That is adequate for a
single-node demo, but it is not a distributed queue: a process crash leaves the
job ``INTERRUPTED`` in the durable store and it must be resumed explicitly.
Cancellation and deadline checks happen between stages, not inside a single LLM
or search call.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from ..application.context import ResearchContext
from ..bootstrap.container import create_app_container
from ..config import Settings, get_settings
from ..domain.outcomes import ResearchOutcome
from ..evidence.graph import EvidenceGraphStore, VerificationStatus
from ..models import ResearchRequest
from ..observability import pop_event_sink, push_event_sink
from .event_sink import JobEventSink
from .evidence_service import persist_run_evidence, thresholds_met
from .jobs import JobRecord, JobStatus, JobStore

logger = logging.getLogger(__name__)


class _Cancelled(Exception):
    pass


class _BudgetExceeded(Exception):
    pass


class _LeaseLost(Exception):
    pass


def force_mock_settings(settings: Settings) -> Settings:
    """Return settings with provider keys cleared so adapters fall back to mocks."""
    return settings.model_copy(
        update={
            "llm": settings.llm.model_copy(update={"api_key": SecretStr("")}),
            "search": settings.search.model_copy(update={"api_key": SecretStr("")}),
        }
    )


class JobRunner:
    def __init__(
        self,
        store: JobStore,
        *,
        data_dir: Path,
        reports_dir: Path,
        evidence_db_path: Path,
        settings: Settings | None = None,
        live_enabled: bool = False,
        max_workers: int = 1,
    ) -> None:
        self.store = store
        self.data_dir = Path(data_dir)
        self.reports_dir = Path(reports_dir)
        self.evidence_db_path = Path(evidence_db_path)
        self.settings = settings or get_settings()
        self.live_enabled = live_enabled
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="axiomscope-job"
        )

    @property
    def mode_label(self) -> str:
        has_keys = bool(self.settings.llm.api_key.get_secret_value()) and bool(
            self.settings.search.api_key.get_secret_value()
        )
        if self.live_enabled and has_keys:
            return "LIVE"
        return "MOCK"

    def submit(self, job_id: str) -> None:
        self._executor.submit(self.execute, job_id)

    def shutdown(self, *, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)

    # -------------------------------------------------------------- execution

    def execute(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if job is None or job.status.terminal:
            return
        started = time.monotonic()
        owner = f"worker:{uuid.uuid4().hex}"
        lease_seconds = max(
            30.0,
            min(300.0, float(job.contract.budget.deadline_seconds or 60.0)),
        )
        fencing_token = self.store.claim_for_execution(
            job_id, owner=owner, lease_seconds=lease_seconds
        )
        if fencing_token is None:
            return
        lost = threading.Event()
        stop_heartbeat = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(job_id, owner, fencing_token, lease_seconds, stop_heartbeat, lost),
            name=f"lease-heartbeat-{job_id}",
            daemon=True,
        )
        heartbeat.start()
        sink_token = push_event_sink(JobEventSink(self.store, job_id))
        try:
            self.store.append_event(
                job_id, "job.started", {"mode_label": job.mode_label}
            )
            graph = EvidenceGraphStore(self.evidence_db_path)
            graph.clear_run(job_id)
            context = ResearchContext.from_request(
                ResearchRequest(
                    county=job.contract.regions[0],
                    focus=job.contract.research_focus or None,
                    mode=job.contract.mode,
                    options={**job.contract.options, "no_cache": True},
                )
            )
            container = self._container(job)
            app = container.application
            self._demo_delay(job, started, lost)
            context = self._stage(
                job, "collect", context, app.collect_materials, started, lost, lambda ctx: {
                    "documents": len(ctx.raw_docs)
                }
            )
            context = self._stage(
                job, "discover", context, app.discover_focus, started, lost, lambda ctx: {
                    "focus": ctx.focus
                }
            )
            context = self._stage(
                job, "evidence", context, app.build_evidence, started, lost, lambda ctx: {
                    "packs": len(ctx.evidence_packs),
                    "chunks": len(ctx.evidence_ledger.chunks) if ctx.evidence_ledger else 0,
                }
            )
            context = self._stage(
                job, "analyze", context, app.analyze, started, lost, lambda ctx: {
                    "sections": len(ctx.report.sections) if ctx.report else 0,
                    "deep_research": ctx.deep_research is not None,
                }
            )
            deep = getattr(context, "deep_research", None)
            summary = self._persist(job, graph, context, deep=deep)
            deep_projection = self._deep_projection(deep)
            self.store.append_event(
                job.job_id, "evidence.persisted", {**summary, "deep_research": deep_projection["enabled"]}
            )
            result = self._stage(
                job, "report", context, app.render_report, started, lost, lambda res: {
                    "report_path": str(res.report_path)
                }
            )
            self.store.append_event(
                job_id,
                "report.rendered",
                {
                    "sections": result.report.section_count,
                    "markdown_chars": len(result.markdown),
                    "provenance": (
                        "native_sections"
                        if job.mode == "snapshot"
                        else "markdown_split"
                    ),
                },
            )
            self._ensure_active(job_id, started, lost)
            enforcement = self._budget_enforcement(job, started)
            outcome, reason = self._outcome(job, summary)
            finished = self.store.finish_job(
                job_id,
                JobStatus.SUCCEEDED,
                outcome=outcome,
                outcome_reason=reason,
                event_type="job.completed",
                event_payload={"outcome": outcome.value, "reason": reason},
                owner=owner,
                fencing_token=fencing_token,
                report_path=str(result.report_path),
                result={
                    "evidence": summary,
                    "sections": result.report.section_count,
                    "mode_label": job.mode_label,
                    "deep_research": deep_projection,
                },
                budget_enforcement=enforcement,
            )
            if not finished:
                logger.warning("stale worker result ignored for job %s", job_id)
        except _LeaseLost:
            logger.warning("lease lost for job %s; result ignored", job_id)
        except _Cancelled:
            self._finish_lease(
                job_id,
                JobStatus.CANCELLED,
                outcome=ResearchOutcome.CANCELLED,
                outcome_reason="cancel_requested",
                event_type="job.cancelled",
                event_payload={"reason": "cancel_requested"},
                owner=owner,
                fencing_token=fencing_token,
            )
        except _BudgetExceeded:
            self._finish_lease(
                job_id,
                JobStatus.BUDGET_EXHAUSTED,
                outcome=ResearchOutcome.BUDGET_EXHAUSTED,
                outcome_reason="deadline_exceeded",
                event_type="budget.exhausted",
                event_payload={"reason": "deadline_exceeded"},
                budget_enforcement=self._budget_enforcement(job, started),
                owner=owner,
                fencing_token=fencing_token,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("research job %s failed", job_id)
            self._finish_lease(
                job_id,
                JobStatus.FAILED,
                outcome=ResearchOutcome.FAILED,
                outcome_reason="execution_error",
                event_type="job.failed",
                event_payload={"code": type(exc).__name__},
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
                budget_enforcement=self._budget_enforcement(job, started),
                owner=owner,
                fencing_token=fencing_token,
            )
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=1.0)
            pop_event_sink(sink_token)

    def _demo_delay(
        self, job: JobRecord, started: float, lost: threading.Event
    ) -> None:
        """Optional MOCK-only stage delay for deterministic browser cancel tests."""
        raw = os.getenv("AXIOMSCOPE_MOCK_STAGE_DELAY_SECONDS", "0")
        try:
            delay = min(10.0, max(0.0, float(raw)))
        except ValueError:
            delay = 0.0
        if delay <= 0 or job.mode_label != "MOCK":
            return
        end = time.monotonic() + delay
        while time.monotonic() < end:
            self._ensure_active(job.job_id, started, lost)
            time.sleep(0.1)

    def _heartbeat(
        self,        job_id: str,
        owner: str,
        fencing_token: int,
        lease_seconds: float,
        stop: threading.Event,
        lost: threading.Event,
    ) -> None:
        interval = max(1.0, lease_seconds / 3.0)
        while not stop.wait(interval):
            if not self.store.renew_lease(
                job_id,
                owner=owner,
                fencing_token=fencing_token,
                lease_seconds=lease_seconds,
            ):
                lost.set()
                return

    def _finish_lease(self, job_id: str, status: JobStatus, **kwargs) -> None:
        if not self.store.finish_job(job_id, status, **kwargs):
            logger.warning("stale worker terminal write ignored for job %s", job_id)

    def _container(self, job: JobRecord):
        contract = job.contract
        settings = self.settings
        if not self.live_enabled:
            settings = force_mock_settings(settings)
        job_data_dir = self.data_dir / "api_jobs" / job.job_id
        job_reports_dir = self.reports_dir / "api_jobs" / job.job_id
        llm = settings.llm
        if contract.budget.max_tokens:
            llm = llm.model_copy(
                update={"max_tokens": min(llm.max_tokens, contract.budget.max_tokens)}
            )
        storage = settings.storage.model_copy(
            update={
                "data_dir": str(job_data_dir),
                "reports_dir": str(job_reports_dir),
            }
        )
        settings = settings.model_copy(
            update={
                "llm": llm,
                "storage": storage,
                "data_dir": job_data_dir,
                "reports_dir": job_reports_dir,
            }
        )
        container = create_app_container(settings=settings)
        if contract.budget.max_documents:
            container.application.config = dataclasses.replace(
                container.application.config,
                max_search_results=min(
                    container.application.config.max_search_results,
                    contract.budget.max_documents,
                ),
            )
        return container

    def _persist(
        self,
        job: JobRecord,
        graph: EvidenceGraphStore,
        context: ResearchContext,
        *,
        deep: Any | None = None,
    ) -> dict[str, Any]:
        ledger = getattr(deep, "evidence_ledger", None) or context.evidence_ledger
        deep_packs = list(getattr(deep, "evidence_packs", None) or [])
        packs = deep_packs or context.evidence_packs or (
            [context.evidence_pack] if context.evidence_pack is not None else []
        )
        if ledger is None:
            return {
                "claims": 0,
                "supported_claims": 0,
                "independent_sources": 0,
                "supported_ratio": 0.0,
                "status_counts": {},
                "snapshots": 0,
                "spans": 0,
                "skipped": "no_evidence_ledger",
            }
        return persist_run_evidence(
            graph, ledger, packs, run_id=job.job_id, contract=job.contract
        )

    @staticmethod
    def _deep_projection(deep: Any | None) -> dict[str, Any]:
        if deep is None:
            return {"enabled": False}
        question_tree = getattr(deep, "question_tree", None)
        return {
            "enabled": True,
            "coverage_rate": getattr(deep, "coverage_rate", None),
            "total_turns": getattr(deep, "total_turns", 0),
            "reflection_turns": len(getattr(deep, "reflection_history", []) or []),
            "retrieval_stop_reason": getattr(deep, "retrieval_stop_reason", ""),
            "retrieval_usage": getattr(deep, "retrieval_usage", {}) or {},
            "question_tree": (
                question_tree.model_dump(mode="json") if question_tree is not None else None
            ),
            "conflicts": [
                conflict.model_dump(mode="json")
                for conflict in getattr(deep, "conflicts", []) or []
            ],
            "gaps": [
                gap.model_dump(mode="json")
                for gap in getattr(deep, "gaps", []) or []
            ],
        }

    def _stage(
        self,
        job: JobRecord,
        name: str,
        context: Any,
        function,
        started: float,
        lost: threading.Event,
        summarize,
    ):
        self._ensure_active(job.job_id, started, lost)
        self.store.append_event(job.job_id, f"stage.{name}.started", {})
        began = time.monotonic()
        value = function(context)
        elapsed_ms = int((time.monotonic() - began) * 1000)
        self.store.append_event(
            job.job_id,
            f"stage.{name}.completed",
            {"elapsed_ms": elapsed_ms, **summarize(value)},
        )
        return value

    def _ensure_active(
        self,
        job_id: str,
        started: float,
        lost: threading.Event | None = None,
    ) -> None:
        if lost is not None and lost.is_set():
            raise _LeaseLost
        if self.store.is_cancel_requested(job_id):
            raise _Cancelled
        job = self.store.get_job(job_id)
        if job is None:
            raise _Cancelled
        deadline = job.contract.budget.deadline_seconds
        if deadline and time.monotonic() - started > deadline:
            raise _BudgetExceeded

    def _budget_enforcement(
        self, job: JobRecord, started: float
    ) -> dict[str, Any]:
        budget = job.contract.budget
        enforced: list[str] = []
        bounded_per_call: list[str] = []
        not_enforced: list[str] = ["max_steps", "max_search_calls", "max_cost"]
        if budget.deadline_seconds:
            enforced.append("deadline_seconds")
        if budget.max_tokens:
            bounded_per_call.append("max_tokens")
        if budget.max_documents:
            bounded_per_call.append("max_documents")
        return {
            "enforced": enforced,
            "bounded_per_call": bounded_per_call,
            "not_enforced_on_workflow_path": not_enforced,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "deadline_seconds": budget.deadline_seconds,
        }

    @staticmethod
    def _outcome(
        job: JobRecord, summary: dict[str, Any]
    ) -> tuple[ResearchOutcome, str]:
        if summary.get("claims", 0) == 0:
            return ResearchOutcome.NO_PROGRESS, "no_structured_claims"
        status_counts = summary.get("status_counts", {})
        if status_counts.get(VerificationStatus.NEEDS_REVIEW.value, 0):
            return ResearchOutcome.CONFLICT_UNRESOLVED, "conflicting_supported_evidence"
        met, failures = thresholds_met(job.contract, summary)
        supported = int(summary.get("supported_claims", 0))
        if met and supported > 0:
            return ResearchOutcome.SUFFICIENT, "evidence_thresholds_met"
        if supported == 0:
            return ResearchOutcome.NO_PROGRESS, "no_supported_claims"
        return ResearchOutcome.NEEDS_HUMAN_REVIEW, ";".join(failures)
