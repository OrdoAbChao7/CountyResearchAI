"""FastAPI 应用工厂。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import Settings, get_settings
from .routers import system
from .settings import WebSettings


def create_app(
    settings: Settings | None = None,
    web_settings: WebSettings | None = None,
) -> FastAPI:
    """构建 Web 应用。

    依赖显式注入，测试可传入临时 Settings；生产由 uvicorn factory 调用，
    此时读取全局配置单例与 ``COUNTY_WEB_*`` 环境变量。
    """
    settings = settings or get_settings()
    web_settings = web_settings or WebSettings.from_env()

    app = FastAPI(
        title=f"{settings.app.name} API",
        version=settings.app.version,
    )
    app.state.settings = settings
    app.state.web_settings = web_settings

    if web_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=web_settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(system.router)
    return app
