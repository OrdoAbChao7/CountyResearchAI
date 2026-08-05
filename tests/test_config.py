"""配置加载测试(Settings / load_settings / _merge_env / _resolve_paths)。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from county_research_ai.config import (
    CONFIG_DIR,
    PROJECT_ROOT,
    Settings,
    get_settings,
    load_settings,
    reset_settings,
)


class TestSettingsDefaults:
    def test_default_llm_config(self):
        s = Settings()
        assert s.llm.provider == "deepseek"
        assert s.llm.model == "deepseek-chat"
        assert s.llm.temperature == 0.3
        assert s.llm.max_tokens == 4096
        assert s.llm.timeout == 60
        assert "industry_status" in s.llm.tasks
        assert len(s.llm.tasks) == 4

    def test_default_search_config(self):
        s = Settings()
        assert s.search.provider == "tavily"
        assert s.search.max_results == 10
        assert s.search.timeout == 30
        assert s.search.concurrency == 3
        assert s.search.fetch_detail is True

    def test_default_pipeline_config(self):
        s = Settings()
        assert s.pipeline.mode == "sequential"
        assert s.pipeline.fail_fast is True
        assert s.pipeline.stages.search is True
        assert s.pipeline.stages.analyze is True

    def test_path_constants(self):
        s = Settings()
        assert s.project_root == PROJECT_ROOT
        assert s.config_dir == CONFIG_DIR


class TestSettingsSingleton:
    def test_get_settings_returns_same_instance(self):
        reset_settings()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_reset_settings_creates_new_instance(self):
        reset_settings()
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2


class TestMergeEnv:
    def test_llm_provider_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "qwen")
        monkeypatch.setenv("LLM_API_KEY", "sk-test-123")
        monkeypatch.setenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        monkeypatch.setenv("LLM_MODEL", "qwen-plus")

        reset_settings()
        # load_settings 会读 .env,但 env 优先级更高
        # 为避免 .env 干扰,直接调 _merge_env
        from county_research_ai.config import _merge_env
        merged = _merge_env({})
        assert merged["llm"]["provider"] == "qwen"
        assert merged["llm"]["api_key"] == "sk-test-123"
        assert merged["llm"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert merged["llm"]["model"] == "qwen-plus"

    def test_empty_api_key_not_merged(self, monkeypatch):
        """空字符串的 API Key 不应被合并(触发 Mock 降级的关键)。"""
        monkeypatch.setenv("LLM_API_KEY", "")
        from county_research_ai.config import _merge_env
        merged = _merge_env({})
        assert "api_key" not in merged.get("llm", {})

    def test_search_provider_key_mapping(self, monkeypatch):
        monkeypatch.setenv("SEARCH_PROVIDER", "serper")
        monkeypatch.setenv("SERPER_API_KEY", "serper-test-key")
        from county_research_ai.config import _merge_env
        merged = _merge_env({})
        assert merged["search"]["provider"] == "serper"
        assert merged["search"]["api_key"] == "serper-test-key"

    def test_tavily_key_mapping(self, monkeypatch):
        monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")
        from county_research_ai.config import _merge_env
        merged = _merge_env({})
        assert merged["search"]["api_key"] == "tvly-test-key"

    def test_numeric_env_conversion(self, monkeypatch):
        monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
        monkeypatch.setenv("LLM_MAX_TOKENS", "8192")
        monkeypatch.setenv("LLM_TIMEOUT", "120")
        monkeypatch.setenv("SEARCH_MAX_RESULTS", "20")
        from county_research_ai.config import _merge_env
        merged = _merge_env({})
        assert merged["llm"]["temperature"] == 0.7
        assert merged["llm"]["max_tokens"] == 8192
        assert merged["llm"]["timeout"] == 120
        assert merged["search"]["max_results"] == 20

    def test_storage_dir_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "custom_data"))
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "custom_reports"))
        from county_research_ai.config import _merge_env
        merged = _merge_env({})
        assert merged["storage"]["data_dir"] == str(tmp_path / "custom_data")
        assert merged["storage"]["reports_dir"] == str(tmp_path / "custom_reports")


class TestResolvePaths:
    def test_default_paths(self):
        s = Settings()
        # 未设置 storage.data_dir 时,使用项目默认路径
        assert s.data_dir == PROJECT_ROOT / "data"
        assert s.reports_dir == PROJECT_ROOT / "reports"

    def test_custom_paths(self, tmp_path):
        s = Settings(
            storage={"data_dir": str(tmp_path / "mydata"), "reports_dir": str(tmp_path / "myreports")},
        )
        assert s.storage.data_dir == str(tmp_path / "mydata")
        # _resolve_paths 在 load_settings 中调用,直接构造 Settings 不会自动解析
        # 需手动调用
        from county_research_ai.config import _resolve_paths
        s = _resolve_paths(s)
        assert s.data_dir == (tmp_path / "mydata").resolve()
        assert s.reports_dir == (tmp_path / "myreports").resolve()


class TestLoadSettings:
    def test_load_with_yaml(self):
        """load_settings 能正常加载 config/settings.yaml。"""
        reset_settings()
        s = load_settings()
        assert s.app.name == "AI县域产业研究助手"
        assert s.app.version == "0.1.0"
        assert s.llm.temperature == 0.3
        assert s.pipeline.mode == "sequential"

    def test_get_settings_caches_in_singleton(self):
        """get_settings 单例:多次调用返回同一实例;load_settings 不写入单例。"""
        reset_settings()
        # get_settings 首次调用会触发 load_settings 并缓存
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        # load_settings 每次都创建新实例,不读取也不写入单例
        s3 = load_settings()
        assert s3 is not s1
