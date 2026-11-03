"""自定义异常层次。

所有业务异常继承自 CountyResearchAIError,便于上层统一捕获与日志记录。
每层定义自己的异常子类,精确定位错误来源。

使用示例:
    try:
        settings = get_settings()
    except ConfigError as e:
        logger.error("配置加载失败: %s", e)
        # e.context 可携带结构化细节用于排错

异常层次:
    CountyResearchAIError            # 基类
    ├── ConfigError                  # 配置加载/校验
    ├── SearchError                  # 数据采集
    ├── StorageError                 # 存储/缓存
    ├── LLMError                     # LLM 调用
    ├── ReportError                  # 报告生成
    └── PipelineError                # Pipeline 编排
"""
from __future__ import annotations

from typing import Any


class CountyResearchAIError(Exception):
    """所有自定义异常的基类。

    Args:
        message: 人类可读的错误描述
        context: 结构化上下文(用于日志/排错,不拼进 message)
    """

    def __init__(
        self,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context or {}

    def __str__(self) -> str:
        if self.context:
            return f"{self.message} | context={self.context}"
        return self.message


class ConfigError(CountyResearchAIError):
    """配置加载或校验错误(如 yaml 缺失、env 必填项为空等)。"""


class SearchError(CountyResearchAIError):
    """数据采集错误(如搜索 API 调用失败、政府页面抓取超时等)。"""


class StorageError(CountyResearchAIError):
    """存储层错误(如目录创建失败、文件读写异常、缓存失效等)。"""


class LLMError(CountyResearchAIError):
    """LLM 调用错误(如鉴权失败、超时、响应解析失败等)。"""


class ReportError(CountyResearchAIError):
    """报告生成错误(如模板渲染失败、章节缺失等)。"""


class PipelineError(CountyResearchAIError):
    """Pipeline 编排错误(如阶段依赖缺失、fail_fast 触发等)。"""
