"""冻结 E2 固定输入文档包及其内容哈希。"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import RawDoc

_SCHEMA_VERSION = "1.0"
_ALLOWED_FIELDS = {
    "schema_version",
    "pack_id",
    "region",
    "focus",
    "mode",
    "documents",
    "source_hash",
}
_FORBIDDEN_FIELDS = {"ground_truth", "claims", "claim_id", "rubric", "judge"}


@dataclass(frozen=True)
class FixedInputPack:
    """E2 三组共享的、不可由运行组修改的原始文档集合。"""

    pack_id: str
    region: str
    focus: str
    mode: str
    documents: tuple[RawDoc, ...]
    source_hash: str

    @classmethod
    def create(
        cls,
        *,
        pack_id: str,
        region: str,
        focus: str,
        mode: str,
        documents: Iterable[RawDoc],
    ) -> FixedInputPack:
        normalized = tuple(documents)
        cls._validate_fields(pack_id=pack_id, region=region, focus=focus, mode=mode)
        cls._validate_documents(normalized)
        payload = cls._payload(
            pack_id=pack_id,
            region=region,
            focus=focus,
            mode=mode,
            documents=normalized,
        )
        return cls(
            pack_id=pack_id,
            region=region,
            focus=focus,
            mode=mode,
            documents=normalized,
            source_hash=cls._hash_payload(payload),
        )

    @classmethod
    def load(cls, path: Path) -> FixedInputPack:
        source = Path(path)
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read fixed-input pack: {source}") from exc
        if not isinstance(value, dict):
            raise ValueError("fixed-input pack must be a JSON object")
        unsupported = sorted(set(value) - _ALLOWED_FIELDS)
        if unsupported:
            raise ValueError(
                f"unsupported fixed-input field: {', '.join(unsupported)}"
            )
        if value.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported fixed-input schema version")
        documents_value = value.get("documents")
        if not isinstance(documents_value, list):
            raise ValueError("fixed-input documents must be a list")
        try:
            documents = tuple(RawDoc.model_validate(item) for item in documents_value)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invalid fixed-input document") from exc
        pack_id = str(value.get("pack_id", ""))
        region = str(value.get("region", ""))
        focus = str(value.get("focus", ""))
        mode = str(value.get("mode", ""))
        cls._validate_fields(pack_id=pack_id, region=region, focus=focus, mode=mode)
        cls._validate_documents(documents)
        expected_hash = value.get("source_hash")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise ValueError("fixed-input source_hash is required")
        payload = cls._payload(
            pack_id=pack_id,
            region=region,
            focus=focus,
            mode=mode,
            documents=documents,
        )
        actual_hash = cls._hash_payload(payload)
        if actual_hash != expected_hash:
            raise ValueError("fixed-input source_hash mismatch")
        return cls(
            pack_id=pack_id,
            region=region,
            focus=focus,
            mode=mode,
            documents=documents,
            source_hash=expected_hash,
        )

    def write(self, path: Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload(
            pack_id=self.pack_id,
            region=self.region,
            focus=self.focus,
            mode=self.mode,
            documents=self.documents,
        )
        actual_hash = self._hash_payload(payload)
        if actual_hash != self.source_hash:
            raise ValueError("fixed-input pack was modified after creation")
        return {**payload, "source_hash": self.source_hash}

    @staticmethod
    def _validate_fields(*, pack_id: str, region: str, focus: str, mode: str) -> None:
        if not all((pack_id, region, focus, mode)):
            raise ValueError("fixed-input pack identity fields are required")

    @staticmethod
    def _validate_documents(documents: tuple[RawDoc, ...]) -> None:
        if not documents:
            raise ValueError("fixed-input pack must contain documents")
        urls = [doc.url for doc in documents]
        if any(not url for url in urls):
            raise ValueError("fixed-input documents require URLs")
        if len(set(urls)) != len(urls):
            raise ValueError("duplicate document URL in fixed-input pack")
        for document in documents:
            metadata_keys = {str(key).lower() for key in document.metadata}
            if metadata_keys & _FORBIDDEN_FIELDS:
                raise ValueError("fixed-input document contains evaluation-only fields")

    @staticmethod
    def _payload(
        *,
        pack_id: str,
        region: str,
        focus: str,
        mode: str,
        documents: tuple[RawDoc, ...],
    ) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "pack_id": pack_id,
            "region": region,
            "focus": focus,
            "mode": mode,
            "documents": [doc.model_dump(mode="json") for doc in documents],
        }

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(content).hexdigest()
