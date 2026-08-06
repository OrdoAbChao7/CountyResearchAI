"""pytest 共享 fixtures。

职责:
    1. 将 src/ 加入 sys.path(无需 pip install -e .)
    2. 每个测试前重置全局 Settings 单例(避免状态泄漏)
    3. 提供常用测试对象:临时 Settings / MockLLM / 示例数据
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 确保 src 在路径中
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest
from pydantic import SecretStr

from county_research_ai.config import (
    AppConfig,
    CacheConfig,
    LLMConfig,
    LoggingConfig,
    PipelineConfig,
    PipelineStages,
    SearchConfig,
    SearchRetryConfig,
    Settings,
    StorageConfig,
    reset_settings,
)
from county_research_ai.llm.base import LLMClient, LLMResponse
from county_research_ai.models import CountyInfo, ProcessedData, RawDoc


# ===== autouse: 每个测试前后重置全局 Settings =====


@pytest.fixture(autouse=True)
def _reset_global_settings(monkeypatch):
    """每个测试前:阻止 .env 加载 + 清掉 API key 环境变量 + 重置 Settings 单例。

    确保测试不依赖 .env 的真实 key,始终走 Mock 降级路径。
    """
    # 阻止 load_settings() 调用 load_dotenv 把 .env 的真实 key 注入环境
    monkeypatch.setattr("county_research_ai.config.load_dotenv", lambda *a, **kw: False)
    # 清掉系统环境变量中可能残留的 API key(防止真实网络调用)
    for key in ("LLM_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY", "BING_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    reset_settings()
    yield
    reset_settings()


# ===== Settings fixtures =====


@pytest.fixture
def tmp_settings(tmp_path) -> Settings:
    """使用临时目录的 Settings(不依赖 .env,不读写真实项目目录)。"""
    return Settings(
        app=AppConfig(),
        llm=LLMConfig(),
        search=SearchConfig(
            provider="tavily",
            api_key=SecretStr("test-key"),
            max_results=5,
            timeout=5,
            concurrency=2,
            retry=SearchRetryConfig(max_attempts=1, backoff_seconds=0),
            fetch_detail=False,
        ),
        storage=StorageConfig(
            data_dir=str(tmp_path / "data"),
            reports_dir=str(tmp_path / "reports"),
        ),
        cache=CacheConfig(enabled=False),
        pipeline=PipelineConfig(fail_fast=True, stages=PipelineStages()),
        logging=LoggingConfig(level="WARNING"),
    )


@pytest.fixture
def tmp_settings_no_key(tmp_path) -> Settings:
    """无 API Key 的 Settings(模拟降级场景)。"""
    return Settings(
        app=AppConfig(),
        llm=LLMConfig(),
        search=SearchConfig(
            provider="tavily",
            api_key=SecretStr(""),
        ),
        storage=StorageConfig(
            data_dir=str(tmp_path / "data"),
            reports_dir=str(tmp_path / "reports"),
        ),
        cache=CacheConfig(enabled=False),
        pipeline=PipelineConfig(fail_fast=True, stages=PipelineStages()),
        logging=LoggingConfig(level="WARNING"),
    )


# ===== Mock LLM =====


class MockLLM(LLMClient):
    """记录调用次数与 prompt 的 Mock LLM(不依赖真实 API)。

    根据 prompt 内容返回不同的构造文本,便于断言 task 路由。
    """

    name = "test-mock-llm"

    def __init__(self) -> None:
        self.call_count = 0
        self.calls: list[str] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1
        user_msg = messages[-1].get("content", "") if messages else ""
        self.calls.append(user_msg)

        if "产业方向" in user_msg and "识别" in user_msg:
            content = (
                '{"candidates": ['
                '{"industry": "特色农业", "confidence": 0.85, '
                '"reason": "搜索结果显示该县农业占GDP 30%,规上企业80家", '
                '"evidence_urls": ["https://example.gov.cn/tjgb-1", "https://example.gov.cn/fzgh-2"], '
                '"related_keywords": ["年产值", "规上企业", "产业链"], '
                '"supporting_documents": ["某县2025年统计公报", "十四五产业发展规划"]}, '
                '{"industry": "乡村旅游", "confidence": 0.7, '
                '"reason": "多个政府规划提到乡村旅游", '
                '"evidence_urls": ["https://example.gov.cn/fzgh-2"], '
                '"related_keywords": ["文旅", "乡村", "民宿"], '
                '"supporting_documents": ["十四五产业发展规划"]}, '
                '{"industry": "先进制造业", "confidence": 0.55, '
                '"reason": "有省级工业园区", '
                '"evidence_urls": ["https://example.com/news/1"], '
                '"related_keywords": ["工业园区", "制造业"], '
                '"supporting_documents": ["龙头XX股份带动产业升级"]}'
                '], "selected_focus": "特色农业"}'
            )
        elif "优势" in user_msg:
            content = "## 核心优势\n1. 资源禀赋突出\n2. 产业基础扎实"
        elif "短板" in user_msg or "风险" in user_msg:
            content = "## 主要短板\n1. 精深加工不足\n2. 品牌辨识度弱"
        elif "建议" in user_msg or "对策" in user_msg:
            content = "## 建议\n短期:技改补贴\n中期:品牌建设"
        elif "摘要" in user_msg or "执行摘要" in user_msg or "关键发现" in user_msg:
            content = "该县该产业已形成完整链条,处于成长期后期,建议补强精深加工。"
        else:
            content = "## 产业概况\n该县该产业产值120亿,规上企业82家。"

        return LLMResponse(
            content=content,
            model="test-mock-v1",
            prompt_tokens=500,
            completion_tokens=800,
            total_tokens=1300,
        )


@pytest.fixture
def mock_llm() -> MockLLM:
    return MockLLM()


# ===== 数据 fixtures =====


@pytest.fixture
def sample_county() -> CountyInfo:
    return CountyInfo.from_name("安吉县")


@pytest.fixture
def sample_docs() -> list[RawDoc]:
    return [
        RawDoc(
            title="安吉县竹产业产值突破百亿",
            url="https://example.gov.cn/安吉县/tjgb-1",
            snippet="安吉县竹产业产值百亿",
            content="竹产业产值120亿" * 5,
            source="mock",
        ),
        RawDoc(
            title="龙头企业XX股份带动产业升级",
            url="https://example.com/news/top-enterprise",
            snippet="龙头企业XX股份",
            content="龙头企业XX股份" * 5,
            source="mock",
        ),
    ]


@pytest.fixture
def sample_processed_data(sample_county, sample_docs) -> ProcessedData:
    return ProcessedData(
        county=sample_county,
        focus="竹产业",
        docs=sample_docs,
        total_chars=200,
    )
