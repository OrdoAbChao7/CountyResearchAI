"""报告 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from ...domain.intelligence import ResearchRunRecord
from ...orchestration.runner import ResearchRunService, RunNotFound
from ..dependencies import get_run_service
from ..schemas import ReportResponse

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=list[ResearchRunRecord])
def list_reports(
    limit: int = 50,
    runs: ResearchRunService = Depends(get_run_service),
) -> list[ResearchRunRecord]:
    return [r for r in runs.list_runs(limit=limit) if r.report_path]


@router.get("/{run_id}", response_model=ReportResponse)
def get_report(
    run_id: str,
    runs: ResearchRunService = Depends(get_run_service),
) -> ReportResponse:
    try:
        record = runs.get(run_id)
        markdown = runs.report_markdown(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ReportResponse(run_id=run_id, markdown=markdown, path=record.report_path)


@router.get("/{run_id}/download", response_class=PlainTextResponse)
def download_report(
    run_id: str,
    runs: ResearchRunService = Depends(get_run_service),
) -> PlainTextResponse:
    try:
        markdown = runs.report_markdown(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{run_id}.md"'
        },
    )


__all__ = ["router"]
