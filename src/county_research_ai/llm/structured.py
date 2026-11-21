"""结构化 LLM 输出解析工具。

Agent 与知识图谱抽取都要求模型输出 JSON。这里统一做容错解析：
纯 JSON、```json 代码块、文本中嵌入的 JSON 对象/数组都能解析。
"""
from __future__ import annotations

import json
import re
from typing import Any

from .base import LLMClient

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class StructuredOutputError(ValueError):
    """模型输出无法解析为预期 JSON 结构。"""


def extract_json(text: str) -> Any:
    """从模型输出中提取第一个 JSON 对象或数组。"""
    if not text or not text.strip():
        raise StructuredOutputError("empty model output")
    candidates: list[str] = []
    fenced = _JSON_FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(text.strip())

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 扫描第一个平衡的 {...} 或 [...]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            char = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start: idx + 1])
                    except json.JSONDecodeError:
                        break
    raise StructuredOutputError("no valid JSON found in model output")


def parse_json_object(text: str) -> dict[str, Any]:
    data = extract_json(text)
    if not isinstance(data, dict):
        raise StructuredOutputError(f"expected JSON object, got {type(data).__name__}")
    return data


def parse_json_list(text: str) -> list[Any]:
    data = extract_json(text)
    if isinstance(data, dict):
        for key in ("items", "results", "entities", "relations", "tasks"):
            if isinstance(data.get(key), list):
                return data[key]
        raise StructuredOutputError("expected JSON array, got object without list field")
    if not isinstance(data, list):
        raise StructuredOutputError(f"expected JSON array, got {type(data).__name__}")
    return data


def json_completion(
    llm: LLMClient,
    *,
    system: str,
    user: str,
    temperature: float = 0.0,
    max_tokens: int = 2500,
) -> Any:
    """调用 LLM 并解析 JSON 输出。"""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    response = llm.chat(messages, temperature=temperature, max_tokens=max_tokens)
    return extract_json(response.content)


__all__ = [
    "StructuredOutputError",
    "extract_json",
    "json_completion",
    "parse_json_list",
    "parse_json_object",
]
