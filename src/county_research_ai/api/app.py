"""FastAPI application for the local AxiomScope workspace."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..config import Settings, get_settings
from ..evidence.graph import EvidenceGraphStore
from .brief import render_decision_brief
from .jobs import JobRecord, JobStatus, JobStore
from .projections import (
    EvidenceListResponse,
    GraphView,
    ProjectionUnavailable,
    QuestionsView,
    ReportView,
    build_evidence_list,
    build_graph_view,
    build_questions_view,
    build_report_view,
)
from .schemas import (
    CapabilitiesOut,
    ClaimChainOut,
    CreateTaskRequest,
    EventOut,
    FindingOut,
    SourceDetailOut,
    SourceOut,
    TaskDetail,
    TaskSummary,
)
from .worker import JobRunner

logger = logging.getLogger(__name__)

API_VERSION = "v1"
JOB_SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 1
ENFORCED_CAPS = ["deadline_seconds"]
BOUNDED_PER_CALL_CAPS = ["max_tokens", "max_documents"]
UNENFORCED_CAPS = ["max_steps", "max_search_calls", "max_cost"]
_ID_RE = re.compile(r"^[A-Za-z0-9_:.\-]{1,200}$")


def _safe_id(value: str, field: str) -> str:
    if not _ID_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "invalid_id", "message": f"invalid {field}"}},
        )
    return value


def _job_or_404(store: JobStore, job_id: str) -> JobRecord:
    job = store.get_job(_safe_id(job_id, "job_id"))
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "job_not_found", "message": "job not found"}},
        )
    return job


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            content = detail
        else:
            content = {
                "error": {"code": f"http_{exc.status_code}", "message": str(detail)}
            }
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {key: value for key, value in error.items() if key != "ctx"}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "request validation failed",
                    "details": jsonable_encoder(details),
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled API error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "internal server error",
                }
            },
        )


def _register_core_routes(
    app: FastAPI, *, runner: JobRunner, live_enabled: bool
) -> None:
    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": "0.1.0",
            "job_schema_version": JOB_SCHEMA_VERSION,
            "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        }

    @app.get("/api/v1/capabilities", response_model=CapabilitiesOut)
    def capabilities() -> CapabilitiesOut:
        return CapabilitiesOut(
            api_version=API_VERSION,
            job_schema_version=JOB_SCHEMA_VERSION,
            evidence_schema_version=EVIDENCE_SCHEMA_VERSION,
            mode_label=runner.mode_label,
            live_enabled=live_enabled,
            enforced_caps=list(ENFORCED_CAPS),
            bounded_per_call_caps=list(BOUNDED_PER_CALL_CAPS),
            unenforced_caps=list(UNENFORCED_CAPS),
            docs_url="/docs",
        )


def _register_task_routes(
    app: FastAPI, *, job_store: JobStore, runner: JobRunner
) -> None:
    @app.post("/api/v1/research/tasks", status_code=202, response_model=TaskDetail)
    def create_task(payload: CreateTaskRequest) -> TaskDetail:
        job = job_store.create_job(payload.contract, mode_label=runner.mode_label)
        runner.submit(job.job_id)
        return TaskDetail.from_job(job_store.get_job(job.job_id) or job)

    @app.get("/api/v1/research/tasks", response_model=list[TaskSummary])
    def list_tasks(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> list[TaskSummary]:
        return [
            TaskSummary.from_job(job)
            for job in job_store.list_jobs(limit=limit, offset=offset)
        ]

    @app.get("/api/v1/research/tasks/{job_id}", response_model=TaskDetail)
    def get_task(job_id: str = PathParam(...)) -> TaskDetail:
        return TaskDetail.from_job(_job_or_404(job_store, job_id))

    @app.post("/api/v1/research/tasks/{job_id}/cancel", response_model=TaskSummary)
    def cancel_task(job_id: str = PathParam(...)) -> TaskSummary:
        job = _job_or_404(job_store, job_id)
        if job.status.terminal:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "job_already_terminal",
                        "message": f"job is already {job.status.value}",
                    }
                },
            )
        job_store.request_cancel(job.job_id)
        return TaskSummary.from_job(job_store.get_job(job.job_id) or job)

    @app.post(
        "/api/v1/research/tasks/{job_id}/resume",
        status_code=202,
        response_model=TaskDetail,
    )
    def resume_task(job_id: str = PathParam(...)) -> TaskDetail:
        job = _job_or_404(job_store, job_id)
        if job.status is JobStatus.RUNNING:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {"code": "job_running", "message": "job is still running"}
                },
            )
        if job.status is JobStatus.SUCCEEDED:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "job_already_succeeded",
                        "message": "completed jobs are not resumed",
                    }
                },
            )
        job_store.requeue(job.job_id)
        runner.submit(job.job_id)
        job_store.append_event(job.job_id, "job.resumed", {})
        return TaskDetail.from_job(job_store.get_job(job.job_id) or job)

    @app.get("/api/v1/research/tasks/{job_id}/events", response_model=list[EventOut])
    def list_events(
        job_id: str = PathParam(...),
        after: int = Query(default=0, ge=0),
    ) -> list[EventOut]:
        job = _job_or_404(job_store, job_id)
        return [
            EventOut.from_event(event)
            for event in job_store.list_events(job.job_id, after_seq=after)
        ]

    @app.get("/api/v1/research/tasks/{job_id}/stream")
    async def stream_events(
        request: Request,
        job_id: str = PathParam(...),
        after: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        job = _job_or_404(job_store, job_id)
        last = after
        header = request.headers.get("last-event-id", "")
        if header.isdigit():
            last = max(last, int(header))
        return StreamingResponse(
            _event_stream(request, job_store, job.job_id, last),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


async def _event_stream(
    request: Request, store: JobStore, job_id: str, last: int
) -> AsyncIterator[str]:
    while True:
        if await request.is_disconnected():
            return
        events = store.list_events(job_id, after_seq=last)
        for event in events:
            last = event.seq
            payload = {
                "seq": event.seq,
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            }
            yield (
                f"id: {event.seq}\n"
                f"event: {event.event_type}\n"
                f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            )
        current = store.get_job(job_id)
        if current is not None and current.status.terminal and not events:
            return
        await asyncio.sleep(0.2)


def _projection_unavailable(exc: ProjectionUnavailable) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": {
                "code": "artifacts_unavailable",
                "message": exc.message,
                "reason": exc.reason,
            }
        },
    )


def _parse_topics(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _legacy_report_text(
    job: JobRecord, reports_dir: Path, *, required: bool
) -> str | None:
    if not job.report_path:
        if required:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {"code": "report_not_ready", "message": "no report yet"}
                },
            )
        return None
    report = Path(job.report_path).resolve()
    root = reports_dir.resolve()
    if root not in report.parents and report.parent != root:
        raise HTTPException(
            status_code=403,
            detail={
                "error": {
                    "code": "report_outside_root",
                    "message": "report path is outside the reports directory",
                }
            },
        )
    if not report.is_file():
        if required:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {"code": "report_not_found", "message": "report missing"}
                },
            )
        return None
    return report.read_text(encoding="utf-8")


def _register_evidence_routes(
    app: FastAPI,
    *,
    job_store: JobStore,
    graph: EvidenceGraphStore,
    reports_dir: Path,
) -> None:
    @app.get(
        "/api/v1/research/tasks/{job_id}/findings",
        response_model=list[FindingOut],
    )
    def list_findings(job_id: str = PathParam(...)) -> list[FindingOut]:
        job = _job_or_404(job_store, job_id)
        return [
            FindingOut.from_verified(item) for item in graph.list_findings(job.job_id)
        ]

    @app.get(
        "/api/v1/research/tasks/{job_id}/claims",
        response_model=list[ClaimChainOut],
    )
    def list_claims(job_id: str = PathParam(...)) -> list[ClaimChainOut]:
        job = _job_or_404(job_store, job_id)
        return [
            ClaimChainOut.from_chain(chain) for chain in graph.list_findings(job.job_id)
        ]

    @app.get(
        "/api/v1/research/tasks/{job_id}/claims/{claim_id}",
        response_model=ClaimChainOut,
    )
    def get_claim(
        job_id: str = PathParam(...),
        claim_id: str = PathParam(...),
    ) -> ClaimChainOut:
        job = _job_or_404(job_store, job_id)
        _safe_id(claim_id, "claim_id")
        claim_ids = {claim.claim_id for claim in graph.list_claims(run_id=job.job_id)}
        if claim_id not in claim_ids:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "code": "claim_not_found",
                        "message": "claim is not part of this run",
                    }
                },
            )
        return ClaimChainOut.from_chain(
            graph.get_chain(claim_id, run_id=job.job_id)
        )

    @app.get(
        "/api/v1/research/tasks/{job_id}/sources",
        response_model=list[SourceOut],
    )
    def list_sources(job_id: str = PathParam(...)) -> list[SourceOut]:
        job = _job_or_404(job_store, job_id)
        return [
            SourceOut.from_snapshot(snapshot)
            for snapshot in graph.list_run_snapshots(job.job_id)
        ]

    @app.get(
        "/api/v1/research/sources/{snapshot_id}",
        response_model=SourceDetailOut,
    )
    def get_source(snapshot_id: str = PathParam(...)) -> SourceDetailOut:
        _safe_id(snapshot_id, "snapshot_id")
        snapshot = graph.get_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {"code": "source_not_found", "message": "source not found"}
                },
            )
        return SourceDetailOut.from_snapshot(snapshot)

    @app.get(
        "/api/v1/research/tasks/{job_id}/questions",
        response_model=QuestionsView,
    )
    def get_questions(job_id: str = PathParam(...)) -> QuestionsView:
        job = _job_or_404(job_store, job_id)
        try:
            return build_questions_view(job)
        except ProjectionUnavailable as exc:
            raise _projection_unavailable(exc) from exc

    @app.get(
        "/api/v1/research/tasks/{job_id}/graph",
        response_model=GraphView,
    )
    def get_graph(
        job_id: str = PathParam(...),
        max_nodes: int = Query(default=400, ge=50, le=1000),
        max_edges: int = Query(default=800, ge=1, le=4000),
        include_sources: bool = Query(default=True),
        topics: str = Query(default=""),
    ) -> GraphView:
        job = _job_or_404(job_store, job_id)
        try:
            return build_graph_view(
                job=job,
                graph=graph,
                max_nodes=max_nodes,
                max_edges=max_edges,
                include_sources=include_sources,
                topics=_parse_topics(topics),
            )
        except ProjectionUnavailable as exc:
            raise _projection_unavailable(exc) from exc

    @app.get(
        "/api/v1/research/tasks/{job_id}/evidence",
        response_model=EvidenceListResponse,
    )
    def get_evidence(
        job_id: str = PathParam(...),
        q: str = Query(default=""),
        status: str = Query(default=""),
        topic: str = Query(default=""),
        min_credibility: float = Query(default=0.0, ge=0.0, le=1.0),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> EvidenceListResponse:
        job = _job_or_404(job_store, job_id)
        return build_evidence_list(
            job=job,
            graph=graph,
            query=q,
            status=status.strip().upper(),
            topic=topic,
            min_credibility=min_credibility,
            limit=limit,
            offset=offset,
        )

    @app.get(
        "/api/v1/research/tasks/{job_id}/report.json",
        response_model=ReportView,
    )
    def get_report_json(job_id: str = PathParam(...)) -> ReportView:
        job = _job_or_404(job_store, job_id)
        return build_report_view(
            job=job,
            graph=graph,
            legacy_markdown=_legacy_report_text(job, reports_dir, required=False),
        )

    @app.get("/api/v1/research/tasks/{job_id}/brief")
    def get_brief(job_id: str = PathParam(...)) -> PlainTextResponse:
        job = _job_or_404(job_store, job_id)
        markdown = render_decision_brief(
            job_id=job.job_id,
            contract=job.contract,
            outcome=job.outcome,
            outcome_reason=job.outcome_reason,
            mode_label=job.mode_label,
            findings=graph.list_findings(job.job_id),
            sources=graph.list_run_snapshots(job.job_id),
        )
        return PlainTextResponse(
            markdown,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{job.job_id}-brief.md"'
            },
        )

    @app.get("/api/v1/research/tasks/{job_id}/report")
    def get_report(job_id: str = PathParam(...)) -> PlainTextResponse:
        job = _job_or_404(job_store, job_id)
        view = build_report_view(
            job=job,
            graph=graph,
            legacy_markdown=_legacy_report_text(job, reports_dir, required=False),
        )
        return PlainTextResponse(
            view.markdown,
            media_type="text/markdown; charset=utf-8",
        )

    @app.get("/api/v1/research/tasks/{job_id}/report/draft")
    def get_report_draft(job_id: str = PathParam(...)) -> PlainTextResponse:
        job = _job_or_404(job_store, job_id)
        markdown = _legacy_report_text(job, reports_dir, required=True)
        return PlainTextResponse(
            markdown or "",
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{job.job_id}-draft.md"'
            },
        )


def _mount_frontend(app: FastAPI) -> None:
    dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
        return

    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "name": "AxiomScope API",
            "version": "0.1.0",
            "docs": "/docs",
            "health": "/health",
            "note": "frontend build not found; run npm build in web/",
        }


def create_app(
    *,
    settings: Settings | None = None,
    store: JobStore | None = None,
    runner: JobRunner | None = None,
    live_enabled: bool | None = None,
    data_dir: Path | None = None,
    reports_dir: Path | None = None,
    evidence_db_path: Path | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if live_enabled is None:
        live_enabled = os.getenv("AXIOMSCOPE_API_LIVE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    api_root = Path(data_dir) if data_dir is not None else settings.data_dir / "api"
    resolved_data_dir = Path(data_dir) if data_dir is not None else settings.data_dir
    resolved_reports_dir = (
        Path(reports_dir) if reports_dir is not None else settings.reports_dir
    )
    evidence_db = (
        Path(evidence_db_path)
        if evidence_db_path is not None
        else api_root / "evidence.sqlite"
    )
    job_store = store or JobStore(api_root / "jobs.sqlite")
    owned_runner = runner is None
    if runner is None:
        runner = JobRunner(
            job_store,
            data_dir=resolved_data_dir,
            reports_dir=resolved_reports_dir,
            evidence_db_path=evidence_db,
            settings=settings,
            live_enabled=live_enabled,
        )
    graph = EvidenceGraphStore(evidence_db)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        recovered = job_store.recover_interrupted()
        if recovered:
            logger.warning("marked %s interrupted job(s) after restart", recovered)
        for queued in job_store.list_jobs(limit=200):
            if queued.status is JobStatus.QUEUED:
                runner.submit(queued.job_id)
        yield
        if owned_runner:
            runner.shutdown(wait=False)

    app = FastAPI(
        title="AxiomScope API",
        version="0.1.0",
        description=(
            "Evidence-native regional industry research. Research runs, "
            "claim-level evidence, and decision briefs."
        ),
        lifespan=lifespan,
    )
    app.state.job_store = job_store
    app.state.runner = runner
    app.state.graph = graph
    app.state.settings = settings
    app.state.live_enabled = live_enabled
    app.state.reports_dir = resolved_reports_dir

    origins = cors_origins or [
        origin.strip()
        for origin in os.getenv(
            "AXIOMSCOPE_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )
    _install_error_handlers(app)
    _register_core_routes(app, runner=runner, live_enabled=live_enabled)
    _register_task_routes(app, job_store=job_store, runner=runner)
    _register_evidence_routes(
        app, job_store=job_store, graph=graph, reports_dir=resolved_reports_dir
    )
    _mount_frontend(app)
    return app


def default_app() -> FastAPI:
    """Uvicorn factory: ``uvicorn county_research_ai.api.app:default_app --factory``."""
    return create_app()
