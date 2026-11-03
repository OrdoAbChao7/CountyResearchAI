from __future__ import annotations

from typing import Protocol

from ..models import CountyInfo, DiscoveryResult, RawDoc


class DiscoveryPort(Protocol):
    def discover_focus(
        self, *, county: CountyInfo, raw_docs: list[RawDoc]
    ) -> DiscoveryResult: ...
