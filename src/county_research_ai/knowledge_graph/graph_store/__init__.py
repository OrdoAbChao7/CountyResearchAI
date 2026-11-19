"""图存储适配器与工厂。"""
from __future__ import annotations

import logging

from ...config import Settings, get_settings
from .base import GraphStore, GraphStoreError, GraphWriteError, GraphWritePolicy, Subgraph
from .mock_store import InMemoryGraphStore

logger = logging.getLogger(__name__)


def create_graph_store(
    settings: Settings | None = None,
    *,
    policy: GraphWritePolicy | None = None,
) -> GraphStore:
    """按配置创建图存储。

    - ``graph.backend=neo4j`` 且驱动/连接可用 → ``Neo4jGraphStore``
    - 否则 → ``InMemoryGraphStore``（开发、测试与外部服务不可用时的降级）
    """
    settings = settings or get_settings()
    config = settings.graph
    if config.backend.lower() == "neo4j":
        try:
            from .neo4j_store import Neo4jGraphStore

            password = config.password.get_secret_value() if config.password else ""
            store = Neo4jGraphStore(
                config.uri,
                config.user,
                password,
                database=config.database,
                policy=policy,
                connection_timeout=config.connection_timeout,
            )
            logger.info("知识图谱后端: Neo4j | uri=%s", config.uri)
            return store
        except Exception as exc:  # noqa: BLE001
            logger.warning("Neo4j 不可用，降级为内存图存储 | err=%s", exc)
    return InMemoryGraphStore(policy=policy)


__all__ = [
    "GraphStore",
    "GraphStoreError",
    "GraphWriteError",
    "GraphWritePolicy",
    "InMemoryGraphStore",
    "Subgraph",
    "create_graph_store",
]
