"""FastAPI 应用入口。

启动方式（无 CLI 业务入口）：
    uvicorn county_research_ai.api.main:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from ..bootstrap.container import AppContainer, create_app_container
from ..config import Settings, get_settings
from .routes import evidence, graph, reports, research, simulations
from .schemas import HealthResponse

logger = logging.getLogger(__name__)


def create_app(
    container: AppContainer | None = None,
    *,
    settings: Settings | None = None,
) -> FastAPI:
    resolved_settings = settings or (container.settings if container else get_settings())
    owns_container = container is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "container", None) is None:
            app.state.container = create_app_container(resolved_settings)
        try:
            yield
        finally:
            if owns_container and getattr(app.state, "container", None) is not None:
                app.state.container.close()
                app.state.container = None

    app = FastAPI(
        title=resolved_settings.app.name,
        version=resolved_settings.app.version,
        description=(
            "Agentic Industrial Intelligence Platform：多 Agent 产业研究、"
            "证据约束知识图谱、产业链缺口雷达与数字孪生。"
        ),
        lifespan=lifespan,
    )
    app.state.container = container

    origins = resolved_settings.api.cors_origins or []
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(research.router)
    app.include_router(graph.router)
    app.include_router(evidence.router)
    app.include_router(reports.router)
    app.include_router(simulations.router)

    @app.get("/healthz", response_model=HealthResponse, tags=["system"])
    def healthz(request: Request) -> HealthResponse:
        container = getattr(request.app.state, "container", None)
        if container is None:
            return HealthResponse(status="starting")
        return HealthResponse(
            status="ok",
            version=resolved_settings.app.version,
            checkpoint_backend=container.runs.checkpoint_backend,
            graph_backend=getattr(
                container.graph_store, "name", type(container.graph_store).__name__
            ),
            llm=type(container.llm).__name__,
            search=container.search.provider_name,
        )

    @app.get("/", tags=["system"])
    def root() -> dict[str, Any]:
        return {
            "name": resolved_settings.app.name,
            "version": resolved_settings.app.version,
            "docs": "/docs",
            "health": "/healthz",
            "api": [
                "POST /api/research/runs",
                "GET /api/research/runs/{run_id}",
                "GET /api/research/runs/{run_id}/events",
                "GET /api/research/runs/{run_id}/report",
                "POST /api/research/runs/{run_id}/resume",
                "GET /api/graph/{county}",
                "GET /api/graph/query",
                "GET /api/evidence/runs/{run_id}",
                "GET /api/reports/{run_id}",
                "POST /api/simulations",
            ],
        }

    return app


app = create_app()


__all__ = ["app", "create_app"]
