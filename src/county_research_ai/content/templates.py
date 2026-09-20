"""短视频内容生产:模板常量与共享工具。

提供:
    - SCRIPT_SEGMENTS: 60 秒短视频固定 5 段时间轴
    - _TaskConfig / _parse_json_lenient / _safe_str_list:
      复用 rise_fall_analyzer 的任务配置 + 容错 JSON 解析模式,
      供 director / script_generator / fact_checker 共用,避免重复定义。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


# 60 秒短视频固定 5 段时间轴(段位 ID / 时间区间 / 用途)
SCRIPT_SEGMENTS: list[dict[str, str]] = [
    {"segment_id": "hook", "time_range": "0-5s", "purpose": "冲突钩子"},
    {"segment_id": "origin", "time_range": "5-20s", "purpose": "过去如何兴起"},
    {"segment_id": "growth", "time_range": "20-40s", "purpose": "产业如何发展壮大"},
    {"segment_id": "decline", "time_range": "40-55s", "purpose": "出现什么问题/拐点"},
    {"segment_id": "takeaway", "time_range": "55-60s", "purpose": "历史规律总结(不写招商)"},
]


@dataclass(frozen=True)
class _TaskConfig:
    """单任务配置(参考 rise_fall_analyzer._TaskConfig)。

    Attributes:
        template_name: prompts/ 下模板名(不含扩展名);None 表示无模板
        fallback_prompt: 模板缺失时的内联 fallback(Jinja2 字符串)
        description: 任务描述(用于日志)
    """

    template_name: str | None
    fallback_prompt: str
    description: str = ""


def _parse_json_lenient(content: str) -> dict | None:
    """容错解析 LLM 返回的 JSON。

    支持三种形态:
        1. 纯 JSON
        2. ```json ... ``` 代码块包裹
        3. 文本中嵌入的 { ... }(取第一个完整对象)
    """
    if not content:
        return None
    text = content.strip()
    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. 剥离 ```json ... ``` 代码块
    fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass
    # 3. 文本中提取首个 {...} 对象
    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        try:
            return json.loads(obj_match.group())
        except json.JSONDecodeError:
            pass
    return None


def _safe_str_list(value) -> list[str]:
    """将任意值安全转换为 list[str](容忍 None / 单值 / 列表)。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]
