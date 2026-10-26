"""Run the local AxiomScope API: ``python -m county_research_ai.api``."""
from __future__ import annotations

import os

import uvicorn

from .app import default_app


def main() -> None:
    uvicorn.run(
        default_app(),
        host=os.getenv("AXIOMSCOPE_API_HOST", "127.0.0.1"),
        port=int(os.getenv("AXIOMSCOPE_API_PORT", "8000")),
        log_level=os.getenv("AXIOMSCOPE_API_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
