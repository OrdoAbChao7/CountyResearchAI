"""CLI 兼容入口。

The historical top-level module remains the compatibility source while all
new callers can depend on this stable interface package.
"""
from ..cli import main

__all__ = ["main"]
