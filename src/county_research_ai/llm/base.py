"""LLM 分析层抽象接口。

定义 LLMClient 抽象基类与 LLMResponse 响应结构。
所有 LLM 实现(OpenAI / DeepSeek / Qwen 兼容端点)实现此接口,
analyzer.py 通过统一接口调用,实现模型可替换:
切换供应商只需替换 LLMClient 实现 + 改 .env,不动 analyzer。

实现方参考:
    - client.py  OpenAI 兼容 SDK 实现(可接 DeepSeek/Qwen/OpenAI)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class LLMResponse(BaseModel):
    """LLM 调用响应。

    analyzer.py 会将 LLMResponse 转换为业务模型 AnalysisResult:
        LLMResponse(content=..., model=..., total_tokens=N)
            → AnalysisResult(task=..., content=..., model=..., tokens_used=N)
    """

    content: str  # 生成的文本
    model: str = ""  # 实际使用的模型名(便于成本追踪)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMClient(ABC):
    """LLM 客户端抽象基类。

    实现方需提供:
        - name: 客户端标识
        - chat(): 核心对话接口(OpenAI messages 风格)

    约定:
        - 鉴权/超时/限流/响应解析错误抛出 LLMError(见 exceptions.py)
        - 实现方自行处理重试(参考 settings.llm.retry)
        - 默认参数(temperature/max_tokens/timeout)从 settings 读取,
          调用方可通过参数覆盖
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """客户端标识,如 'deepseek' / 'qwen' / 'openai'。"""
        ...

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """对话接口(OpenAI messages 风格)。

        Args:
            messages: 消息列表,如 [{"role": "user", "content": "..."}]
            temperature: 覆盖默认温度(None 则用 settings.llm.temperature)
            max_tokens: 覆盖默认最大 token(None 则用 settings.llm.max_tokens)
            **kwargs: 透传给底层 API 的额外参数

        Returns:
            LLMResponse

        Raises:
            LLMError: 调用失败
        """
        ...

    def complete(self, prompt: str, system: str = "", **kwargs: Any) -> str:
        """便捷方法:单轮补全,直接返回文本内容。

        适用于 analyzer.py 中"填好模板 → 取回分析文本"的简单场景。
        需要多轮对话或获取 token 用量时请直接调用 chat()。

        Args:
            prompt: 用户 prompt(已由 prompt_loader 渲染)
            system: 可选 system prompt
            **kwargs: 透传给 chat()

        Returns:
            生成的文本内容
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, **kwargs).content
