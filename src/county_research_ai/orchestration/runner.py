"""研究运行服务：后台执行、运行记录、事件、报告与恢复。

FastAPI 与测试都通过这一层启动研究，不直接操作 LangGraph。
"""
from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agents.base import AgentContext
from ..domain.events import EventType
from ..domain.intelligence import (
    AgentResult,
    CritiqueReport,
    OpportunityCandidate,
    ResearchPlan,
    ResearchRunRecord,
    ResearchRunRequest,
    RunStatus,
)
from .artifacts import RunArtifacts
from .checkpoint import create_checkpointer, run_config, state_values
from .events import RunEventStore
from .graph import build_research_graph
from .services import OrchestrationServices
from .state import initial_state

logger = logging.getLogger(__name__)


class RunServiceError(RuntimeError):
    """运行服务基类异常。"""


class RunNotFound(RunServiceError):
    pass


class ResumeUnavailable(RunServiceError):
    pass


class ResearchRunService:
    def __init__(
        self,
        services: OrchestrationServices,
        *,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.services = services
        self.settings = services.settings
        self.runs_dir = Path(self.settings.runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._records: dict[str, ResearchRunRecord] = {}
        self._events: dict[str, RunEventStore] = {}
        self._futures: dict[str, Future[Any]] = {}
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(
            max_workers=max(1, int(self.settings.api.max_concurrent_runs)),
            thread_name_prefix="research-run",
        )
        self._checkpointer, self.checkpoint_backend = create_checkpointer(
            self.runs_dir / "checkpoints.sqlite"
        )
        self._graph = build_research_graph(checkpointer=self._checkpointer)

    # ===== 查询 =====

    def get(self, run_id: str) -> ResearchRunRecord:
        with self._lock:
            record = self._records.get(run_id)
        if record is not None:
            return record
        record = self._load_record(run_id)
        if record is None:
            raise RunNotFound(f"run not found: {run_id}")
        with self._lock:
            self._records[run_id] = record
        return record

    def list_runs(self, *, limit: int = 50) -> list[ResearchRunRecord]:
        records: dict[str, ResearchRunRecord] = {}
        for path in self.runs_dir.glob("run-*/run.json"):
            try:
                record = ResearchRunRecord.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except Exception:  # noqa: BLE001
                continue
            records[record.run_id] = record
        with self._lock:
            records.update(self._records)
        ordered = sorted(
            records.values(), key=lambda r: r.created_at, reverse=True
        )
        return ordered[: max(1, limit)]

    def events(self, run_id: str, *, after: int = 0, limit: int = 500):
        self.get(run_id)
        return self._event_store(run_id).after(after, limit=limit)

    def report_markdown(self, run_id: str) -> str:
        self.get(run_id)
        artifacts = self._artifacts(run_id)
        markdown = artifacts.read_text("report.md")
        if not markdown:
            raise RunNotFound(f"report not ready for run: {run_id}")
        return markdown

    def evidence_snapshot(self, run_id: str) -> list[dict[str, Any]]:
        self.get(run_id)
        return self._artifacts(run_id).read_json("evidence.json", default=[]) or []

    def state(self, run_id: str) -> dict[str, Any]:
        self.get(run_id)
        return state_values(self._graph, run_id)

    # ===== 启动 / 恢复 =====

    def start(self, request: ResearchRunRequest) -> ResearchRunRecord:
        county = request.county.strip()
        if not county:
            raise RunServiceError("county is required")
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        artifacts = RunArtifacts(run_id, self.runs_dir / run_id)
        store = self._event_store(run_id)
        record = ResearchRunRecord(
            run_id=run_id,
            request=request.model_copy(update={"county": county}),
            status=RunStatus.QUEUED,
            checkpoint_thread=run_id,
        )
        self._save_record(record)
        with self._lock:
            self._records[run_id] = record
        store.emit(
            EventType.RUN_QUEUED,
            node="api",
            message=f"研究请求已排队：{county} {request.focus or ''}".strip(),
            data={"request": request.model_dump(mode="json")},
        )
        state = initial_state(
            run_id=run_id,
            county=county,
            focus=(request.focus or "").strip(),
            mode=request.mode,
            objectives=request.objectives,
            max_rounds=int(self.settings.agents.max_rounds),
        )
        self._submit(run_id, state, artifacts, store)
        return self.get(run_id)

    def resume(self, run_id: str) -> ResearchRunRecord:
        record = self.get(run_id)
        if record.status == RunStatus.COMPLETED:
            return record
        if not state_values(self._graph, run_id):
            raise ResumeUnavailable(
                "没有可恢复的检查点（可能使用了内存检查点或运行尚未开始）"
            )
        artifacts = self._artifacts(run_id)
        store = self._event_store(run_id)
        with self._lock:
            record.status = RunStatus.QUEUED
            record.error = ""
            record.current_node = "resume"
        self._save_record(record)
        store.emit(
            EventType.RUN_RESUMED,
            node="resume",
            message="从检查点恢复研究运行",
        )
        self._submit(run_id, None, artifacts, store, resume=True)
        return self.get(run_id)

    def wait(self, run_id: str, *, timeout: float | None = None) -> ResearchRunRecord:
        with self._lock:
            future = self._futures.get(run_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.get(run_id)

    def shutdown(self, *, wait: bool = False) -> None:
        if self._owns_executor:
            self._executor.shutdown(wait=wait, cancel_futures=False)

    # ===== 内部执行 =====

    def _submit(
        self,
        run_id: str,
        state: dict[str, Any] | None,
        artifacts: RunArtifacts,
        store: RunEventStore,
        *,
        resume: bool = False,
    ) -> None:
        future = self._executor.submit(
            self._execute, run_id, state, artifacts, store, resume
        )
        with self._lock:
            self._futures[run_id] = future

    def _execute(
        self,
        run_id: str,
        state: dict[str, Any] | None,
        artifacts: RunArtifacts,
        store: RunEventStore,
        resume: bool,
    ) -> None:
        record = self.get(run_id)
        evidence = self.services.new_evidence()
        gap_radar = self.services.new_gap_radar(evidence)
        context = AgentContext(
            run_id=run_id,
            county=record.request.county,
            focus=(record.request.focus or ""),
            evidence=evidence,
            search=self.services.search,
            documents=self.services.documents,
            graph=self.services.graph,
            quant=self.services.quant,
            analytics=self.services.analytics,
            graph_store=self.services.graph_store,
            gap_radar=gap_radar,
            emitter=store.callback,
        )
        if resume:
            # 恢复：证据与原始资料从运行目录重建，图状态来自检查点
            artifacts.load_evidence(evidence)
            context.raw_docs = artifacts.load_docs()
            if not context.focus and record.request.focus:
                context.focus = record.request.focus

        with self._lock:
            record.status = RunStatus.RUNNING
            record.started_at = record.started_at or datetime.now(timezone.utc)
            record.current_node = "intake"
        self._save_record(record)
        if not resume:
            store.emit(
                EventType.RUN_STARTED,
                node="intake",
                message="研究运行开始",
                data={"run_id": run_id, "county": record.request.county},
            )
        config = run_config(
            run_id,
            services=self.services,
            context=context,
            artifacts=artifacts,
            emitter=store.callback,
            recursion_limit=self.settings.agents.recursion_limit,
        )
        try:
            result = self._graph.invoke(state, config)
        except Exception as exc:  # noqa: BLE001
            logger.exception("研究运行失败 | run_id=%s", run_id)
            with self._lock:
                record.status = RunStatus.FAILED
                record.error = str(exc)
                record.finished_at = datetime.now(timezone.utc)
                record.progress = 1.0
                record.current_node = "failed"
            self._save_record(record)
            store.emit(
                EventType.RUN_FAILED,
                node="failed",
                message=f"研究运行失败：{exc}",
                data={"error": str(exc)},
            )
            return

        final_state = dict(result or {})
        self._apply_state(record, final_state)
        record.finished_at = datetime.now(timezone.utc)
        record.current_node = "finalize"
        record.progress = 1.0
        record.checkpoint_thread = run_id
        self._save_record(record)
        store.emit(
            EventType.CHECKPOINT_SAVED,
            node="finalize",
            message=f"检查点已保存（{self.checkpoint_backend}）",
            data={
                "backend": self.checkpoint_backend,
                "thread_id": run_id,
                "evidence_count": record.evidence_count,
            },
        )

    def _apply_state(
        self, record: ResearchRunRecord, state: dict[str, Any]
    ) -> None:
        raw_status = str(state.get("status", "completed"))
        try:
            record.status = RunStatus(raw_status)
        except ValueError:
            record.status = RunStatus.COMPLETED
        record.error = str(state.get("error", "") or "")
        record.degraded = bool(state.get("degraded", False))
        record.evidence_count = int(state.get("evidence_count", 0) or 0)
        graph_stats = state.get("graph_stats") or {}
        record.graph_entities = int(graph_stats.get("entities", 0) or 0)
        record.graph_relations = int(graph_stats.get("relations", 0) or 0)
        if state.get("plan"):
            try:
                record.plan = ResearchPlan.model_validate(state["plan"])
            except Exception:  # noqa: BLE001
                record.plan = None
        results: list[AgentResult] = []
        for raw in state.get("results", []) or []:
            try:
                results.append(AgentResult.model_validate(raw))
            except Exception:  # noqa: BLE001
                continue
        record.agent_results = results
        if results:
            record.current_agent = results[-1].agent.value
        if state.get("critique"):
            try:
                record.critique = CritiqueReport.model_validate(state["critique"])
            except Exception:  # noqa: BLE001
                record.critique = None
        opportunities: list[OpportunityCandidate] = []
        for raw in state.get("opportunities", []) or []:
            try:
                opportunities.append(OpportunityCandidate.model_validate(raw))
            except Exception:  # noqa: BLE001
                continue
        record.opportunities = opportunities
        report = state.get("report") or {}
        record.report_path = str(report.get("report_path", "") or "")

    # ===== 文件 =====

    def _event_store(self, run_id: str) -> RunEventStore:
        with self._lock:
            store = self._events.get(run_id)
            if store is None:
                store = RunEventStore(run_id, self.runs_dir / run_id)
                self._events[run_id] = store
            return store

    def _artifacts(self, run_id: str) -> RunArtifacts:
        return RunArtifacts(run_id, self.runs_dir / run_id)

    def _save_record(self, record: ResearchRunRecord) -> None:
        artifacts = RunArtifacts(record.run_id, self.runs_dir / record.run_id)
        artifacts.write_json("run.json", record.model_dump(mode="json"))

    def _load_record(self, run_id: str) -> ResearchRunRecord | None:
        path = self.runs_dir / run_id / "run.json"
        if not path.exists():
            return None
        try:
            return ResearchRunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None


__all__ = [
    "ResearchRunService",
    "ResumeUnavailable",
    "RunNotFound",
    "RunServiceError",
]
