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
    def from_name(cls, name: str) -> CountyInfo:
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
    mode 指定研究模式:snapshot(产业现状快照)/ rise-fall(产业兴衰规律)。
    options 预留扩展(如自定义数据源、指定模型、跳过缓存等)。
    """

    county: str  # 县名(简单字符串,pipeline 内部转 CountyInfo)
    focus: str | None = None  # 研究方向,如 "竹产业";None 则自动发现
    mode: str = "snapshot"  # 研究模式:snapshot / rise-fall
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


# ===== 兴衰规律研究(rise-fall 模式) =====


class TimelineEvent(BaseModel):
    """历史时间线事件。

    用于描绘县域产业发展的关键节点(起家、扩张、拐点、衰退等)。

    Attributes:
        year: 年份或时间段,如 "1998" / "2003-2008" / "2010 年代初"
        event: 事件描述(一句话)
        category: 事件类别: origin(起家) / growth(扩张) / turning(拐点)
                  / decline(衰落) / policy(政策) / external(外部冲击)
        impact: 对县域产业的影响(一句话)
        source_url: 证据来源 URL(关键事件必须绑定)
    """

    year: str = ""
    event: str = ""
    category: str = "unknown"
    impact: str = ""
    source_url: str = ""


class RiseFactor(BaseModel):
    """产业兴起因子。

    Attributes:
        name: 因子名称,如 "矿产资源禀赋" / "改革开放政策红利"
        description: 详细说明该因子如何驱动产业兴起
        evidence: 证据列表(数据/事实/来源 URL 摘要)
    """

    name: str
    description: str = ""
    evidence: list[str] = Field(default_factory=list)


class DeclineFactor(BaseModel):
    """产业衰落因子。

    Attributes:
        name: 因子名称,如 "资源枯竭" / "环保整治" / "产业转移"
        description: 详细说明该因子如何导致产业衰落
        severity: 严重程度 0-1(1 表示致命性衰退)
        evidence: 证据列表
    """

    name: str
    description: str = ""
    severity: float = 0.5
    evidence: list[str] = Field(default_factory=list)


class IndustryLifecycle(BaseModel):
    """县域产业生命周期画像。

    Attributes:
        origin_industry: 起家产业(早期立县之本)
        origin_period: 起家产业主导时期,如 "1980-2010"
        origin_reason: 为何以此起家(机制 + 事实说明)
        growth_industries: 发展壮大期的产业列表
        current_industries: 当前主导产业列表
        stage: 当前所处阶段: origin / growth / mature / decline / transition
        turning_points: 关键转折点时间线
    """

    origin_industry: str = ""
    origin_period: str = ""
    origin_reason: str = ""
    growth_industries: list[str] = Field(default_factory=list)
    current_industries: list[str] = Field(default_factory=list)
    stage: str = "unknown"
    turning_points: list[TimelineEvent] = Field(default_factory=list)


class HistoricalPattern(BaseModel):
    """县域兴衰历史规律归纳。

    Attributes:
        pattern_type: 兴衰模型类型,如:
            - resource_curse       资源诅咒型(资源起家→枯竭→衰退)
            - policy_driven        政策驱动型(红利期繁荣→政策退坡→转型)
            - market_cycle         市场周期型(随宏观周期起伏)
            - industry_transfer    产业转移型(承接→壮大→再转移出)
            - talent_drain         人才流失型(产业基础尚可但人力流失)
            - path_lock            路径锁定型(单一产业过度依赖)
            - diversified_growth   多元共生型(多产业协同,韧性较强)
        summary: 规律总结(2-3 句话概括兴衰主线)
        confidence: 置信度 0-1(基于证据充分度)
        evidence: 支撑该判断的证据列表
    """

    pattern_type: str = "unknown"
    summary: str = ""
    confidence: float = 0.5
    evidence: list[str] = Field(default_factory=list)


class CountyRiseFallAnalysis(BaseModel):
    """县域产业兴衰规律研究总结果(rise-fall 模式产出)。

    聚合生命周期、兴起因子、衰落因子、人才流失、历史规律等核心维度,
    供 RiseFallReportRenderer 渲染为兴衰规律研究报告。

    Attributes:
        county: 县域信息
        lifecycle: 产业生命周期画像
        rise_factors: 产业兴起因子列表
        decline_factors: 产业衰落因子列表
        talent_loss_reasons: 人才流失原因列表(每条一句话 + 证据)
        historical_pattern: 兴衰模型归纳
        summary: 执行摘要(Markdown)
        model: 使用的 LLM 模型名
        tokens_used: 总 token 消耗
        analyzed_at: 分析完成时间(UTC)
    """

    county: CountyInfo
    lifecycle: IndustryLifecycle = Field(default_factory=IndustryLifecycle)
    rise_factors: list[RiseFactor] = Field(default_factory=list)
    decline_factors: list[DeclineFactor] = Field(default_factory=list)
    talent_loss_reasons: list[str] = Field(default_factory=list)
    historical_pattern: HistoricalPattern = Field(default_factory=HistoricalPattern)
    summary: str = ""
    model: str = ""
    tokens_used: int = 0
    analyzed_at: datetime = Field(default_factory=_utcnow)


# ===== 长周期兴衰史研究(long-history 模式) =====


class HistoricalPeriod(BaseModel):
    """历史阶段画像。

    将县域历史划分为若干连续阶段(如"传统时代"/"近代"/"计划经济"等),
    每个阶段有起止时间、生存逻辑、关键事件。

    Attributes:
        name: 阶段名,如 "建县至清末(传统时代)" / "1949-1978 计划经济时期"
        start: 起始年份或时间点
        end: 结束年份或时间点
        summary: 阶段特征总结(3-5 句话)
        dominant_logic: 此阶段县域的主导生存逻辑(一句话)
        key_events: 关键历史事件(年份 + 事件描述)
        evidence: 支撑证据(县志/地方志/论文等)
    """

    name: str = ""
    start: str = ""
    end: str = ""
    summary: str = ""
    dominant_logic: str = ""
    key_events: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class GeoHistoricalFactor(BaseModel):
    """地理历史因子。

    决定县域形成与长周期命运的地理、资源、交通、行政等深层结构因素。

    Attributes:
        name: 因子名,如 "赣粤驿道交通枢纽" / "山区耕地匮乏" / "行政边界功能"
        description: 因子内容描述
        impact: 对县域长期命运的影响(一句话,说明机制)
        evidence: 支撑证据
    """

    name: str = ""
    description: str = ""
    impact: str = ""
    evidence: list[str] = Field(default_factory=list)


class LongHistoryPattern(BaseModel):
    """县域长周期兴衰模型归纳。

    Attributes:
        pattern_type: 长周期模型类型(10 种典型模型之一或 mixed)
        summary: 2-3 句话概括该县数百年来的历史命运主线
        confidence: 置信度 0-1(基于证据充分度)
        dominant_variables: 决定该县长周期命运的 2-4 个关键变量(如"交通线/资源/行政层级/周边大城市虹吸")
        evidence: 支撑判断的关键证据
    """

    pattern_type: str = "unknown"
    summary: str = ""
    confidence: float = 0.5
    dominant_variables: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class CountyLongHistoryAnalysis(BaseModel):
    """县域长周期兴衰史研究总结果(long-history 模式产出)。

    覆盖 9 个核心问题,供 LongHistoryReportRenderer 渲染为 9 节长周期报告。
    注意:所有关键分析均保留 evidence 列表,便于追溯。

    Attributes:
        county: 县域信息
        periods: 历史阶段列表(建议 4-7 个,覆盖建县至今)
        geo_factors: 地理历史因子(3-6 个,解释"为什么在这里形成一个县")
        traditional_economy: 传统时代生存方式(农业/商贸/手工业/移民等,Markdown)
        modern_shocks: 近代冲击与变迁(战争/交通线/市场/行政,Markdown)
        state_period_reorganization: 计划经济时期再组织(国营/矿山/水利/农垦/供销,Markdown)
        reform_period_transformation: 改革开放后产业重塑(民营/招商/特色产业/产业转移,Markdown)
        contemporary_status: 新世纪以来发展变化(人口/交通/地产/产业升级,Markdown)
        long_history_pattern: 长周期兴衰模型归纳
        summary: 执行摘要(Markdown)
        analyzed_at: 分析完成时间(UTC)
    """

    county: CountyInfo
    periods: list[HistoricalPeriod] = Field(default_factory=list)
    geo_factors: list[GeoHistoricalFactor] = Field(default_factory=list)

    traditional_economy: str = ""
    modern_shocks: str = ""
    state_period_reorganization: str = ""
    reform_period_transformation: str = ""
    contemporary_status: str = ""

    long_history_pattern: LongHistoryPattern = Field(default_factory=LongHistoryPattern)
    summary: str = ""
    analyzed_at: datetime = Field(default_factory=_utcnow)


# ===== 内容生产(短视频脚本流水线) =====


class ContentAngle(BaseModel):
    """短视频选题角度。

    由 director 基于研究报告生成,作为脚本撰写的输入。
    每个角度代表一种切入短视频的视角(冲突/反差/数据/人物锚点等)。

    Attributes:
        angle_id: 角度唯一标识(slug 风格,如 'resource-curse-coal-collapse')
        title: 视频标题(15-25 字,带钩子,不含标题党)
        hook: 开场 1 句话钩子(冲突/反差/疑问)
        perspective: 切入视角描述(40-80 字,说明该角度如何切入该县产业兴衰)
        target_audience: 目标受众(如"关注下沉市场的创业者"/"产业研究爱好者")
        key_points: 该角度要传达的 3-5 个核心要点
        tone: 叙事基调(如"冷静叙事"/"反讽"/"科普向")
        source_refs: 引用的研究结论来源(对应研究报告中的章节/数据点)
    """

    angle_id: str = ""
    title: str = ""
    hook: str = ""
    perspective: str = ""
    target_audience: str = ""
    key_points: list[str] = Field(default_factory=list)
    tone: str = ""
    source_refs: list[str] = Field(default_factory=list)


class ScriptSegment(BaseModel):
    """短视频脚本单段。

    60 秒短视频按时间轴切分为 5 段:
        0-5s   冲突钩子
        5-20s  过去如何兴起
        20-40s 产业如何发展
        40-55s 出现什么问题
        55-60s 历史规律总结

    Attributes:
        segment_id: 段落标识(如 'hook'/'origin'/'growth'/'decline'/'takeaway')
        time_range: 时间区间字符串(如 '0-5s')
        narration: 旁白文案(口播用,口语化)
        on_screen: 屏幕文字(关键字幕/数据贴片)
        visual_hint: 画面建议(素材方向,不涉及具体剪辑)
        source_refs: 该段引用的研究证据(对应研究报告中的章节/数据点 URL)
    """

    segment_id: str = ""
    time_range: str = ""
    narration: str = ""
    on_screen: str = ""
    visual_hint: str = ""
    source_refs: list[str] = Field(default_factory=list)


class VideoScript(BaseModel):
    """完整短视频脚本(基于某个 ContentAngle 生成)。

    Attributes:
        angle_id: 对应的选题角度 ID
        title: 视频标题(沿用 ContentAngle.title 或微调)
        duration_seconds: 预计时长(秒,默认 60)
        segments: 5 段脚本(按时间轴)
        total_word_count: 旁白总字数(便于评估口播节奏)
        generated_at: 生成时间(UTC)
    """

    angle_id: str = ""
    title: str = ""
    duration_seconds: int = 60
    segments: list[ScriptSegment] = Field(default_factory=list)
    total_word_count: int = 0
    generated_at: datetime = Field(default_factory=_utcnow)


class FactCheckItem(BaseModel):
    """单条事实核查项。

    Attributes:
        claim: 脚本中需要核查的事实声明(原句或概括)
        segment_id: 该声明所属的脚本段落 ID
        evidence: 核查依据(引用研究报告/外部资料中的数据点)
        verdict: 核查结论(supported / unsupported / needs_revision)
        note: 备注(如"数据未找到"/"年份需修正为 2014")
    """

    claim: str = ""
    segment_id: str = ""
    evidence: str = ""
    verdict: str = "needs_revision"  # supported / unsupported / needs_revision
    note: str = ""


class FactCheckResult(BaseModel):
    """脚本事实核查结果。

    Attributes:
        angle_id: 对应的选题角度 ID
        items: 各事实核查项列表
        overall_status: 整体状态(ok / needs_revision / unsupported)
            - ok: 全部 supported
            - needs_revision: 至少一项 needs_revision 但无 unsupported
            - unsupported: 至少一项 unsupported(必须返修)
        checked_at: 核查完成时间(UTC)
    """

    angle_id: str = ""
    items: list[FactCheckItem] = Field(default_factory=list)
    overall_status: str = "needs_revision"  # ok / needs_revision / unsupported
    checked_at: datetime = Field(default_factory=_utcnow)


class StoryLine(BaseModel):
    """故事线(从研究报告中提炼的"值得讲述的故事")。

    由 StoryMiner 从研究报告中提取,用于指导 ContentDirector 选择传播角度。
    严禁编造人物、企业、年份、数据,所有内容必须来源于研究报告。

    Attributes:
        main_story: 主线故事梗概(100-200 字,冲突清晰、因果链完整)
        characters: 关键人物/群体(如"早期煤老板""返乡创业者""留守老人")
        enterprises: 关键企业/机构(如"某煤矿集团""某农业合作社")
        events: 关键事件(如"2008 年矿难""2015 年产业转型")
        data_points: 关键数据点(如"产量峰值 500 万吨""人口流失 40%")
        time_span: 时间跨度(如"1990-2020")
        conflict_type: 冲突类型(如"资源枯竭 vs 产业转型""区位优势 vs 人口外流")
        evidence_refs: 证据来源(对应研究报告中的章节/数据点 URL)
        mined_at: 提取时间(UTC)
    """

    main_story: str = ""
    characters: list[str] = Field(default_factory=list)
    enterprises: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    data_points: list[str] = Field(default_factory=list)
    time_span: str = ""
    conflict_type: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    mined_at: datetime = Field(default_factory=_utcnow)


class TopicCandidate(BaseModel):
    """选题候选(从本地研究数据库中发现的有传播价值的研究案例)。

    由 TopicAgent 从本地 reports/ 目录扫描生成,用于帮助创作者发现值得研究的县城。
    第一版不联网,仅基于已有研究报告数据库。

    Attributes:
        county: 县名
        core_industry: 核心产业(如"煤炭""脐橙""电子信息")
        historical_contrast: 历史反差(如"从矿都到空心镇""从贫困县到全国示范")
        rise_fall_pattern: 兴衰模式(如"resource_curse""policy_driven")
        key_data: 关键数据亮点(如"产值从 30 亿跌至 3 亿""人口流失 60%")
        report_path: 对应的研究报告路径
        score: 综合评分(基于历史反差度/产业代表性/数据丰富度)
        reason: 推荐理由(简述为何该县值得研究/传播)
        created_at: 创建时间(UTC)
    """

    county: str = ""
    core_industry: str = ""
    historical_contrast: str = ""
    rise_fall_pattern: str = ""
    key_data: list[str] = Field(default_factory=list)
    report_path: str = ""
    score: float = 0.0
    reason: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class ContentPackage(BaseModel):
    """短视频内容包(最终交付物)。

    将故事线/选题/脚本/核查结果打包,便于公众号、小红书等渠道扩展。

    Attributes:
        county: 县名
        report_path: 来源研究报告路径
        story_line: 故事线(可选,第二阶段新增)
        angle: 选题角度
        script: 短视频脚本
        fact_check: 事实核查结果
        produced_at: 内容包生成时间(UTC)
    """

    county: str = ""
    report_path: str = ""
    story_line: StoryLine | None = None  # 第二阶段新增,可选
    angle: ContentAngle = Field(default_factory=ContentAngle)
    script: VideoScript = Field(default_factory=VideoScript)
    fact_check: FactCheckResult = Field(default_factory=FactCheckResult)
    produced_at: datetime = Field(default_factory=_utcnow)
