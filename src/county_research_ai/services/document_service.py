"""文档处理服务:清洗、去重、排序、缓存与落盘。"""
from __future__ import annotations

import logging

from ..config import Settings, get_settings
from ..models import CountyInfo, ProcessedData, RawDoc
from ..processor import DocumentProcessor
from ..storage.base import Storage

logger = logging.getLogger(__name__)


class DocumentService:
    """把 ``DocumentProcessor`` 与 ``Storage`` 组合为 Agent 可调用的服务。

    处理器负责纯内存清洗；本服务负责缓存命中与原始/处理后数据落盘。
    """

    def __init__(
        self,
        processor: DocumentProcessor,
        storage: Storage,
        settings: Settings | None = None,
    ) -> None:
        self._processor = processor
        self._storage = storage
        self._settings = settings or get_settings()

    def process(
        self,
        docs: list[RawDoc],
        *,
        county: CountyInfo,
        focus: str,
        use_cache: bool = False,
    ) -> ProcessedData:
        """清洗并打包文档；``use_cache=True`` 时优先读取未过期的处理后缓存。"""
        if use_cache:
            cached = self.load_cached(county.name, focus)
            if cached is not None:
                return cached
        processed = self._processor.process(docs, county=county, focus=focus)
        try:
            self._storage.save_processed(county.name, focus, processed)
        except Exception as exc:  # noqa: BLE001
            logger.warning("处理后数据落盘失败（不影响研究） | err=%s", exc)
        return processed

    def load_cached(self, county: str, focus: str) -> ProcessedData | None:
        settings = self._settings
        if not settings.cache.enabled:
            return None
        try:
            return self._storage.load_processed(
                county, focus, max_age_hours=settings.cache.ttl_hours
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取处理后缓存失败 | err=%s", exc)
            return None

    def archive_raw(self, county: str, docs: list[RawDoc]) -> None:
        """归档原始资料。归档失败不阻断研究。"""
        try:
            self._storage.save_raw(county, docs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("原始资料归档失败（不影响研究） | err=%s", exc)

    def summarize(self, processed: ProcessedData, *, max_chars: int = 12000) -> str:
        """渲染为 Agent prompt 可消费的证据包文本。"""
        return processed.render_for_llm(max_chars=max_chars)


__all__ = ["DocumentService"]
