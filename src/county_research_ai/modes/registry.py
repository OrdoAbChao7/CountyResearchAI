from __future__ import annotations

from collections.abc import Iterable

from ..domain.modes import ResearchMode
from .base import ResearchModeHandler


class ModeRegistry:
    def __init__(self, handlers: Iterable[ResearchModeHandler]) -> None:
        self._handlers: dict[str, ResearchModeHandler] = {}
        for handler in handlers:
            if handler.name in self._handlers:
                raise ValueError(f"duplicate research mode: {handler.name}")
            self._handlers[handler.name] = handler

    def get(self, mode: ResearchMode | str) -> ResearchModeHandler:
        handler = self._handlers.get(mode)
        if handler is None:
            raise ValueError(f"unsupported research mode: {mode}")
        return handler
