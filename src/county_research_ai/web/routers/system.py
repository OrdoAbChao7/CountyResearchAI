"""系统端点：存活探针与前端启动元信息。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import (
    FeatureFlags,
    HealthResponse,
    Limits,
    MetaResponse,
    ProviderStatus,
)
from ..settings import WebSettings

router = APIRouter(tags=["system"])


def _configured(secret) -> bool:
    """SecretStr 可能为空；空值不触发任何真实调用。"""
    return bool(secret and secret.get_secret_value())


@router.get("/api/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    # T0 尚未接入 RunManager；接入后从运行注册表读取活跃数。
    return HealthResponse(version=settings.app.version, active_runs=0)


@router.get("/api/v1/meta", response_model=MetaResponse)
def meta(request: Request) -> MetaResponse:
    settings = request.app.state.settings
    web_settings: WebSettings = request.app.state.web_settings
    llm_configured = _configured(settings.llm.api_key)
    search_configured = _configured(settings.search.api_key)

    return MetaResponse(
        version=settings.app.version,
        features=FeatureFlags(),
        llm=ProviderStatus(
            configured=llm_configured,
            provider=settings.llm.provider if llm_configured else "mock",
        ),
        search=ProviderStatus(
            configured=search_configured,
            provider=settings.search.provider if search_configured else "mock",
        ),
        limits=Limits(
            max_workers=web_settings.workers,
            queue_limit=web_settings.queue_limit,
            max_graph_nodes=web_settings.max_graph_nodes,
        ),
    )
