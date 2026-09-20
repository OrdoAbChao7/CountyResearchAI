"""研究模式的唯一归一化入口。"""
from __future__ import annotations

from typing import Literal, cast

from ..models import ResearchRequest

ResearchMode = Literal["snapshot", "rise-fall", "long-history"]

_ALIASES: dict[str, ResearchMode] = {
    "snapshot": "snapshot",
    "industry": "snapshot",
    "rise-fall": "rise-fall",
    "long-history": "long-history",
}


def normalize_mode(value: str) -> ResearchMode:
    normalized = _ALIASES.get(value.strip().lower())
    if normalized is None:
        raise ValueError(f"unsupported research mode: {value}")
    return cast(ResearchMode, normalized)


def normalize_request(request: ResearchRequest) -> ResearchRequest:
    return request.model_copy(
        deep=True,
        update={"mode": normalize_mode(request.mode)},
    )
