"""LLM 分析层。

负责调用大模型对结构化数据进行产业分析:
    - base.py          抽象接口 LLMClient
    - client.py        具体实现(OpenAI 兼容,可接 DeepSeek/Qwen)
    - prompt_loader.py 从 prompts/ 加载 Jinja2 模板并填充变量
    - analyzer.py      业务分析逻辑,产出结构化分析结果

提示词模板存放在项目根目录的 prompts/ 下。
"""
from __future__ import annotations
