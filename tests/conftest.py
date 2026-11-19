"""pytest 共享 fixtures（V2）。

- 阻止 .env 的真实 key 进入测试；
- 提供临时 Settings / 搜索 / 完整 V2 容器 / API 客户端；
- 所有外部服务（LLM、搜索、Neo4j）默认使用 Mock 或内存实现。
"""
from __future__ import annotations

# ruff: noqa: E402  # src/ is inserted before importing the package under test.
import sys
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest
from pydantic import SecretStr

from county_research_ai.config import (
    AgentRuntimeConfig,
    APIConfig,
    AppConfig,
    CacheConfig,
    GraphDBConfig,
    LLMConfig,
    LoggingConfig,
    QualityConfig,
    RuntimeConfig,
    SearchConfig,
    SearchRetryConfig,
    Settings,
    SimulationConfig,
    StorageConfig,
    TemporalConfig,
    reset_settings,
)
from county_research_ai.llm.base import LLMClient, LLMResponse
from county_research_ai.models import CountyInfo, ProcessedData, RawDoc
from county_research_ai.search.base import SearchProvider


@pytest.fixture(autouse=True)
def _reset_global_settings(monkeypatch):
    """每个测试前阻止 .env 加载并清掉 API key 环境变量。"""
    monkeypatch.setattr("county_research_ai.config.load_dotenv", lambda *a, **kw: False)
    for key in (
        "LLM_API_KEY",
        "TAVILY_API_KEY",
        "SERPER_API_KEY",
        "BING_API_KEY",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_SEARCH_ENABLED",
        "GRAPH_BACKEND",
        "NEO4J_URI",
        "NEO4J_PASSWORD",
        "RUNS_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    reset_settings()
    yield
    reset_settings()


def _settings(tmp_path: Path) -> Settings:
    settings = Settings(
        app=AppConfig(),
        llm=LLMConfig(api_key=SecretStr(""), max_tokens=1024, timeout=10),
        search=SearchConfig(
            provider="tavily",
            api_key=SecretStr(""),
            max_results=5,
            timeout=5,
            concurrency=1,
            retry=SearchRetryConfig(max_attempts=1, backoff_seconds=0),
            fetch_detail=False,
        ),
        storage=StorageConfig(
            data_dir=str(tmp_path / "data"),
            reports_dir=str(tmp_path / "reports"),
        ),
        cache=CacheConfig(enabled=False),
        quality=QualityConfig(min_content_length=10),
        logging=LoggingConfig(level="WARNING"),
        runtime=RuntimeConfig(fail_fast=False),
        agents=AgentRuntimeConfig(
            max_steps=4,
            max_llm_calls=4,
            max_specialists=6,
            max_rounds=2,
            max_followup_queries=3,
            recursion_limit=120,
        ),
        graph=GraphDBConfig(backend="memory"),
        api=APIConfig(max_concurrent_runs=1),
        simulation=SimulationConfig(enabled=True, engine="baseline"),
        temporal=TemporalConfig(enabled=True),
    )
    settings.data_dir = tmp_path / "data"
    settings.reports_dir = tmp_path / "reports"
    settings.runs_dir = tmp_path / "runs"
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    return settings


@pytest.fixture
def tmp_settings(tmp_path) -> Settings:
    settings = _settings(tmp_path)
    settings.search.api_key = SecretStr("test-key")
    settings.llm.api_key = SecretStr("test-key")
    settings.runtime.fail_fast = True
    return settings


@pytest.fixture
def tmp_settings_no_key(tmp_path) -> Settings:
    return _settings(tmp_path)


# ===== Mock LLM（文本型，供旧分析器测试） =====


class MockLLM(LLMClient):
    """记录调用次数与 prompt 的 Mock LLM。"""

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
                '"evidence_urls": ["https://example.gov.cn/tjgb-1"], '
                '"related_keywords": ["年产值", "规上企业", "产业链"], '
                '"supporting_documents": ["某县2025年统计公报"]}, '
                '{"industry": "乡村旅游", "confidence": 0.7, '
                '"reason": "多个政府规划提到乡村旅游", '
                '"evidence_urls": ["https://example.gov.cn/fzgh-2"], '
                '"related_keywords": ["文旅", "乡村", "民宿"], '
                '"supporting_documents": ["十四五产业发展规划"]}, '
                '{"industry": "竹产业", "confidence": 0.65, '
                '"reason": "统计公报显示竹产业产值突出", '
                '"evidence_urls": ["https://example.gov.cn/安吉县/tjgb-1"], '
                '"related_keywords": ["竹制品", "精深加工", "龙头企业"], '
                '"supporting_documents": ["安吉县竹产业产值突破百亿"]}'
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


class ScriptedLLM(LLMClient):
    """按顺序返回预设 JSON 的 LLM，用于测试 Agent 行动循环。"""

    name = "scripted-llm"

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.call_count = 0
        self.calls: list[list[dict[str, str]]] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1
        self.calls.append(list(messages))
        index = min(self.call_count - 1, len(self.responses) - 1)
        return LLMResponse(
            content=self.responses[index],
            model="scripted-v1",
            prompt_tokens=100,
            completion_tokens=100,
            total_tokens=200,
        )


@pytest.fixture
def mock_llm() -> MockLLM:
    return MockLLM()


@pytest.fixture
def scripted_llm() -> type[ScriptedLLM]:
    return ScriptedLLM


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
            content=(
                "2023年，安吉县竹产业实现产值120亿元，同比增长15%，规上企业82家。"
                "竹产业形成了上游竹材种植、中游精深加工、下游竹制品销售的完整链条。"
                "安吉竹业股份有限公司位于安吉县，是当地龙头企业。"
            ),
            source="mock-gov",
        ),
        RawDoc(
            title="安吉县十四五竹产业发展规划",
            url="https://example.gov.cn/安吉县/fzgh-2",
            snippet="重点打造百亿级竹产业集群",
            content=(
                "《安吉县十四五竹产业发展规划》提出到2027年实现产值200亿元，"
                "培育龙头企业10家，建成省级竹产业园区1个，"
                "对精深加工项目给予设备投入30%的补贴。"
            ),
            source="mock-gov",
        ),
        RawDoc(
            title="安吉竹业股份带动产业升级",
            url="https://example.com/news/top-enterprise",
            snippet="龙头企业投产智能化生产线",
            content=(
                "安吉竹业股份有限公司2024年投产智能化竹材精深加工线，"
                "新增产值约20亿元，与浙江农林大学共建竹材研发中心。"
            ),
            source="mock-news",
        ),
    ]


@pytest.fixture
def sample_processed_data(sample_county, sample_docs) -> ProcessedData:
    return ProcessedData(
        county=sample_county,
        focus="竹产业",
        docs=sample_docs,
        total_chars=sum(len(d.content) for d in sample_docs),
    )


class StaticSearchProvider(SearchProvider):
    """返回固定资料集的搜索 provider。"""

    name = "static"

    def __init__(self, docs: list[RawDoc]) -> None:
        self.docs = docs

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        return self.docs[:max_results]


@pytest.fixture
def static_search(tmp_settings, sample_docs):
    from county_research_ai.services.search_service import build_search_service

    return build_search_service(
        tmp_settings, mock_provider=StaticSearchProvider(sample_docs)
    )


# ===== V2 容器 / API =====


@pytest.fixture
def v2_container(tmp_settings, sample_docs):
    from county_research_ai.bootstrap.v2_container import (
        AppContainer,
        create_services,
    )
    from county_research_ai.mocks.llm import MockLLMClient
    from county_research_ai.orchestration.runner import ResearchRunService
    from county_research_ai.orchestration.services import OrchestrationServices
    from county_research_ai.services.search_service import build_search_service
    from county_research_ai.shining_stars.digital_twin import DigitalTwinService
    from county_research_ai.storage.local_fs import LocalFSStorage

    search = build_search_service(
        tmp_settings, mock_provider=StaticSearchProvider(sample_docs)
    )
    services: OrchestrationServices = create_services(
        tmp_settings, llm=MockLLMClient(), search=search
    )
    runs = ResearchRunService(services)
    container = AppContainer(
        settings=tmp_settings,
        llm=services.llm,
        search=search,
        storage=LocalFSStorage(settings=tmp_settings),
        graph_store=services.graph_store,
        services=services,
        runs=runs,
        simulation=DigitalTwinService(settings=tmp_settings),
    )
    yield container
    container.close()


@pytest.fixture
def api_client(v2_container):
    from fastapi.testclient import TestClient

    from county_research_ai.api.main import create_app

    app = create_app(v2_container)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def tool_context(tmp_settings: Settings, mock_llm, sample_docs):
    from county_research_ai.agent.tools import ResearchToolContext
    from county_research_ai.llm.analyzer import LLMAnalyzer
    from county_research_ai.llm.long_history_analyzer import LongHistoryAnalyzer
    from county_research_ai.llm.rise_fall_analyzer import RiseFallAnalyzer
    from county_research_ai.processor import DocumentProcessor
    from county_research_ai.reporting import ReportRenderer
    from county_research_ai.reporting.long_history_renderer import LongHistoryReportRenderer
    from county_research_ai.reporting.rise_fall_renderer import RiseFallReportRenderer
    from county_research_ai.search.base import SearchProvider
    from county_research_ai.storage.local_fs import LocalFSStorage

    class StaticSearch(SearchProvider):
        name = "static"

        def search(self, query: str, max_results: int = 10):
            return sample_docs[:max_results]

    return ResearchToolContext(
        search=StaticSearch(),
        storage=LocalFSStorage(settings=tmp_settings),
        processor=DocumentProcessor(quality_config=tmp_settings.quality),
        analyzer=LLMAnalyzer(llm=mock_llm, settings=tmp_settings),
        rise_fall_analyzer=RiseFallAnalyzer(llm=mock_llm, settings=tmp_settings),
        long_history_analyzer=LongHistoryAnalyzer(llm=mock_llm, settings=tmp_settings),
        renderer=ReportRenderer(),
        rise_fall_renderer=RiseFallReportRenderer(),
        long_history_renderer=LongHistoryReportRenderer(),
        settings=tmp_settings,
    )
