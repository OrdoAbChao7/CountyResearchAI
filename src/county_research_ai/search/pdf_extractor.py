"""Deterministic PDF text extraction for public bulletins and official notices.

Uses ``pypdf`` on bounded PDF byte streams so official county statistical
bulletins and designation notices returned as ``.pdf`` links can enter the
evidence pipeline with exact offsets and content hashes.
"""
from __future__ import annotations

import io
import logging
import re

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MAX_PDF_BYTES = 15 * 1024 * 1024
DEFAULT_MAX_PDF_PAGES = 60

_PDF_MAGIC = b"%PDF-"
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def is_pdf_document(url: str, content_type: str = "") -> bool:
    """Return True when either the MIME header or URL path indicates a PDF."""
    if "pdf" in (content_type or "").lower():
        return True
    path = (url or "").lower().split("#", 1)[0].split("?", 1)[0]
    return path.endswith(".pdf")


def extract_pdf_text_bytes(
    data: bytes,
    *,
    max_pages: int = DEFAULT_MAX_PDF_PAGES,
    max_chars: int = 0,
) -> tuple[str, int]:
    """Extract normalized plain text and page count from raw PDF bytes.

    Raises ``ValueError`` when the payload is empty, not a valid PDF, or cannot
    be decoded by ``pypdf``.
    """
    if not data or not data.lstrip().startswith(_PDF_MAGIC):
        raise ValueError("payload is not a valid PDF byte stream")
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - declared in pyproject.toml
        raise RuntimeError("pypdf is required for PDF extraction") from exc

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            reader.decrypt("")
        total_pages = len(reader.pages)
        limit = min(total_pages, max_pages) if max_pages > 0 else total_pages
        chunks: list[str] = []
        collected = 0
        for idx in range(limit):
            page_text = (reader.pages[idx].extract_text() or "").strip()
            if not page_text:
                continue
            chunks.append(page_text)
            collected += len(page_text)
            if max_chars > 0 and collected >= max_chars:
                break
    except Exception as exc:
        raise ValueError(f"failed to parse PDF stream: {exc}") from exc

    text = _MULTI_BLANK_RE.sub("\n\n", "\n\n".join(chunks)).strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[: max_chars - 3] + "..."
    return text, total_pages


def fetch_pdf_bytes(
    url: str,
    *,
    timeout: float = 20.0,
    max_bytes: int = DEFAULT_MAX_PDF_BYTES,
) -> tuple[bytes, str]:
    """Download bounded bytes from ``url`` and return ``(data, content_type)``."""
    headers = {
        "User-Agent": "Mozilla/5.0 (CountyResearchAI/0.2 bot)",
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    buf = bytearray()
    content_type = ""
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code >= 400:
                raise ValueError(f"HTTP {resp.status_code} fetching PDF")
            content_type = resp.headers.get("content-type", "")
            for chunk in resp.iter_bytes():
                buf.extend(chunk)
                if max_bytes > 0 and len(buf) > max_bytes:
                    raise ValueError(f"PDF exceeds max_bytes ({max_bytes})")
    return bytes(buf), content_type
