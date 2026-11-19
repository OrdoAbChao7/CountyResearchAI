"""系统端点响应模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    active_runs: int = 0


class ProviderStatus(BaseModel):
    """只暴露“是否配置”，绝不返回密钥本身。"""

    configured: bool
    provider: str


class FeatureFlags(BaseModel):
    deep_research: bool = True
    sse: bool = False
    graph: bool = True


class Limits(BaseModel):
    max_workers: int
    queue_limit: int
    max_graph_nodes: int = 1000


class MetaResponse(BaseModel):
    version: str
    modes: list[str] = Field(
        default_factory=lambda: ["snapshot", "rise-fall", "long-history"]
    )
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    llm: ProviderStatus
    search: ProviderStatus
    limits: Limits
