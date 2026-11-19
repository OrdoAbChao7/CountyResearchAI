"""FastAPI 业务入口。

CLI 已移除；研究、图谱、证据、报告与仿真统一通过 HTTP API 暴露。
"""
from .main import app, create_app

__all__ = ["app", "create_app"]
