"""API 依赖：从应用状态获取容器与服务。"""
from __future__ import annotations

from fastapi import Request

from ..bootstrap.v2_container import AppContainer
from ..orchestration.runner import ResearchRunService
from ..services.graph_service import GraphService
from ..shining_stars.digital_twin import DigitalTwinService


def get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("application container is not initialized")
    return container


def get_run_service(request: Request) -> ResearchRunService:
    return get_container(request).runs


def get_graph_service(request: Request) -> GraphService:
    return get_container(request).services.graph


def get_simulation_service(request: Request) -> DigitalTwinService:
    return get_container(request).simulation


__all__ = [
    "get_container",
    "get_graph_service",
    "get_run_service",
    "get_simulation_service",
]
