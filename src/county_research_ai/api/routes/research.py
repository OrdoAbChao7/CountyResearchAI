"""研究运行 API：启动、状态、SSE 事件、报告与恢复。"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from ...agents.registry import agent_catalog
from ...domain.events import RunEvent
from ...domain.intelligence import ResearchRunRecord, RunStatus
from ...orchestration.runner import (
    ResearchRunService,
    ResumeUnavailable,
    RunNotFound,
    RunServiceError,
)
from ..dependencies import get_run_service
from ..v2_schemas import ReportResponse, ResearchRunCreate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research", tags=["research"])

_TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


@router.post(
    "/runs",
    response_model=ResearchRunRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_run(
    payload: ResearchRunCreate,
    runs: ResearchRunService = Depends(get_run_service),
) -> ResearchRunRecord:
    try:
        return runs.start(payload.to_domain())
    except RunServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs", response_model=list[ResearchRunRecord])
def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    runs: ResearchRunService = Depends(get_run_service),
) -> list[ResearchRunRecord]:
    return runs.list_runs(limit=limit)


@router.get("/runs/{run_id}", response_model=ResearchRunRecord)
def get_run(
    run_id: str,
    runs: ResearchRunService = Depends(get_run_service),
) -> ResearchRunRecord:
    try:
        return runs.get(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/resume", response_model=ResearchRunRecord)
def resume_run(
    run_id: str,
    runs: ResearchRunService = Depends(get_run_service),
) -> ResearchRunRecord:
    try:
        return runs.resume(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ResumeUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/{run_id}/report", response_model=ReportResponse)
def get_report(
    run_id: str,
    runs: ResearchRunService = Depends(get_run_service),
) -> ReportResponse:
    try:
        record = runs.get(run_id)
        markdown = runs.report_markdown(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ReportResponse(
        run_id=run_id, markdown=markdown, path=record.report_path
    )


@router.get("/runs/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
    runs: ResearchRunService = Depends(get_run_service),
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    """SSE：推送 Agent/工具/进度/错误事件，运行结束后发送 ``stream_end``。"""
    try:
        runs.get(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    start = after
    if last_event_id and last_event_id.isdigit():
        start = max(start, int(last_event_id))

    async def event_stream():
        last = start
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            try:
                events: list[RunEvent] = runs.events(run_id, after=last, limit=200)
            except RunNotFound:
                break
            for event in events:
                last = event.seq
                yield (
                    f"id: {event.seq}\nevent: {event.type}\n"
                    f"data: {event.model_dump_json()}\n\n"
                )
            record = runs.get(run_id)
            if record.status in _TERMINAL and not events:
                yield (
                    "event: stream_end\n"
                    f"data: {json.dumps({'run_id': run_id, 'status': record.status.value})}\n\n"
                )
                break
            idle += 1
            if idle % 40 == 0:
                yield ": ping\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/agents")
def list_agents() -> list[dict]:
    return agent_catalog()


__all__ = ["router"]
