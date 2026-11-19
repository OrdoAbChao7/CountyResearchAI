"""CountyResearchAI V2 · Agentic Industrial Intelligence Platform。

面向中国县域产业研究的多 Agent 平台：FastAPI 业务入口 + LangGraph 编排 +
证据约束的知识图谱。旧版固定 Workflow/CLI 已移除，设计见 ARCHITECTURE_V2.md。

包结构:
    api/              FastAPI 入口、路由与传输 Schema
    bootstrap/        组合根（配置 → 服务 → 图存储 → 运行服务）
    orchestration/    LangGraph 图、状态、Supervisor、路由、检查点
    agents/           专业 Agent、Critic、Report、工具注册表
    services/         搜索/证据/文档/发现/图谱/定量/机会/报告服务
    knowledge_graph/  本体、抽取、消歧、存储适配器、GraphRAG、时序
    shining_stars/    Star A/B/C 领域契约与确定性实现
    domain/           共享领域模型与事件
    search/ llm/ reporting/ storage/   既有能力层
    config.py         配置加载（yaml + env）
"""
from __future__ import annotations

__version__ = "0.2.0"
__all__ = ["__version__"]
