"""证据 API：运行证据快照与单条证据追溯。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...orchestration.runner import ResearchRunService, RunNotFound
from ..dependencies import get_run_service

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


@router.get("/runs/{run_id}")
def list_evidence(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    runs: ResearchRunService = Depends(get_run_service),
) -> dict[str, Any]:
    try:
        snapshot = runs.evidence_snapshot(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "run_id": run_id,
        "count": len(snapshot),
        "items": snapshot[:limit],
    }


@router.get("/runs/{run_id}/{evidence_id}")
def get_evidence(
    run_id: str,
    evidence_id: str,
    runs: ResearchRunService = Depends(get_run_service),
) -> dict[str, Any]:
    try:
        snapshot = runs.evidence_snapshot(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    for item in snapshot:
        if item.get("id") == evidence_id:
            return item
    raise HTTPException(
        status_code=404, detail=f"evidence not found: {evidence_id}"
    )


__all__ = ["router"]
