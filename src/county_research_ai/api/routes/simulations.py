"""Star B API：产业数字孪生情景仿真。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...shining_stars.digital_twin import (
    DigitalTwinService,
    SimulationEngineUnavailable,
    SimulationRequest,
)
from ..dependencies import get_simulation_service

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


@router.get("/capabilities")
def capabilities(
    service: DigitalTwinService = Depends(get_simulation_service),
) -> dict[str, Any]:
    return service.capabilities()


@router.post("")
def simulate(
    payload: SimulationRequest,
    service: DigitalTwinService = Depends(get_simulation_service),
) -> dict[str, Any]:
    try:
        outcome = service.simulate(payload)
    except SimulationEngineUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return outcome.model_dump(mode="json")


__all__ = ["router"]
