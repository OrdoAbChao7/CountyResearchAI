"""Search requests and raw provider responses scoped to one research run."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from ..models import RawDoc

SearchRequestKey = tuple[int | str, str, int]


def normalize_query(query: str) -> str:
    return " ".join(query.split())


class SearchDocumentRecord(BaseModel):
    """One provider result as returned, before ranking or selection.

    The record is an audit aid only. ``parse_status`` distinguishes what the
    application did with the result:

    - ``text``: a non-PDF result whose body text was saved;
    - ``pdf_parsed``: a PDF result whose bytes were fetched and parsed by the
      application into body text;
    - ``pdf_text_from_provider``: a PDF result that came with provider body
      text; the app did not parse the PDF bytes, but the provider text is
      available and may enter the evidence pipeline;
    - ``pdf_not_parsed``: a PDF result without body text; only a snippet may
      exist, as reported by ``text_origin``;
    - ``no_text``: a non-PDF result without body text.

    None of these states verify the document contents, which remain
    ``NOT_VERIFIED``.
    """

    url: str
    title: str = ""
    content_type: str = ""
    content_chars: int = 0
    snippet_chars: int = 0
    text_sha256: str = ""
    text_origin: Literal["content", "snippet", "none"] = "none"
    parse_status: Literal[
        "text", "pdf_parsed", "pdf_text_from_provider", "pdf_not_parsed", "no_text"
    ] = "no_text"
    parse_reason: str = ""


class SearchExecution(BaseModel):
    slot_id: str
    round: int
    query: str
    provider: str = ""
    request: Literal["executed", "reused", "skipped"]
    status: Literal["results", "empty", "failed", "skipped"]
    returned_documents: int = 0
    reason: str = ""
    documents: list[SearchDocumentRecord] = Field(default_factory=list)


@dataclass
class SearchRequestHistory:
    # None denotes a failed request or route. An empty list is a successful empty result.
    responses: dict[SearchRequestKey, list[RawDoc] | None] = field(default_factory=dict)
    route_results: dict[SearchRequestKey, list[RawDoc] | None] = field(default_factory=dict)
    used_queries: set[tuple[SearchRequestKey, str]] = field(default_factory=set)
    executions: list[SearchExecution] = field(default_factory=list)

    def can_use(self, request: SearchRequestKey, route: SearchRequestKey, slot_id: str) -> bool:
        if (route, slot_id) in self.used_queries:
            return False
        if route in self.route_results:
            return bool(self.route_results[route])
        return request not in self.responses or bool(self.responses[request])


_current_history: ContextVar[SearchRequestHistory | None] = ContextVar(
    "research_search_history", default=None
)


def current_search_history() -> SearchRequestHistory | None:
    return _current_history.get()


@contextmanager
def bind_search_history(history: SearchRequestHistory) -> Iterator[None]:
    token = _current_history.set(history)
    try:
        yield
    finally:
        _current_history.reset(token)
