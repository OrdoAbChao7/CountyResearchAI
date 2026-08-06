"""共享数据模型。

定义贯穿各层的核心数据结构,基于 Pydantic v2。
数据流向(不可变值对象,在层间传递):

    ResearchRequest                 # CLI/Pipeline 输入
        ↓
    CountyInfo + RawDoc[]           # search 层产出
        ↓
    ProcessedData                   # storage 层清洗后
        ↓
    AnalysisResult[]                # llm 层产出
        ↓
    ReportSection[] → ResearchReport  # reporting 层产出

时间戳统一使用 UTC 时区感知(datetime.now(timezone.utc))。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """UTC 当前时间(时区感知)。"""
    return datetime.now(timezone.utc)


# ===== 基础实体 =====


class CountyInfo(BaseModel):
    """县域信息。

    MVP 阶段只需县名即可启动;province/prefure 为可选增强,
    后续 search 层可根据县名自动补全。
    """

    name: str = ""  # 县名,如 "安吉县"
    province: str = ""  # 省份,如 "浙江省"
    prefecture: str = ""  # 地级市,如 "湖州市"
    full_name: str = ""  # 完整名称,如 "浙江省湖州市安吉县"

    def display(self) -> str:
        """用于报告标题的显示名。"""
        return self.full_name or self.name

    @classmethod
    def from_name(cls, name: str) -> "CountyInfo":
        """仅凭县名构造(province 等留空,后续可补全)。"""
        return cls(name=name)


class RawDoc(BaseModel):
    """采集层原始文档。

    一条搜索结果对应一个 RawDoc;
    content 字段在 fetch_detail=True 时抓取详情页正文填充。

    Attributes:
        title: 文档标题
        url: 文档链接
        snippet: 搜索引擎返回的摘要
        content: 详情页正文(截断到 detail_max_chars)
        source: 数据源标识:tavily/serper/bing/gov
        fetched_at: 采集时间(UTC)
        metadata: 额外元信息(相关度评分、语言等,因 provider 而异)
        published_at: 发布时间(若可解析,否则 None)
        domain_type: 来源类型: government / news / company / research / social / unknown
        credibility_score: 来源可信度评分 0-1(政府/研报高,社交低)
        evidence_type: 证据类型: fact(事实) / opinion(观点) / prediction(预测) / unknown
        source_summary: 来源摘要(一句话概括,供 LLM 快速判断)
    """

    title: str
    url: str
    snippet: str = ""  # 搜索引擎返回的摘要
    content: str = ""  # 详情页正文(截断到 detail_max_chars)
    source: str = ""  # 数据源标识:tavily/serper/bing/gov
    fetched_at: datetime = Field(default_factory=_utcnow)
    # 额外元信息(相关度评分、语言、发布时间等,因 provider 而异)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # ---- 质量评估字段(向后兼容,全部有默认值) ----
    published_at: datetime | None = None
    domain_type: str = "unknown"
    credibility_score: float = 0.5
    evidence_type: str = "unknown"
    source_summary: str = ""


# ===== 流程中间产物 =====


class ProcessedData(BaseModel):
    """清洗后的结构化数据,供 LLM 消费。

    由 storage 层从 RawDoc 列表清洗而来:
        - 去重(按 URL)
        - 过滤(最低字数/黑名单关键词/时效)
        - 截断(控制总长度避免超 token)
    """

    county: CountyInfo
    focus: str  # 研究方向,如 "竹产业"
    docs: list[RawDoc] = Field(default_factory=list)
    total_chars: int = 0  # 全部文档总字符数(用于估算 token 与截断)
    processed_at: datetime = Field(default_factory=_utcnow)

    def render_for_llm(self, max_chars: int = 0) -> str:
        """将文档列表渲染为 LLM 可读的文本块。

        Args:
            max_chars: 最大字符数,0 表示不截断
        """
        blocks: list[str] = []
        used = 0
        for i, doc in enumerate(self.docs, start=1):
            chunk = f"[{i}] {doc.title}\n来源: {doc.url}\n{doc.content or doc.snippet}"
            if max_chars and used + len(chunk) > max_chars:
                blocks.append(f"[{i}] (已截断) {doc.title}\n来源: {doc.url}")
                break
            blocks.append(chunk)
            used += len(chunk)
        return "\n\n---\n\n".join(blocks)


class AnalysisResult(BaseModel):
    """LLM 单个分析任务的输出。

    对应 settings.llm.tasks 中的每一项:
        industry_status / advantages / shortcomings / recommendations
    """

    task: str  # 任务名
    content: str  # Markdown 分析内容
    model: str = ""  # 使用的模型名(便于成本追踪)
    tokens_used: int = 0  # token 消耗(便于成本追踪)


class DiscoveryCandidate(BaseModel):
    """产业方向候选(自动发现阶段的单个候选)。

    Attributes:
        industry: 产业方向名称,如 "竹产业"
        confidence: 置信度 0-1
        reason: 判断依据(基于搜索结果的哪篇文章/什么数据)
        evidence_urls: 支撑证据的 URL 列表(完整决策轨迹)
        related_keywords: 相关关键词(用于后续搜索扩展)
        supporting_documents: 支撑文档标题列表(可追溯数据来源)
    """

    industry: str
    confidence: float = 0.5
    reason: str = ""

    # ---- 证据链字段(完整决策轨迹) ----
    evidence_urls: list[str] = Field(default_factory=list)
    related_keywords: list[str] = Field(default_factory=list)
    supporting_documents: list[str] = Field(default_factory=list)


class DiscoveryResult(BaseModel):
    """产业方向自动发现的结果。

    当用户未指定 --focus 时,系统通过搜索+LLM 分析自动识别重点产业方向。
    """

    candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    selected_focus: str = ""  # 自动选定的产业方向(取置信度最高的)
    model: str = ""
    tokens_used: int = 0
    discovered_at: datetime = Field(default_factory=_utcnow)


# ===== 报告相关 =====


class ReportSection(BaseModel):
    """报告章节。

    reporting/renderer.py 根据 order 排序后拼接为最终 Markdown。
    """

    title: str
    content: str  # Markdown 内容
    order: int = 0  # 排序权重(小在前)
    sources: list[str] = Field(default_factory=list)  # 引用的 URL 列表


class ResearchRequest(BaseModel):
    """研究请求(CLI / Pipeline 输入)。

    focus 为可选:未指定时 Pipeline 会自动搜索识别该县重点产业方向。
    options 预留扩展(如自定义数据源、指定模型、跳过缓存等)。
    """

    county: str  # 县名(简单字符串,pipeline 内部转 CountyInfo)
    focus: str | None = None  # 研究方向,如 "竹产业";None 则自动发现
    options: dict[str, Any] = Field(default_factory=dict)


class ResearchReport(BaseModel):
    """完整研究报告(Pipeline 最终输出)。

    pipeline 将各阶段产物汇总到此对象,reporting 层据此渲染 Markdown。
    """

    county: CountyInfo
    focus: str
    sections: list[ReportSection] = Field(default_factory=list)
    analyses: list[AnalysisResult] = Field(default_factory=list)  # 原始分析结果(便于追溯)
    generated_at: datetime = Field(default_factory=_utcnow)
    version: str = "0.1.0"

    @property
    def section_count(self) -> int:
        """章节数。"""
        return len(self.sections)

    def get_section(self, title: str) -> ReportSection | None:
        """按标题查找章节。"""
        for s in self.sections:
            if s.title == title:
                return s
        return None
