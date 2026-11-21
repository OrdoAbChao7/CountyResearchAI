"""LangGraph 检查点：SQLite 持久化，缺失时退回内存。

- thread_id = run_id，一个研究运行对应一个可恢复线程；
- 检查点只保存 JSON 可序列化的图状态；
- 证据/文档/报告由 RunArtifacts 单独持久化。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

logger = logging.getLogger(__name__)

_SAVER_LOCK = threading.Lock()


def create_checkpointer(
    path: Path | None = None,
) -> tuple[Any, str]:
    """返回 (saver, backend_name)。

    SQLite 失败时自动退回 InMemorySaver，并记录警告——这保证测试环境
    与未安装可选依赖时仍可运行，但会失去跨进程恢复能力。
    """
    if path is not None:
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver

            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(path), check_same_thread=False, timeout=30
            )
            saver = SqliteSaver(conn)
            return saver, "sqlite"
        except Exception as exc:  # noqa: BLE001
            logger.warning("SQLite 检查点不可用，退回内存检查点 | err=%s", exc)
    return InMemorySaver(), "memory"


def run_config(
    run_id: str,
    *,
    services: Any,
    context: Any,
    artifacts: Any = None,
    emitter: Any = None,
    recursion_limit: int = 120,
) -> dict[str, Any]:
    """构造 LangGraph 运行配置。运行期对象只放在 configurable 中。"""
    return {
        "configurable": {
            "thread_id": run_id,
            "run_id": run_id,
            "services": services,
            "context": context,
            "artifacts": artifacts,
            "emitter": emitter,
        },
        "recursion_limit": max(20, int(recursion_limit)),
    }


def thread_id(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}}


def state_values(graph: Any, run_id: str) -> dict[str, Any]:
    try:
        snapshot = graph.get_state(thread_id(run_id))
    except Exception:  # noqa: BLE001
        return {}
    return dict(snapshot.values or {})


__all__ = [
    "create_checkpointer",
    "run_config",
    "state_values",
    "thread_id",
]
