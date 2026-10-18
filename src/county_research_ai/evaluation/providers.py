"""独立实验使用的 Provider Usage、真实性检查和 DeepSeek 适配器。"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from ..exceptions import SearchError
from ..llm.base import LLMResponse
from ..models import RawDoc
from ..search.base import SearchProvider
from .resource_manager import ResourceManager, ResourceRequest


@dataclass(frozen=True)
class ProviderUsage:
    provider: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    known: bool
    requests: int = 1
    credits: float | None = None

    @classmethod
    def from_llm_response(cls, response: LLMResponse, *, provider: str) -> ProviderUsage:
        values = (response.prompt_tokens, response.completion_tokens, response.total_tokens)
        known = any(value > 0 for value in values)
        return cls(
            provider=provider,
            model=response.model,
            prompt_tokens=response.prompt_tokens if known else None,
            completion_tokens=response.completion_tokens if known else None,
            total_tokens=response.total_tokens if known else None,
            known=known,
        )


class StrictProviderGuard:
    """拒绝 Mock、未配置模型和跨批次模型漂移。"""

    def __init__(self, *, expected_model: str) -> None:
        self.expected_model = expected_model

    def assert_real(self, provider: Any, *, run_id: str) -> None:
        if not run_id:
            raise SearchError("run_id is required for strict provider execution")
        class_name = type(provider).__name__.lower()
        module_name = type(provider).__module__.lower()
        provider_name = str(getattr(provider, "name", "")).lower()
        if class_name.startswith("mock") or ".mocks" in module_name or provider_name.startswith("mock"):
            raise SearchError(
                "Mock provider is not valid for a real experiment",
                context={"run_id": run_id, "provider_type": type(provider).__name__},
            )

    def assert_model(self, actual_model: str) -> None:
        if actual_model != self.expected_model:
            raise SearchError(
                "provider model does not match frozen experiment model",
                context={"expected_model": self.expected_model, "actual_model": actual_model},
            )


class ResourceManagedLLMClient:
    """在每次 LLM 调用边界接入 Resource Manager 的包装器。"""

    def __init__(
        self,
        delegate: Any,
        *,
        manager: ResourceManager,
        provider: str,
        model: str,
        run_id: str,
        artifact_dir: Path | None = None,
        resource_kind: str = "llm",
    ) -> None:
        self._delegate = delegate
        self._manager = manager
        self._provider = provider
        self._model = model
        self._run_id = run_id
        self._resource_kind = resource_kind
        self._artifact_dir = Path(artifact_dir) if artifact_dir is not None else None
        self._call_index = 0
        self._request_count = 0
        self._usage_known = True
        if self._artifact_dir is not None:
            self._artifact_dir.mkdir(parents=True, exist_ok=True)
        StrictProviderGuard(expected_model=model).assert_real(delegate, run_id=run_id)

    @property
    def name(self) -> str:
        return str(getattr(self._delegate, "name", self._provider))

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def usage_known(self) -> bool:
        """只有至少有一次成功调用且所有调用都返回 Usage 时才为真。"""
        return self._request_count > 0 and self._usage_known

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        request = ResourceRequest(
            provider=self._provider,
            model=self._model,
            kind=self._resource_kind,
            units=max_tokens or 1,
            run_id=self._run_id,
        )
        lease = self._manager.reserve(request)
        try:
            response = self._delegate.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            StrictProviderGuard(expected_model=self._model).assert_model(response.model)
            usage = ProviderUsage.from_llm_response(response, provider=self._provider)
            self._request_count += 1
            self._usage_known = self._usage_known and usage.known
            self._archive_response(messages, response, usage)
            settled_units = usage.total_tokens if usage.known and usage.total_tokens is not None else lease.reserved_units
            self._manager.settle(lease.lease_id, settled_units, usage=asdict(usage))
            return response
        except Exception as exc:
            try:
                self._manager.fail(lease.lease_id, type(exc).__name__)
            except Exception:
                pass
            raise

    def _archive_response(
        self,
        messages: list[dict[str, str]],
        response: LLMResponse,
        usage: ProviderUsage,
    ) -> None:
        if self._artifact_dir is None:
            return
        self._call_index += 1
        payload = {
            "run_id": self._run_id,
            "provider": self._provider,
            "model": response.model,
            "messages": messages,
            "response": response.model_dump(),
            "usage": asdict(usage),
        }
        path = self._artifact_dir / f"{self._call_index:04d}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def complete(self, prompt: str, system: str = "", **kwargs: Any) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, **kwargs).content


class ResourceManagedJudgeClient(ResourceManagedLLMClient):
    """Judge 专用 LLM 包装器，单独按 kind=judge 记账。"""

    def __init__(
        self,
        delegate: Any,
        *,
        manager: ResourceManager,
        provider: str,
        model: str,
        run_id: str,
        artifact_dir: Path | None = None,
    ) -> None:
        super().__init__(
            delegate,
            manager=manager,
            provider=provider,
            model=model,
            run_id=run_id,
            artifact_dir=artifact_dir,
            resource_kind="judge",
        )


class ResourceManagedSearchProvider(SearchProvider):
    """在每次搜索请求边界接入 Resource Manager 的包装器。"""

    def __init__(
        self,
        delegate: SearchProvider,
        *,
        manager: ResourceManager,
        provider: str,
        run_id: str,
    ) -> None:
        self._delegate = delegate
        self._manager = manager
        self._provider = provider
        self._run_id = run_id
        StrictProviderGuard(expected_model="search").assert_real(delegate, run_id=run_id)

    @property
    def name(self) -> str:
        return self._provider

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        request = ResourceRequest(
            provider=self._provider,
            model="search",
            kind="search",
            units=1,
            run_id=self._run_id,
        )
        lease = self._manager.reserve(request)
        try:
            documents = self._delegate.search(query, max_results=max_results)
            self._manager.settle(
                lease.lease_id,
                1,
                usage={"provider": self._provider, "results": len(documents)},
            )
            return documents
        except Exception as exc:
            try:
                self._manager.fail(lease.lease_id, type(exc).__name__)
            except Exception:
                pass
            raise


class ResourceManagedFetchClient:
    """为 DeepSeek 等 Fetch Provider 接入统一资源账本。"""

    def __init__(
        self,
        delegate: Any,
        *,
        manager: ResourceManager,
        provider: str,
        run_id: str,
        artifact_dir: Path | None = None,
    ) -> None:
        self._delegate = delegate
        self._manager = manager
        self._provider = provider
        self._run_id = run_id
        self._artifact_dir = Path(artifact_dir) if artifact_dir is not None else None
        self._call_index = 0
        if self._artifact_dir is not None:
            self._artifact_dir.mkdir(parents=True, exist_ok=True)
        StrictProviderGuard(expected_model="fetch").assert_real(delegate, run_id=run_id)

    @property
    def name(self) -> str:
        return str(getattr(self._delegate, "name", self._provider))

    def fetch(self, url: str) -> dict[str, Any]:
        lease = self._manager.reserve(
            ResourceRequest(
                provider=self._provider,
                model="fetch",
                kind="fetch",
                units=1,
                run_id=self._run_id,
            )
        )
        try:
            result = self._delegate.fetch(url)
            self._manager.settle(
                lease.lease_id,
                1,
                usage={"provider": self._provider, "url": url},
            )
            self._archive_response(url, result)
            return result
        except Exception as exc:
            try:
                self._manager.fail(lease.lease_id, type(exc).__name__)
            except Exception:
                pass
            raise

    def _archive_response(self, url: str, result: dict[str, Any]) -> None:
        if self._artifact_dir is None:
            return
        self._call_index += 1
        path = self._artifact_dir / f"{self._call_index:04d}.json"
        path.write_text(
            json.dumps(
                {"run_id": self._run_id, "provider": self._provider, "url": url, "response": result},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

class DeepSeekSearchAdapter:
    """DeepSeek Search/Fetch 原始 HTTP 适配器。

    直接 HTTP 调用默认关闭，因为该接口按成功请求收费。开启必须由调用方
    显式传入 ``enabled=True``，实验协议仍需在 Resource Manager 中放行。
    """

    SEARCH_ENDPOINT = "https://api.deepseek.com/v1/tools/search"
    FETCH_ENDPOINT = "https://api.deepseek.com/v1/tools/fetch"
    name = "deepseek-search"

    def __init__(
        self,
        api_key: str,
        *,
        enabled: bool = False,
        timeout: float = 30.0,
        min_interval_seconds: float = 0.0,
    ) -> None:
        self._api_key = api_key
        self._enabled = enabled
        self._timeout = timeout
        self._min_interval = max(0.0, min_interval_seconds)
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._stats = {"requests": 0, "successful_requests": 0, "failed_requests": 0}

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        payload = {"query": query, "count": max_results}
        data = self._post(self.SEARCH_ENDPOINT, payload)
        docs: list[RawDoc] = []
        seen_urls: set[str] = set()
        seen_content: set[str] = set()
        for item in data.get("results", []):
            url = str(item.get("url", ""))
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            content = str(item.get("content", item.get("snippet", "")))
            content_key = content.strip()
            if content_key and content_key in seen_content:
                continue
            if content_key:
                seen_content.add(content_key)
            docs.append(
                RawDoc(
                    title=str(item.get("title", "")),
                    url=url,
                    snippet=str(item.get("snippet", item.get("content", ""))),
                    content=content,
                    source=self.name,
                    metadata={
                        "published_date": item.get("published_date"),
                        "score": item.get("score"),
                        "raw_result": item,
                    },
                )
            )
        return docs

    def fetch(self, url: str) -> dict[str, Any]:
        return self._post(self.FETCH_ENDPOINT, {"url": url})

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_enabled()
        with self._lock:
            delay = self._min_interval - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            self._last_request = time.monotonic()
            self._stats["requests"] += 1
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if response.status_code >= 400:
                raise SearchError(
                    f"DeepSeek HTTP {response.status_code}",
                    context={"endpoint": endpoint, "status_code": response.status_code},
                )
            data = response.json()
            with self._lock:
                self._stats["successful_requests"] += 1
            return data
        except SearchError:
            with self._lock:
                self._stats["failed_requests"] += 1
            raise
        except (httpx.HTTPError, ValueError) as exc:
            with self._lock:
                self._stats["failed_requests"] += 1
            raise SearchError(
                "DeepSeek response or network error",
                context={"endpoint": endpoint, "error_type": type(exc).__name__},
            ) from exc

    def _ensure_enabled(self) -> None:
        if not self._api_key:
            raise SearchError("DeepSeek API key is missing")
        if not self._enabled:
            raise SearchError("DeepSeek Search/Fetch is disabled_by_policy")
