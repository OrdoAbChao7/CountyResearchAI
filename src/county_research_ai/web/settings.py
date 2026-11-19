"""Web 适配层配置。

只从 ``COUNTY_WEB_*`` 环境变量读取，不写入 settings.yaml，
避免部署参数与研究配置互相污染。
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import PROJECT_ROOT

_PACKAGE_DIR = Path(__file__).resolve().parent


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


class WebSettings(BaseModel):
    """``COUNTY_WEB_*`` 环境变量的类型化视图。"""

    host: str = "127.0.0.1"
    port: int = 8000
    # 研究线程池并发数，不是 uvicorn 进程数。
    workers: int = 2
    queue_limit: int = 20
    runs_dir: Path = PROJECT_ROOT / "data" / "runs"
    cors_origins: list[str] = Field(default_factory=list)
    token: str = ""
    event_heartbeat: int = 15
    event_poll: float = 0.25
    static_dir: Path = _PACKAGE_DIR / "static"
    max_graph_nodes: int = 1000

    @classmethod
    def from_env(cls) -> WebSettings:
        """读取环境变量；空字符串视为未设置。"""
        raw_origins = os.getenv("COUNTY_WEB_CORS_ORIGINS", "")
        return cls(
            host=_env_str("COUNTY_WEB_HOST", "127.0.0.1"),
            port=_env_int("COUNTY_WEB_PORT", 8000),
            workers=_env_int("COUNTY_WEB_WORKERS", 2),
            queue_limit=_env_int("COUNTY_WEB_QUEUE_LIMIT", 20),
            runs_dir=Path(
                _env_str("COUNTY_WEB_RUNS_DIR", str(PROJECT_ROOT / "data" / "runs"))
            ),
            cors_origins=[
                origin.strip()
                for origin in raw_origins.split(",")
                if origin.strip()
            ],
            token=os.getenv("COUNTY_WEB_TOKEN", ""),
            event_heartbeat=_env_int("COUNTY_WEB_EVENT_HEARTBEAT", 15),
            event_poll=_env_float("COUNTY_WEB_EVENT_POLL", 0.25),
            static_dir=Path(_env_str("COUNTY_WEB_STATIC_DIR", str(_PACKAGE_DIR / "static"))),
        )
