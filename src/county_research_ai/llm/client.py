"""OpenAI 兼容 LLM 客户端实现。

通过 OpenAI SDK 调用兼容 OpenAI API 的服务:
    - OpenAI   https://api.openai.com/v1
    - DeepSeek https://api.deepseek.com/v1
    - Qwen     https://dashscope.aliyuncs.com/compatible-mode/v1

切换供应商只需改 .env 的 LLM_PROVIDER / LLM_BASE_URL / LLM_MODEL,代码不动。

设计要点:
    - openai 包延迟导入:模块加载不依赖 openai,仅实例化时需要
    - 重试机制:用 tenacity 包装,按 settings.llm.retry 配置
    - 错误统一抛 LLMError,携带 context(模型/消息数/错误类型)
    - 响应解析:提取 content + usage(token 用量)
"""
from __future__ import annotations

import logging
from typing import Any

from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import Settings, get_settings
from ..exceptions import LLMError
from .base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class OpenAICompatibleClient(LLMClient):
    """OpenAI 兼容 API 客户端。

    Usage:
        client = OpenAICompatibleClient()  # 从 settings 读取配置
        resp = client.chat([{"role": "user", "content": "你好"}])
        print(resp.content, resp.total_tokens)

    测试注入:
        client = OpenAICompatibleClient(settings=custom_settings)
    """

    name = "openai_compatible"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        llm = self._settings.llm

        # 校验必要配置
        api_key = llm.api_key.get_secret_value() if llm.api_key else ""
        if not api_key:
            raise LLMError(
                "LLM API Key 未配置",
                context={
                    "hint": "请在 .env 中设置 LLM_API_KEY",
                    "provider": llm.provider,
                },
            )

        # 延迟导入 openai SDK
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMError(
                "openai 包未安装,无法使用真实 LLM",
                context={"hint": "pip install openai", "error": str(e)},
            ) from e

        # 构造客户端
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": float(llm.timeout),
        }
        if llm.base_url:
            client_kwargs["base_url"] = llm.base_url

        try:
            self._client = OpenAI(**client_kwargs)
        except Exception as e:
            raise LLMError(
                "OpenAI 客户端初始化失败",
                context={
                    "provider": llm.provider,
                    "base_url": llm.base_url,
                    "error": str(e),
                },
            ) from e

        self._model = llm.model
        self._default_temperature = llm.temperature
        self._default_max_tokens = llm.max_tokens
        self._retry_config = llm.retry

        logger.info(
            "LLM 客户端就绪 | provider=%s | model=%s | base_url=%s",
            llm.provider, self._model, llm.base_url or "(官方端点)",
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用 chat completions 接口(带重试)。"""
        temp = temperature if temperature is not None else self._default_temperature
        tokens = max_tokens if max_tokens is not None else self._default_max_tokens

        # 构造重试装饰器(每次调用新建,避免共享状态)
        retry_decorator = retry(
            stop=stop_after_attempt(self._retry_config.max_attempts),
            wait=wait_exponential(
                multiplier=self._retry_config.backoff_seconds,
                min=self._retry_config.backoff_seconds,
                max=self._retry_config.backoff_seconds * 10,
            ),
            retry=retry_if_exception_type(LLMError),
            reraise=True,
        )

        try:
            resp = retry_decorator(self._do_chat)(
                messages=messages,
                temperature=temp,
                max_tokens=tokens,
                **kwargs,
            )
            return resp
        except RetryError as e:
            raise LLMError(
                "LLM 调用重试耗尽",
                context={
                    "model": self._model,
                    "attempts": self._retry_config.max_attempts,
                    "last_error": str(e),
                },
            ) from e

    # ---- 内部方法 ----

    def _do_chat(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> LLMResponse:
        """实际调用 OpenAI SDK(单次,不带重试)。

        所有 SDK 异常统一转换为 LLMError,这样上层的
        retry_if_exception_type(LLMError) 才能正确触发重试。
        """
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        except Exception as e:
            # 把 SDK 异常包装为 LLMError,便于重试器识别
            raise LLMError(
                f"LLM API 调用失败: {type(e).__name__}: {e}",
                context={
                    "model": self._model,
                    "messages_count": len(messages),
                    "error_type": type(e).__name__,
                },
            ) from e

        # 解析响应
        try:
            choice = resp.choices[0]
            content = choice.message.content or ""
            usage = resp.usage
            return LLMResponse(
                content=content,
                model=getattr(resp, "model", self._model),
                prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
                total_tokens=getattr(usage, "total_tokens", 0) if usage else 0,
            )
        except (IndexError, AttributeError) as e:
            raise LLMError(
                "LLM 响应解析失败",
                context={
                    "model": self._model,
                    "error": str(e),
                    "resp_type": type(resp).__name__,
                },
            ) from e
