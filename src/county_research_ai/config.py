"""配置加载模块。

合并 settings.yaml(默认行为)与 .env(敏感信息 / 覆盖项),产出全局 Settings 单例。

优先级:环境变量 > settings.yaml > 代码默认值

使用方式:
    from county_research_ai.config import get_settings
    settings = get_settings()
    settings.llm.model  # -> "deepseek-chat"
    settings.llm.api_key.get_secret_value()  # -> 实际密钥

测试时重置单例:
    from county_research_ai.config import reset_settings
    reset_settings()
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr

# ===== 路径常量 =====
# config.py 位于 src/county_research_ai/config.py
PACKAGE_DIR = Path(__file__).resolve().parent          # src/county_research_ai/
SRC_DIR = PACKAGE_DIR.parent                            # src/
PROJECT_ROOT = SRC_DIR.parent                           # 项目根目录
CONFIG_DIR = PROJECT_ROOT / "config"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"


# ===== 嵌套配置模型 =====


class LLMRetryConfig(BaseModel):
    """LLM 请求重试配置。"""

    max_attempts: int = 3
    backoff_seconds: int = 2  # 指数退避起始值


class LLMConfig(BaseModel):
    """LLM 大模型配置。

    provider / model / base_url / api_key 从 .env 读取,
    其余参数可在 settings.yaml 中调整。
    """

    provider: str = "deepseek"
    api_key: SecretStr = SecretStr("")
    base_url: str = ""
    model: str = "deepseek-chat"
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: int = 60  # 单次请求超时(秒)
    retry: LLMRetryConfig = Field(default_factory=LLMRetryConfig)
    # 分析任务拆分:每个子任务独立调用 LLM
    tasks: list[str] = Field(
        default_factory=lambda: [
            "industry_status",
            "advantages",
            "shortcomings",
            "recommendations",
        ]
    )


class SearchRetryConfig(BaseModel):
    """搜索请求重试配置。"""

    max_attempts: int = 3
    backoff_seconds: int = 2


class SearchConfig(BaseModel):
    """数据采集配置。"""

    provider: str = "tavily"
    api_key: SecretStr = SecretStr("")
    max_results: int = 10
    timeout: int = 30
    concurrency: int = 3  # 并发采集数
    retry: SearchRetryConfig = Field(default_factory=SearchRetryConfig)
    fetch_detail: bool = True  # 是否抓取搜索结果详情页
    detail_max_chars: int = 8000  # 单页正文截断长度


class StorageConfig(BaseModel):
    """存储配置。

    data_dir / reports_dir 留空则使用项目默认路径;
    填入绝对路径可覆盖到外部位置(如挂载盘)。
    """

    data_dir: str = ""
    reports_dir: str = ""
    raw_subdir: str = "raw"
    processed_subdir: str = "processed"
    # 原始数据归档格式:按 {县名}/{日期}/ 组织
    archive_layout: str = "{county}/{date}"


class CacheConfig(BaseModel):
    """缓存配置(避免短期内重复调用 API)。"""

    enabled: bool = True
    ttl_hours: int = 24
    # 缓存键字段:hash(县名 + 方向 + 数据源)
    key_fields: list[str] = Field(
        default_factory=lambda: ["county", "focus", "provider"]
    )


class QualityConfig(BaseModel):
    """质量控制配置(数据处理与分析的质量门槛)。"""

    minimum_sources: int = 5  # 最低来源数量(低于此数警告,但不阻断)
    government_source_weight: float = 2.0  # 政府来源排序权重
    max_evidence_length: int = 8000  # 单文档最大证据长度(字符)
    min_credibility_score: float = 0.3  # 最低可信度(低于此值过滤)
    min_content_length: int = 50  # 最低正文长度(字符,低于此值视为无效文档)


class PipelineStages(BaseModel):
    """Pipeline 阶段开关(调试时可单独关闭某阶段)。"""

    search: bool = True
    process: bool = True
    analyze: bool = True
    report: bool = True


class PipelineConfig(BaseModel):
    """流程编排配置。"""

    mode: str = "sequential"  # MVP 阶段单线程顺序执行
    fail_fast: bool = True  # 任一阶段失败是否终止全流程
    stages: PipelineStages = Field(default_factory=PipelineStages)


class LoggingConfig(BaseModel):
    """日志配置。"""

    level: str = "INFO"  # DEBUG / INFO / WARNING / ERROR
    format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    file: str = ""  # 留空则仅输出到控制台
    rotate: bool = False


class AppConfig(BaseModel):
    """应用元信息。"""

    name: str = "AI县域产业研究助手"
    version: str = "0.1.0"
    # 报告文件命名模板(Jinja2)
    report_filename_template: str = "{{ county }}_{{ focus }}_{{ date }}.md"


class Settings(BaseModel):
    """全局配置根模型。

    业务相关配置从 yaml/env 加载;
    路径常量在运行时计算,确保始终指向正确的项目位置。
    """

    app: AppConfig = Field(default_factory=AppConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # 路径常量(运行时计算,不从配置文件读取)
    project_root: Path = PROJECT_ROOT
    config_dir: Path = CONFIG_DIR
    prompts_dir: Path = PROMPTS_DIR
    data_dir: Path = DATA_DIR
    reports_dir: Path = REPORTS_DIR


# ===== 加载逻辑 =====


def _load_yaml(path: Path) -> dict[str, Any]:
    """加载 YAML 配置文件,不存在则返回空字典。"""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _merge_env(settings_dict: dict[str, Any]) -> dict[str, Any]:
    """将环境变量合并进 settings 字典,env 优先级更高。

    LLM 与搜索 API 的密钥只从 .env 读取,绝不放进 yaml。
    """
    # ---------- LLM ----------
    llm = settings_dict.setdefault("llm", {})
    if os.getenv("LLM_PROVIDER"):
        llm["provider"] = os.getenv("LLM_PROVIDER")
    if os.getenv("LLM_API_KEY"):
        llm["api_key"] = os.getenv("LLM_API_KEY")
    if os.getenv("LLM_BASE_URL"):
        llm["base_url"] = os.getenv("LLM_BASE_URL")
    if os.getenv("LLM_MODEL"):
        llm["model"] = os.getenv("LLM_MODEL")
    if os.getenv("LLM_TEMPERATURE"):
        llm["temperature"] = float(os.getenv("LLM_TEMPERATURE"))  # type: ignore[arg-type]
    if os.getenv("LLM_MAX_TOKENS"):
        llm["max_tokens"] = int(os.getenv("LLM_MAX_TOKENS"))  # type: ignore[arg-type]
    if os.getenv("LLM_TIMEOUT"):
        llm["timeout"] = int(os.getenv("LLM_TIMEOUT"))  # type: ignore[arg-type]

    # ---------- 搜索 ----------
    search = settings_dict.setdefault("search", {})
    if os.getenv("SEARCH_PROVIDER"):
        search["provider"] = os.getenv("SEARCH_PROVIDER")
    # 根据当前 provider 选择对应的 API Key 环境变量
    provider = search.get("provider", "tavily")
    key_env_map = {
        "tavily": "TAVILY_API_KEY",
        "serper": "SERPER_API_KEY",
        "bing": "BING_API_KEY",
    }
    env_key = key_env_map.get(provider, "")
    if env_key and os.getenv(env_key):
        search["api_key"] = os.getenv(env_key)
    if os.getenv("SEARCH_MAX_RESULTS"):
        search["max_results"] = int(os.getenv("SEARCH_MAX_RESULTS"))  # type: ignore[arg-type]
    if os.getenv("SEARCH_TIMEOUT"):
        search["timeout"] = int(os.getenv("SEARCH_TIMEOUT"))  # type: ignore[arg-type]
    if os.getenv("SEARCH_CONCURRENCY"):
        search["concurrency"] = int(os.getenv("SEARCH_CONCURRENCY"))  # type: ignore[arg-type]

    # ---------- 存储 ----------
    storage = settings_dict.setdefault("storage", {})
    if os.getenv("DATA_DIR"):
        storage["data_dir"] = os.getenv("DATA_DIR")
    if os.getenv("REPORTS_DIR"):
        storage["reports_dir"] = os.getenv("REPORTS_DIR")

    # ---------- 缓存 ----------
    cache = settings_dict.setdefault("cache", {})
    if os.getenv("CACHE_TTL_HOURS"):
        cache["ttl_hours"] = int(os.getenv("CACHE_TTL_HOURS"))  # type: ignore[arg-type]

    # ---------- 日志 ----------
    log = settings_dict.setdefault("logging", {})
    if os.getenv("LOG_LEVEL"):
        log["level"] = os.getenv("LOG_LEVEL")

    return settings_dict


def _resolve_paths(settings: Settings) -> Settings:
    """根据 storage.data_dir / reports_dir 覆盖默认路径。"""
    if settings.storage.data_dir:
        settings.data_dir = Path(settings.storage.data_dir).resolve()
    if settings.storage.reports_dir:
        settings.reports_dir = Path(settings.storage.reports_dir).resolve()
    return settings


def load_settings(config_path: Path | None = None) -> Settings:
    """加载配置:settings.yaml + .env 合并,env 优先。

    Args:
        config_path: 自定义 settings.yaml 路径(测试用);默认使用 config/settings.yaml

    Returns:
        校验后的 Settings 实例
    """
    # 1. 加载 .env(项目根目录)
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # 2. 加载 settings.yaml
    yaml_path = config_path or (CONFIG_DIR / "settings.yaml")
    settings_dict = _load_yaml(yaml_path)

    # 3. 合并环境变量(优先级更高)
    settings_dict = _merge_env(settings_dict)

    # 4. 构造 Settings(Pydantic 校验)
    settings = Settings(**settings_dict)

    # 5. 解析路径覆盖
    settings = _resolve_paths(settings)

    return settings


# ===== 全局单例 =====

_settings: Settings | None = None


def get_settings() -> Settings:
    """获取全局 Settings 单例(首次调用时加载,后续复用)。

    使用单例避免每次访问配置都重新读盘与解析。
    """
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    """重置单例(测试场景:修改 env/yaml 后需要重新加载时使用)。"""
    global _settings
    _settings = None
