"""Mock 实现模块。

存放用于测试和本地开发的 Mock 组件:
    - MockSearchProvider: 返回构造的示例 RawDoc,无需真实搜索 API
    - MockLLMClient:      根据 task 返回构造的分析文本,无需真实 LLM API
    - MockStorage:         内存版 Storage,无需磁盘

Pipeline 中的 Mock 类会从本模块重导出,保持向后兼容。
"""
from __future__ import annotations

from .llm import MockLLMClient
from .search import MockSearchProvider
from .storage import MockStorage

__all__ = ["MockSearchProvider", "MockLLMClient", "MockStorage"]
