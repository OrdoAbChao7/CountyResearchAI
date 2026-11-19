"""证据服务:运行期绑定的结构化证据库。

每个研究运行拥有独立的 ``EvidenceService``（内部一个 ``EvidenceStore``），
并行 Agent 通过锁安全地写入/读取证据。
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from pathlib import Path

from ..evidence.store import EvidenceStore
from ..models import (
    EvidenceConflict,
    EvidenceGap,
    EvidenceItem,
    QuestionTree,
    RawDoc,
)

logger = logging.getLogger(__name__)


class EvidenceService:
    """线程安全的证据读写与审计服务。"""

    def __init__(self, store: EvidenceStore | None = None) -> None:
        self._store = store or EvidenceStore()
        self._lock = threading.RLock()

    # ---- 写入 ----

    def ingest(self, docs: Iterable[RawDoc], *, county: str, focus: str = "") -> list[EvidenceItem]:
        """摄入原始文档并抽取结构化证据，返回新增证据项。"""
        doc_list = list(docs)
        if not doc_list:
            return []
        with self._lock:
            return self._store.ingest_documents(doc_list, county=county, focus=focus)

    def add(self, item: EvidenceItem) -> EvidenceItem:
        with self._lock:
            self._store.add_evidence(item)
        return item

    # ---- 读取 ----

    def get(self, evidence_id: str) -> EvidenceItem | None:
        with self._lock:
            return next((it for it in self._store.get_all() if it.id == evidence_id), None)

    def all(self, *, limit: int = 0) -> list[EvidenceItem]:
        with self._lock:
            items = self._store.get_all()
        return items[:limit] if limit else items

    def by_topic(self, topic: str) -> list[EvidenceItem]:
        with self._lock:
            return self._store.get_by_topic(topic)

    def by_ids(self, ids: Iterable[str]) -> list[EvidenceItem]:
        wanted = [i for i in ids if i]
        if not wanted:
            return []
        with self._lock:
            items = self._store.get_all()
        index = {it.id: it for it in items}
        return [index[i] for i in wanted if i in index]

    def search(self, keywords: list[str], *, topic: str = "", limit: int = 10) -> list[EvidenceItem]:
        """按关键词在 claim / snippet / title 上做包含匹配，按可信度排序。"""
        terms = [k.strip() for k in keywords if k and k.strip()]
        with self._lock:
            pool = self._store.get_by_topic(topic) if topic else self._store.get_all()
        if not terms:
            scored = [(it.credibility_score, it) for it in pool]
        else:
            scored = []
            for item in pool:
                haystack = f"{item.claim} {item.snippet} {item.title} {item.indicator_caliber}"
                hits = sum(1 for term in terms if term in haystack)
                if hits:
                    scored.append((hits + item.credibility_score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def conflicts(self) -> list[EvidenceConflict]:
        with self._lock:
            return list(self._store.get_conflicts())

    def coverage(self, question_tree: QuestionTree) -> tuple[float, list[EvidenceGap]]:
        with self._lock:
            return self._store.assess_question_tree_coverage(question_tree)

    # ---- 渲染 / 持久化 ----

    def citations_markdown(self) -> str:
        with self._lock:
            return self._store.render_citations_table()

    def conflicts_markdown(self) -> str:
        with self._lock:
            return self._store.render_conflicts_section()

    def render_for_prompt(self, *, limit: int = 30, max_chars: int = 8000) -> str:
        """渲染为 Agent prompt 中的证据清单（带 Evidence ID）。"""
        items = sorted(self.all(limit=limit), key=lambda x: x.credibility_score, reverse=True)
        lines: list[str] = []
        used = 0
        for item in items:
            line = (
                f"[{item.id}] ({item.verification_status}, 可信度{item.credibility_score:.2f}, "
                f"{item.year or '年份未注明'}) {item.claim} —— {item.title} {item.url}"
            )
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines) if lines else "（当前证据库为空）"

    def evidence_ids(self, limit: int = 0) -> list[str]:
        return [item.id for item in self.all(limit=limit)]

    def snapshot(self) -> list[dict]:
        return [item.model_dump(mode="json") for item in self.all()]

    def persist(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, path: Path) -> int:
        """从快照恢复证据（用于运行恢复）。返回加载条数。"""
        if not path.exists():
            return 0
        payload = json.loads(path.read_text(encoding="utf-8"))
        count = 0
        for raw in payload:
            self.add(EvidenceItem.model_validate(raw))
            count += 1
        return count

    def stats(self) -> dict[str, int]:
        items = self.all()
        return {
            "total": len(items),
            "verified": sum(1 for i in items if i.verification_status == "verified"),
            "unverified": sum(1 for i in items if i.verification_status != "verified"),
            "conflicts": len(self.conflicts()),
        }


__all__ = ["EvidenceService"]
