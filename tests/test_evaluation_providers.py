from __future__ import annotations

import json

import pytest

import county_research_ai.evaluation.providers as provider_module
from county_research_ai.evaluation.providers import (
    DeepSeekSearchAdapter,
    ProviderUsage,
    ResourceManagedFetchClient,
    ResourceManagedJudgeClient,
    ResourceManagedLLMClient,
    ResourceManagedSearchProvider,
    StrictProviderGuard,
)
from county_research_ai.evaluation.resource_manager import ResourceLimit, ResourceManager
from county_research_ai.exceptions import SearchError
from county_research_ai.llm.base import LLMResponse
from county_research_ai.mocks.llm import MockLLMClient
from county_research_ai.models import RawDoc


class FakeRealClient:
    name = "gemini"


def test_provider_usage_preserves_real_llm_usage():
    usage = ProviderUsage.from_llm_response(
        LLMResponse(
            content="ok",
            model="gemini-3.1-flash-lite",
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
        ),
        provider="gemini",
    )

    assert usage.known is True
    assert usage.total_tokens == 18
    assert usage.provider == "gemini"


def test_missing_llm_usage_is_unknown_not_zero():
    usage = ProviderUsage.from_llm_response(
        LLMResponse(content="ok", model="gemini-3.1-flash-lite"),
        provider="gemini",
    )

    assert usage.known is False
    assert usage.total_tokens is None


def test_strict_guard_rejects_mock_and_model_drift():
    guard = StrictProviderGuard(expected_model="gemini-3.1-flash-lite")
    guard.assert_real(FakeRealClient(), run_id="run-1")
    guard.assert_model("gemini-3.1-flash-lite")

    with pytest.raises(SearchError):
        guard.assert_real(MockLLMClient(), run_id="run-1")
    with pytest.raises(SearchError):
        guard.assert_model("gemini-2.5-flash")


def test_deepseek_adapter_is_disabled_by_default():
    adapter = DeepSeekSearchAdapter(api_key="not-used")

    with pytest.raises(SearchError, match="disabled_by_policy"):
        adapter.search("县域产业")


def test_deepseek_search_parses_metadata_and_deduplicates_content(
    monkeypatch: pytest.MonkeyPatch,
):
    requests: list[dict] = []

    class Response:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "title": "官方统计",
                        "url": "https://example.gov.cn/a",
                        "snippet": "摘要",
                        "content": "同一正文",
                        "published_date": "2026-01-02",
                        "score": 0.91,
                    },
                    {
                        "title": "重复正文",
                        "url": "https://example.gov.cn/b",
                        "content": "同一正文",
                        "published_date": "2026-01-03",
                        "score": 0.52,
                    },
                ]
            }

    class Client:
        def __init__(self, *, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def post(self, endpoint, *, headers, json):
            requests.append({"endpoint": endpoint, "headers": headers, "json": json})
            return Response()

    monkeypatch.setattr(provider_module.httpx, "Client", Client)
    adapter = DeepSeekSearchAdapter(api_key="secret", enabled=True)

    documents = adapter.search("县域产业", max_results=7)

    assert len(documents) == 1
    assert documents[0].title == "官方统计"
    assert documents[0].source == "deepseek-search"
    assert documents[0].metadata["published_date"] == "2026-01-02"
    assert documents[0].metadata["score"] == 0.91
    assert requests[0]["endpoint"] == adapter.SEARCH_ENDPOINT
    assert requests[0]["headers"]["Authorization"] == "Bearer secret"
    assert requests[0]["json"] == {"query": "县域产业", "count": 7}
    assert adapter.stats() == {
        "requests": 1,
        "successful_requests": 1,
        "failed_requests": 0,
    }


def test_deepseek_fetch_returns_raw_response_and_tracks_usage(
    monkeypatch: pytest.MonkeyPatch,
):
    class Response:
        status_code = 200

        def json(self):
            return {"url": "https://example.gov.cn/page", "content": "正文"}

    class Client:
        def __init__(self, *, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def post(self, endpoint, *, headers, json):
            assert endpoint == DeepSeekSearchAdapter.FETCH_ENDPOINT
            assert json == {"url": "https://example.gov.cn/page"}
            return Response()

    monkeypatch.setattr(provider_module.httpx, "Client", Client)
    adapter = DeepSeekSearchAdapter(api_key="secret", enabled=True)

    assert adapter.fetch("https://example.gov.cn/page") == {
        "url": "https://example.gov.cn/page",
        "content": "正文",
    }
    assert adapter.stats() == {
        "requests": 1,
        "successful_requests": 1,
        "failed_requests": 0,
    }


def test_deepseek_http_failure_is_counted_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
):
    class Response:
        status_code = 402

        def json(self):
            return {"error": "payment required"}

    class Client:
        def __init__(self, *, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def post(self, endpoint, *, headers, json):
            return Response()

    monkeypatch.setattr(provider_module.httpx, "Client", Client)
    adapter = DeepSeekSearchAdapter(api_key="secret", enabled=True)

    with pytest.raises(SearchError, match="DeepSeek HTTP 402") as error:
        adapter.search("县域产业")

    assert "secret" not in str(error.value)
    assert adapter.stats() == {
        "requests": 1,
        "successful_requests": 0,
        "failed_requests": 1,
    }


def test_deepseek_adapter_applies_minimum_request_interval(
    monkeypatch: pytest.MonkeyPatch,
):
    class Response:
        status_code = 200

        def json(self):
            return {"results": []}

    class Client:
        def __init__(self, *, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def post(self, endpoint, *, headers, json):
            return Response()

    times = iter((100.0, 100.0, 104.0, 104.0))
    sleeps: list[float] = []
    monkeypatch.setattr(provider_module.httpx, "Client", Client)
    monkeypatch.setattr(provider_module.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(provider_module.time, "sleep", sleeps.append)
    adapter = DeepSeekSearchAdapter(
        api_key="secret",
        enabled=True,
        min_interval_seconds=5.0,
    )

    adapter.search("第一次")
    adapter.search("第二次")

    assert sleeps == [1.0]


def test_resource_managed_llm_settles_provider_usage(tmp_path):
    class FakeLLM(FakeRealClient):
        def chat(self, messages, **kwargs):
            return LLMResponse(
                content="ok",
                model="gemini-3.1-flash-lite",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            )

    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={("gemini", "gemini-3.1-flash-lite", "llm"): ResourceLimit(4096)},
    )
    client = ResourceManagedLLMClient(
        FakeLLM(), manager=manager, provider="gemini", model="gemini-3.1-flash-lite", run_id="run-1"
    )

    client.chat([{"role": "user", "content": "hello"}], max_tokens=100)

    assert manager.snapshot().consumed[("gemini", "gemini-3.1-flash-lite", "llm")] == 15
    assert client.usage_known is True
    assert client.request_count == 1


def test_resource_managed_llm_can_account_for_judge_calls_separately(tmp_path):
    class FakeLLM(FakeRealClient):
        def chat(self, messages, **kwargs):
            return LLMResponse(
                content='{"dimensions":{"factual_accuracy":4}',
                model="judge-model",
                prompt_tokens=4,
                completion_tokens=3,
                total_tokens=7,
            )

    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={("gemini", "judge-model", "judge"): ResourceLimit(100)},
    )
    client = ResourceManagedJudgeClient(
        FakeLLM(),
        manager=manager,
        provider="gemini",
        model="judge-model",
        run_id="judge-run",
    )

    client.chat([{"role": "user", "content": "score"}], max_tokens=10)

    assert manager.snapshot().consumed[("gemini", "judge-model", "judge")] == 7


def test_resource_managed_fetch_settles_and_archives_real_response(tmp_path):
    class FakeFetch(FakeRealClient):
        name = "deepseek-fetch"

        def fetch(self, url):
            return {"url": url, "content": "page"}

    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={("deepseek", "fetch", "fetch"): ResourceLimit(2)},
    )
    client = ResourceManagedFetchClient(
        FakeFetch(),
        manager=manager,
        provider="deepseek",
        run_id="fetch-run",
        artifact_dir=tmp_path / "fetch_responses",
    )

    assert client.fetch("https://example.gov.cn/page")["content"] == "page"
    assert manager.snapshot().consumed[("deepseek", "fetch", "fetch")] == 1
    archived = list((tmp_path / "fetch_responses").glob("*.json"))
    assert len(archived) == 1
    assert "api_key" not in archived[0].read_text(encoding="utf-8")


def test_resource_managed_llm_marks_unknown_usage_without_fabricating_it(tmp_path):
    class FakeLLM(FakeRealClient):
        def chat(self, messages, **kwargs):
            return LLMResponse(content="ok", model="gemini-3.1-flash-lite")

    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={("gemini", "gemini-3.1-flash-lite", "llm"): ResourceLimit(100)},
    )
    client = ResourceManagedLLMClient(
        FakeLLM(),
        manager=manager,
        provider="gemini",
        model="gemini-3.1-flash-lite",
        run_id="run-unknown",
    )

    client.chat([{"role": "user", "content": "hello"}], max_tokens=10)

    assert client.usage_known is False
    assert client.request_count == 1


def test_resource_managed_llm_archives_raw_response_without_api_key(tmp_path):
    class FakeLLM(FakeRealClient):
        def chat(self, messages, **kwargs):
            return LLMResponse(
                content="raw response",
                model="gemini-3.1-flash-lite",
                prompt_tokens=2,
                completion_tokens=3,
                total_tokens=5,
            )

    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={("gemini", "gemini-3.1-flash-lite", "llm"): ResourceLimit(100)},
    )
    client = ResourceManagedLLMClient(
        FakeLLM(),
        manager=manager,
        provider="gemini",
        model="gemini-3.1-flash-lite",
        run_id="run-1",
        artifact_dir=tmp_path / "llm_responses",
    )

    client.chat([{"role": "user", "content": "hello"}], max_tokens=10)

    files = list((tmp_path / "llm_responses").glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["response"]["content"] == "raw response"
    assert payload["usage"]["total_tokens"] == 5
    assert "api_key" not in json.dumps(payload)


def test_resource_managed_search_settles_one_request(tmp_path):
    class FakeSearch:
        name = "tavily"

        def search(self, query, max_results=10):
            return [RawDoc(title="source", url="https://example.com")]

    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={("tavily", "search", "search"): ResourceLimit(2)},
    )
    provider = ResourceManagedSearchProvider(
        FakeSearch(), manager=manager, provider="tavily", run_id="run-1"
    )

    assert len(provider.search("query")) == 1
    assert manager.snapshot().consumed[("tavily", "search", "search")] == 1
