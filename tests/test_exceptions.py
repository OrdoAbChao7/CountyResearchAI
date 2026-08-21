"""异常层次测试(CountyResearchAIError 及子类)。"""
from __future__ import annotations

import pytest

from county_research_ai.exceptions import (
    ConfigError,
    CountyResearchAIError,
    LLMError,
    PipelineError,
    ReportError,
    SearchError,
    StorageError,
)


class TestCountyResearchAIError:
    def test_message_stored(self):
        e = CountyResearchAIError("出错了")
        assert e.message == "出错了"

    def test_context_default_empty(self):
        e = CountyResearchAIError("err")
        assert e.context == {}

    def test_context_stored(self):
        e = CountyResearchAIError("err", context={"key": "value", "n": 42})
        assert e.context["key"] == "value"
        assert e.context["n"] == 42

    def test_str_without_context(self):
        e = CountyResearchAIError("简单错误")
        assert str(e) == "简单错误"

    def test_str_with_context(self):
        e = CountyResearchAIError("错误", context={"detail": "xxx"})
        s = str(e)
        assert "错误" in s
        assert "context=" in s
        assert "xxx" in s

    def test_is_exception_subclass(self):
        e = CountyResearchAIError("err")
        assert isinstance(e, Exception)


class TestExceptionHierarchy:
    """所有子异常都应继承 CountyResearchAIError,便于上层统一捕获。"""

    @pytest.mark.parametrize(
        "exc_cls",
        [ConfigError, SearchError, StorageError, LLMError, ReportError, PipelineError],
    )
    def test_inherits_from_base(self, exc_cls):
        e = exc_cls("test")
        assert isinstance(e, CountyResearchAIError)
        assert isinstance(e, Exception)

    def test_config_error_context(self):
        e = ConfigError("配置缺失", context={"field": "LLM_API_KEY"})
        assert e.context["field"] == "LLM_API_KEY"

    def test_search_error_context(self):
        e = SearchError("搜索失败", context={"query": "安吉县", "status": 429})
        assert e.context["query"] == "安吉县"

    def test_storage_error_context(self):
        e = StorageError("写入失败", context={"path": "/tmp/x"})
        assert e.context["path"] == "/tmp/x"

    def test_llm_error_context(self):
        e = LLMError("LLM 超时", context={"model": "deepseek-chat"})
        assert e.context["model"] == "deepseek-chat"

    def test_pipeline_error_context(self):
        e = PipelineError("阶段失败", context={"stage": "search"})
        assert e.context["stage"] == "search"

    def test_catch_all_via_base(self):
        """用基类可以统一捕获所有子异常。"""
        errors = [
            ConfigError("c"),
            SearchError("s"),
            StorageError("st"),
            LLMError("l"),
            ReportError("r"),
            PipelineError("p"),
        ]
        for e in errors:
            try:
                raise e
            except CountyResearchAIError as caught:
                assert caught is e
