from __future__ import annotations

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = ""
    checkpoint_backend: str = ""
    graph_backend: str = ""
    llm: str = ""
    search: str = ""


__all__ = ["ErrorResponse", "HealthResponse"]
