"""知识图谱 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...services.graph_service import GraphService
from ..dependencies import get_graph_service

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/query")
def query_graph(
    question: str = Query(min_length=2, max_length=300),
    county: str = "",
    focus: str = "",
    graph: GraphService = Depends(get_graph_service),
) -> dict[str, Any]:
    result = graph.query(question, county=county, focus=focus)
    return result.model_dump(mode="json")


@router.get("/entities/{entity_id}")
def get_entity(
    entity_id: str,
    graph: GraphService = Depends(get_graph_service),
) -> dict[str, Any]:
    entity = graph.get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"entity not found: {entity_id}")
    return entity


@router.get("/{county}")
def county_graph(
    county: str,
    industry: str = "",
    limit: int = Query(default=200, ge=1, le=1000),
    graph: GraphService = Depends(get_graph_service),
) -> dict[str, Any]:
    return graph.county_graph(county, industry=industry, limit=limit)


__all__ = ["router"]
