"""AI县域产业研究助手 - 自动化采集、分析与生成县域产业研究报告。

包结构:
    search/      数据采集层(网络搜索 + 政府公开数据)
    llm/         LLM 分析层(调用大模型产出结构化洞察)
    reporting/   报告生成层(渲染 Markdown 报告)
    storage/     存储层(本地文件系统 + 缓存)
    pipeline.py  流程编排(串联上述四层)
    cli.py       命令行入口
    config.py    配置加载(yaml + env)
    models.py    共享数据模型
    exceptions.py 自定义异常
"""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
