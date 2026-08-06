"""流程编排模块。

串联 search → storage → llm → reporting 四层,定义单向 Pipeline:

    1. search   采集数据     → RawDoc[]
    2. storage  清洗落盘     → ProcessedData (含缓存复用)
    3. llm      智能分析     → AnalysisResult[]
    4. reporting 渲染报告    → ResearchReport + 落盘 Markdown

MVP 阶段:单线程顺序执行(settings.pipeline.mode="sequential")。

Mock 兜底策略(路径A):
    - search/web_search.py   未实现 → 使用 MockSearchProvider(构造示例 RawDoc)
    - storage/local_fs.py    未实现 → 使用 MockStorage(内存存储)
    - llm/client.py          未实现 → 使用 MockLLMClient(构造示例分析文本)
    - reporting/renderer.py  未实现 → 使用内置简易渲染器
这样在不写真实业务实现的情况下,依然可以完整跑通:
    CLI 输入 → Pipeline → 报告 Markdown 文件

后续各层实现完成后,只需替换 create_default_pipeline() 中的 mock 为真实实现,
Pipeline 逻辑本身无需修改。
"""
from __future__ import annotations

import logging
import logging.config
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_settings
from .exceptions import LLMError, PipelineError, SearchError
from .llm.analyzer import LLMAnalyzer
from .llm.base import LLMClient, LLMResponse
from .llm.client import OpenAICompatibleClient
from .llm.long_history_analyzer import LongHistoryAnalyzer
from .llm.rise_fall_analyzer import RiseFallAnalyzer
from .models import (
    AnalysisResult,
    CountyInfo,
    CountyLongHistoryAnalysis,
    CountyRiseFallAnalysis,
    DiscoveryResult,
    ProcessedData,
    RawDoc,
    ReportSection,
    ResearchReport,
    ResearchRequest,
)
from .processor import DocumentProcessor
from .reporting import ReportRenderer
from .reporting.long_history_renderer import LongHistoryReportRenderer
from .reporting.rise_fall_renderer import RiseFallReportRenderer
from .search.base import SearchProvider
from .search.collector import SearchCollector
from .storage.base import Storage
from .storage.local_fs import LocalFSStorage

logger = logging.getLogger(__name__)


# ===== Pipeline 主类 =====


class ResearchPipeline:
    """研究流程编排器。

    Usage:
        pipeline = ResearchPipeline(
            search=..., storage=..., llm=..., reporting_renderer=...
        )
        report, report_path = pipeline.run(
            ResearchRequest(county="安吉县", focus="竹产业")
        )
    """

    def __init__(
        self,
        *,
        search: SearchProvider,
        storage: Storage,
        llm: LLMClient,
        analyzer: LLMAnalyzer | None = None,
        renderer: ReportRenderer | None = None,
        rise_fall_analyzer: RiseFallAnalyzer | None = None,
        rise_fall_renderer: RiseFallReportRenderer | None = None,
        long_history_analyzer: LongHistoryAnalyzer | None = None,
        long_history_renderer: LongHistoryReportRenderer | None = None,
    ) -> None:
        self.search = search
        self.storage = storage
        self.llm = llm
        # analyzer 默认基于传入的 llm 客户端构造
        self.analyzer = analyzer or LLMAnalyzer(llm=llm)
        # renderer 默认使用 ReportRenderer(基于 Jinja2 模板)
        self.renderer = renderer or ReportRenderer()
        # rise-fall 模式专用分析器与渲染器(按需构造,复用同一 llm 客户端)
        self.rise_fall_analyzer = rise_fall_analyzer or RiseFallAnalyzer(llm=llm)
        self.rise_fall_renderer = rise_fall_renderer or RiseFallReportRenderer()
        # long-history 模式专用分析器与渲染器(复用同一 llm 客户端)
        self.long_history_analyzer = (
            long_history_analyzer or LongHistoryAnalyzer(llm=llm)
        )
        self.long_history_renderer = (
            long_history_renderer or LongHistoryReportRenderer()
        )

    # ---- 公开入口 ----

    def run(self, request: ResearchRequest) -> tuple[ResearchReport, Path]:
        """执行完整研究流程,返回 (报告对象, 报告文件路径)。

        Raises:
            PipelineError: 任一阶段失败且 fail_fast=True
        """
        settings = get_settings()
        stages = settings.pipeline.stages
        fail_fast = settings.pipeline.fail_fast

        county_info = CountyInfo.from_name(request.county)
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

        # 模式归一化:industry 是 snapshot 的别名(规格要求保留 --mode industry)
        mode_normalized = request.mode
        if mode_normalized == "industry":
            mode_normalized = "snapshot"
        request.mode = mode_normalized

        logger.info(
            "研究启动 | 县=%s | 方向=%s | 模式=%s",
            county_info.display(), request.focus, request.mode,
        )

        # 模式路由:long-history / rise-fall / snapshot(含 industry)
        if request.mode == "rise-fall":
            return self._run_rise_fall(request, county_info, date_str)
        if request.mode == "long-history":
            return self._run_long_history(request, county_info, date_str)

        logger.info(
            "Pipeline 阶段 | search=%s | process=%s | analyze=%s | report=%s",
            stages.search, stages.process, stages.analyze, stages.report,
        )

        # -------- 阶段 1: 采集 --------
        raw_docs: list[RawDoc] = []
        if stages.search:
            try:
                raw_docs = self._stage_search(county_info, request.focus or "")
                logger.info("阶段搜索完成 | 文档数=%d", len(raw_docs))
            except Exception as e:
                self._handle_stage_error("search", e, fail_fast)
        else:
            logger.info("阶段搜索已跳过")

        # -------- 阶段 1.5: 产业方向自动发现(仅当用户未指定 --focus) --------
        focus = request.focus
        if not focus and raw_docs:
            logger.info("未指定产业方向,开始自动发现...")
            try:
                discovery = self._stage_discover(county_info, raw_docs)
                if discovery.selected_focus:
                    focus = discovery.selected_focus
                    logger.info(
                        "产业方向自动发现完成 | 选定方向=%s | 候选数=%d",
                        focus, len(discovery.candidates),
                    )
                    if discovery.candidates:
                        top3 = ", ".join(
                            f"{c.industry}(置信度{c.confidence:.0%})"
                            for c in discovery.candidates[:3]
                        )
                        logger.info("候选产业方向: %s", top3)
                else:
                    logger.warning(
                        "产业方向发现未能选出结果(降级为特色农业) | 候选数=%d",
                        len(discovery.candidates),
                    )
                    focus = "特色农业"
            except Exception as e:
                logger.warning(
                    "产业方向发现失败(降级为特色农业) | err=%s", e,
                )
                focus = "特色农业"
        elif not focus:
            logger.warning("搜索结果为空且未指定产业方向,降级为特色农业")
            focus = "特色农业"

        # -------- 阶段 2: 处理(清洗+存盘+缓存读取) --------
        processed: ProcessedData | None = None
        if stages.process:
            try:
                # --no-cache 通过 request.options 传入;为 True 时强制 cache_hours=0 跳过缓存
                skip_cache = bool(request.options.get("no_cache"))
                cache_hours = 0 if skip_cache else (
                    settings.cache.ttl_hours if settings.cache.enabled else 0
                )
                processed = self._stage_process(
                    county_info, focus, raw_docs,
                    cache_hours=cache_hours,
                )
                logger.info("阶段处理完成 | 文档数=%d | 字符数=%d",
                            len(processed.docs), processed.total_chars)
            except Exception as e:
                self._handle_stage_error("process", e, fail_fast)
        else:
            logger.info("阶段处理已跳过")

        # -------- 阶段 3: LLM 分析 --------
        analyses: list[AnalysisResult] = []
        if stages.analyze and processed is not None:
            try:
                analyses = self._stage_analyze(county_info, focus, processed)
                logger.info("阶段分析完成 | 任务数=%d", len(analyses))
            except Exception as e:
                self._handle_stage_error("analyze", e, fail_fast)
        else:
            logger.info("阶段分析已跳过")

        # -------- 阶段 4: 报告渲染 + 存盘 --------
        report: ResearchReport | None = None
        report_path: Path | None = None
        if stages.report:
            try:
                report, report_path = self._stage_report(
                    county_info, focus, date_str, analyses, processed,
                )
                logger.info("阶段报告完成 | 章节数=%d | 路径=%s",
                            report.section_count, report_path)
            except Exception as e:
                self._handle_stage_error("report", e, fail_fast)
        else:
            logger.info("阶段报告已跳过")

        if report is None or report_path is None:
            raise PipelineError("Pipeline 完成但未生成报告", context={
                "stages_report": stages.report,
                "analyses_len": len(analyses),
            })

        logger.info("研究完成 | 报告已输出: %s", report_path)
        return report, report_path

    # ---- rise-fall 模式流程 ----

    def _run_rise_fall(
        self,
        request: ResearchRequest,
        county_info: CountyInfo,
        date_str: str,
    ) -> tuple[ResearchReport, Path]:
        """rise-fall 模式:县域产业兴衰规律研究。

        流程: search(历史维度) → process → rise_fall_analyzer → render → 落盘
        报告拼接逻辑委托给 RiseFallReportRenderer,不放在本方法内。
        """
        settings = get_settings()
        stages = settings.pipeline.stages
        fail_fast = settings.pipeline.fail_fast
        # rise-fall 模式 focus 可选(研究全县产业兴衰,非单一产业)
        focus = request.focus or "兴衰规律"

        logger.info(
            "rise-fall 流程启动 | 县=%s | 方向=%s",
            county_info.display(), focus,
        )

        # -------- 阶段 1: 采集(历史维度关键词) --------
        raw_docs: list[RawDoc] = []
        if stages.search:
            try:
                raw_docs = self._stage_search(
                    county_info, request.focus or "", mode="rise-fall",
                )
                logger.info("阶段搜索完成 | 文档数=%d", len(raw_docs))
            except Exception as e:
                self._handle_stage_error("search", e, fail_fast)
        else:
            logger.info("阶段搜索已跳过")

        # -------- 阶段 2: 处理(清洗+存盘+缓存读取) --------
        processed: ProcessedData | None = None
        if stages.process:
            try:
                skip_cache = bool(request.options.get("no_cache"))
                cache_hours = 0 if skip_cache else (
                    settings.cache.ttl_hours if settings.cache.enabled else 0
                )
                processed = self._stage_process(
                    county_info, focus, raw_docs,
                    cache_hours=cache_hours,
                )
                logger.info(
                    "阶段处理完成 | 文档数=%d | 字符数=%d",
                    len(processed.docs), processed.total_chars,
                )
            except Exception as e:
                self._handle_stage_error("process", e, fail_fast)
        else:
            logger.info("阶段处理已跳过")

        # -------- 阶段 3: 兴衰规律分析 --------
        analysis: CountyRiseFallAnalysis | None = None
        if stages.analyze and processed is not None:
            try:
                analysis = self.rise_fall_analyzer.analyze(
                    county=county_info, data=processed,
                )
                logger.info(
                    "阶段兴衰分析完成 | 起家=%s | 兴衰模型=%s | tokens=%d",
                    analysis.lifecycle.origin_industry,
                    analysis.historical_pattern.pattern_type,
                    analysis.tokens_used,
                )
            except Exception as e:
                self._handle_stage_error("analyze", e, fail_fast)
        else:
            logger.info("阶段分析已跳过")

        # -------- 阶段 4: 报告渲染 + 存盘 --------
        report_path: Path | None = None
        if stages.report:
            try:
                report_path = self._stage_rise_fall_report(
                    analysis, county_info, focus, date_str, processed,
                )
                logger.info("阶段报告完成 | 路径=%s", report_path)
            except Exception as e:
                self._handle_stage_error("report", e, fail_fast)
        else:
            logger.info("阶段报告已跳过")

        if report_path is None:
            raise PipelineError("rise-fall Pipeline 完成但未生成报告", context={
                "stages_report": stages.report,
            })

        # 构造一个 ResearchReport 兼容对象(供 CLI 获取章节数等元信息)
        section_titles = [
            "执行摘要", "一、县域基本画像", "二、起家产业", "三、兴起逻辑",
            "四、壮大机制", "五、关键拐点", "六、衰落机制", "七、人才流失分析",
            "八、县域兴衰模型归纳", "九、结论",
        ]
        report = ResearchReport(
            county=county_info,
            focus=focus,
            sections=[
                ReportSection(title=t, content="", order=i)
                for i, t in enumerate(section_titles, start=1)
            ],
            analyses=[],
        )

        logger.info("rise-fall 研究完成 | 报告已输出: %s", report_path)
        return report, report_path

    def _stage_rise_fall_report(
        self,
        analysis: CountyRiseFallAnalysis | None,
        county: CountyInfo,
        focus: str,
        date_str: str,
        processed: ProcessedData | None,
    ) -> Path:
        """rise-fall 阶段 4: 渲染兴衰规律报告并落盘。"""
        settings = get_settings()
        # 分析失败时构造空 analysis,渲染器会输出"数据不足"占位
        if analysis is None:
            analysis = CountyRiseFallAnalysis(county=county)

        raw_docs = processed.docs if processed else []
        md = self.rise_fall_renderer.render(analysis, raw_docs)

        # 文件名(与 snapshot 区分:加 rise_fall 标识)
        filename = self._render_filename(
            settings.app.report_filename_template,
            {"county": county.name, "focus": focus, "date": date_str},
        )
        return self.storage.save_report(filename, md)

    # ---- long-history 模式流程 ----

    def _run_long_history(
        self,
        request: ResearchRequest,
        county_info: CountyInfo,
        date_str: str,
    ) -> tuple[ResearchReport, Path]:
        """long-history 模式:县域长周期兴衰史研究(数百年尺度)。

        流程: search(长周期史料查询) → process → periods → geo_origin
              → traditional → modern → state → reform → contemporary
              → pattern → report
        """
        settings = get_settings()
        stages = settings.pipeline.stages
        fail_fast = settings.pipeline.fail_fast
        focus = request.focus or "长周期兴衰史"

        logger.info(
            "long-history 流程启动 | 县=%s | 方向=%s",
            county_info.display(), focus,
        )

        # -------- 阶段 1: 采集(长周期史料维度) --------
        raw_docs: list[RawDoc] = []
        if stages.search:
            try:
                raw_docs = self._stage_search(
                    county_info, request.focus or "", mode="long-history",
                )
                logger.info("阶段搜索完成 | 文档数=%d", len(raw_docs))
            except Exception as e:
                self._handle_stage_error("search", e, fail_fast)
        else:
            logger.info("阶段搜索已跳过")

        # -------- 阶段 2: 处理 --------
        processed: ProcessedData | None = None
        if stages.process:
            try:
                skip_cache = bool(request.options.get("no_cache"))
                cache_hours = 0 if skip_cache else (
                    settings.cache.ttl_hours if settings.cache.enabled else 0
                )
                processed = self._stage_process(
                    county_info, focus, raw_docs, cache_hours=cache_hours,
                )
                logger.info(
                    "阶段处理完成 | 文档数=%d | 字符数=%d",
                    len(processed.docs), processed.total_chars,
                )
            except Exception as e:
                self._handle_stage_error("process", e, fail_fast)
        else:
            logger.info("阶段处理已跳过")

        # -------- 阶段 3: 长周期分析(9 子任务) --------
        analysis: CountyLongHistoryAnalysis | None = None
        if stages.analyze and processed is not None:
            try:
                analysis = self.long_history_analyzer.analyze(
                    county=county_info, data=processed,
                )
                logger.info(
                    "长周期分析完成 | 阶段数=%d | 模型=%s",
                    len(analysis.periods),
                    analysis.long_history_pattern.pattern_type,
                )
            except Exception as e:
                self._handle_stage_error("analyze", e, fail_fast)
        else:
            logger.info("阶段分析已跳过")

        # -------- 阶段 4: 报告渲染 + 存盘 --------
        report_path: Path | None = None
        if stages.report:
            try:
                report_path = self._stage_long_history_report(
                    analysis, county_info, focus, date_str, processed,
                )
                logger.info("阶段报告完成 | 路径=%s", report_path)
            except Exception as e:
                self._handle_stage_error("report", e, fail_fast)
        else:
            logger.info("阶段报告已跳过")

        if report_path is None:
            raise PipelineError("long-history Pipeline 完成但未生成报告", context={
                "stages_report": stages.report,
            })

        section_titles = [
            "执行摘要", "一、长周期总论", "二、建县与地理逻辑",
            "三、传统时代生存方式", "四、近代冲击与变迁",
            "五、计划经济时期再组织", "六、改革开放后的产业重塑",
            "七、新世纪以来发展变化", "八、长周期兴衰模型", "九、历史规律总结",
        ]
        report = ResearchReport(
            county=county_info,
            focus=focus,
            sections=[
                ReportSection(title=t, content="", order=i)
                for i, t in enumerate(section_titles, start=1)
            ],
            analyses=[],
        )

        logger.info("long-history 研究完成 | 报告已输出: %s", report_path)
        return report, report_path

    def _stage_long_history_report(
        self,
        analysis: CountyLongHistoryAnalysis | None,
        county: CountyInfo,
        focus: str,
        date_str: str,
        processed: ProcessedData | None,
    ) -> Path:
        """long-history 阶段 4:渲染 9 节长周期报告并落盘。"""
        settings = get_settings()
        if analysis is None:
            analysis = CountyLongHistoryAnalysis(county=county)
        raw_docs = processed.docs if processed else []
        md = self.long_history_renderer.render(analysis, raw_docs)

        # 文件名(复用 rise-fall 的文件名渲染逻辑,加 long_history 标识)
        filename = self._render_filename(
            settings.app.report_filename_template,
            {"county": county.name, "focus": focus, "date": date_str},
        )
        return self.storage.save_report(filename, md)

    @staticmethod
    def _render_filename(template: str, context: dict[str, str]) -> str:
        """通用文件名渲染(Jinja2)。"""
        from jinja2 import Template
        try:
            return Template(template).render(**context)
        except Exception as e:
            raise PipelineError(
                "报告文件名渲染失败",
                context={"template": template, "error": str(e)},
            ) from e

    # ---- 各阶段内部方法 ----

    def _stage_search(
        self, county: CountyInfo, focus: str, mode: str = "snapshot",
    ) -> list[RawDoc]:
        """阶段 1: 调用 SearchCollector 采集原始数据(Web + Gov 并发)。

        Args:
            county: 县域信息
            focus: 研究方向(rise-fall 模式可为空)
            mode: 研究模式 snapshot / rise-fall(rise-fall 使用历史维度关键词)
        """
        if isinstance(self.search, SearchCollector):
            settings = get_settings()
            try:
                return self.search.collect(
                    county=county.display(),
                    focus=focus,
                    max_results=settings.search.max_results,
                    mode=mode,
                )
            except Exception as e:
                logger.warning("Collector 采集失败(降级处理) | err=%s", e)
                if get_settings().pipeline.fail_fast:
                    raise
                return []

        # 兼容: 非 Collector 的 SearchProvider(Mock 等场景),退化为多查询简单合并
        queries = [
            f"{county.display()} {focus} 产业 发展",
            f"{county.display()} {focus} 产值 企业",
            f"{county.display()} 产业 园区 规划",
        ]
        settings = get_settings()
        all_docs: dict[str, RawDoc] = {}  # url 去重
        for q in queries:
            try:
                docs = self.search.search(q, max_results=settings.search.max_results)
                for doc in docs:
                    if doc.url and doc.url not in all_docs:
                        all_docs[doc.url] = doc
            except Exception as e:
                logger.warning("搜索失败(降级处理) | query=%s | err=%s", q, e)
                if settings.pipeline.fail_fast:
                    raise
        return list(all_docs.values())

    def _stage_discover(
        self, county: CountyInfo, raw_docs: list[RawDoc]
    ) -> DiscoveryResult:
        """阶段 1.5: 从搜索结果中自动识别该县重点产业方向。

        委托给 LLMAnalyzer.discover_focus() 执行。
        """
        return self.analyzer.discover_focus(county=county, raw_docs=raw_docs)

    def _stage_process(
        self,
        county: CountyInfo,
        focus: str,
        raw_docs: list[RawDoc],
        *,
        cache_hours: int,
    ) -> ProcessedData:
        """阶段 2: 先尝试读取缓存;未命中则委托 DocumentProcessor 处理并落盘。"""
        if cache_hours > 0:
            cached = self.storage.load_processed(county.name, focus, max_age_hours=cache_hours)
            if cached is not None:
                logger.info("处理阶段命中缓存 | 县=%s | 方向=%s", county.name, focus)
                return cached

        # 无缓存 → DocumentProcessor 处理
        processor = DocumentProcessor(quality_config=get_settings().quality)
        processed = processor.process(raw_docs, county=county, focus=focus)

        # 落盘(Pipeline 负责,Processor 不直接调用 Storage)
        self.storage.save_processed(county.name, focus, processed)
        self.storage.save_raw(county.name, processed.docs)
        return processed

    def _stage_analyze(
        self, county: CountyInfo, focus: str, data: ProcessedData
    ) -> list[AnalysisResult]:
        """阶段 3: 委托给 LLMAnalyzer 按 settings.llm.tasks 依次分析。

        analyzer 内部已处理:
            - prompt 模板加载与 fallback
            - 单任务失败降级(受 fail_fast 控制)
            - token 用量统计
        """
        return self.analyzer.analyze(county=county, focus=focus, data=data)

    def _stage_report(
        self,
        county: CountyInfo,
        focus: str,
        date_str: str,
        analyses: list[AnalysisResult],
        processed: ProcessedData | None,
    ) -> tuple[ResearchReport, Path]:
        """阶段 4: 将 analyses 拼装为 ReportSection,渲染为 Markdown 并存盘。"""
        settings = get_settings()

        title_map = {
            "industry_status": "一、产业现状分析",
            "advantages": "二、优势分析",
            "shortcomings": "三、短板分析",
            "recommendations": "四、发展建议",
        }

        sections: list[ReportSection] = []

        # 摘要(委托给 analyzer.generate_summary,使用 summary.md 模板)
        summary_text = self.analyzer.generate_summary(county=county, focus=focus, analyses=analyses)
        sections.append(ReportSection(title="执行摘要", content=summary_text, order=1))

        # 各分析章节
        order = 2
        for a in analyses:
            if a.task not in title_map:
                continue
            sections.append(ReportSection(
                title=title_map[a.task],
                content=a.content,
                order=order,
                sources=[doc.url for doc in (processed.docs if processed else [])][:10],
            ))
            order += 1

        # 数据来源
        if processed:
            src_lines = [f"- [{doc.title}]({doc.url})" for doc in processed.docs[:20] if doc.url]
            src_text = "\n".join(src_lines) if src_lines else "_无_"
        else:
            src_text = "_无_"
        sections.append(ReportSection(title="数据来源", content=src_text, order=order))

        sections.sort(key=lambda s: s.order)

        report = ResearchReport(
            county=county,
            focus=focus,
            sections=sections,
            analyses=analyses,
        )

        # 渲染 Markdown(委托给 ReportRenderer)
        md = self.renderer.render_markdown(report)

        # 文件名 + 存盘
        filename = self.renderer.render_filename(
            settings.app.report_filename_template,
            {"county": county.name, "focus": focus, "date": date_str},
        )
        report_path = self.storage.save_report(filename, md)
        return report, report_path

    # ---- 辅助方法 ----

    @staticmethod
    def _handle_stage_error(stage: str, err: Exception, fail_fast: bool) -> None:
        """错误处理:fail_fast 则抛 PipelineError 终止;否则仅记录。"""
        logger.error("阶段失败 | stage=%s | err=%s", stage, err, exc_info=True)
        if fail_fast:
            raise PipelineError(
                f"Pipeline 阶段失败: {stage}",
                context={"stage": stage, "error": str(err)},
            ) from err


# ===== Mock 实现(从 mocks/ 重导出,保持向后兼容) =====

from .mocks import MockLLMClient, MockSearchProvider, MockStorage  # noqa: F401,E402


# ===== 模块级工厂 =====


def create_default_pipeline() -> ResearchPipeline:
    """构造默认 Pipeline。

    自动降级策略(三层兜底,保证链路始终可跑):
        - storage: 始终用正式实现 LocalFSStorage
        - llm:     有 API Key → OpenAICompatibleClient(真实)
                   否则 → MockLLMClient(报告内容为构造示例)
        - search:  有搜索 API Key → SearchCollector(Web + Gov 并发)
                   否则 → MockSearchProvider(3 条构造的示例文档)
    """
    settings = get_settings()

    # ---- search 选择 ----
    search_key = settings.search.api_key.get_secret_value() if settings.search.api_key else ""
    if search_key:
        try:
            search = SearchCollector.from_settings(settings=settings)
            logger.info(
                "搜索使用真实 SearchCollector | web_provider=%s",
                settings.search.provider,
            )
        except SearchError as e:
            logger.warning(
                "SearchCollector 初始化失败,降级为 MockSearchProvider | err=%s", e,
            )
            search = MockSearchProvider()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "SearchCollector 初始化异常,降级为 MockSearchProvider | err=%s", e,
            )
            search = MockSearchProvider()
    else:
        logger.warning(
            "未配置搜索 API Key,降级为 MockSearchProvider(采集数据为构造示例,非真实网页)。"
            "请在 .env 中配置搜索 API Key(TAVILY_API_KEY / SERPER_API_KEY / BING_API_KEY)。"
        )
        search = MockSearchProvider()

    # ---- llm 选择 ----
    llm_key = settings.llm.api_key.get_secret_value() if settings.llm.api_key else ""
    if llm_key:
        try:
            llm = OpenAICompatibleClient(settings=settings)
            logger.info("LLM 使用真实客户端 | provider=%s | model=%s",
                        settings.llm.provider, settings.llm.model)
        except LLMError as e:
            logger.warning(
                "真实 LLM 客户端初始化失败,降级为 MockLLM | err=%s", e,
            )
            llm = MockLLMClient()
    else:
        logger.warning(
            "未配置 LLM_API_KEY,降级为 MockLLM(报告内容为构造示例,非真实分析)。"
            "请在 .env 中配置 LLM_API_KEY 以启用真实 LLM 分析。"
        )
        llm = MockLLMClient()

    return ResearchPipeline(
        search=search,
        storage=LocalFSStorage(),
        llm=llm,
    )


def setup_logging() -> None:
    """初始化日志(从 settings.logging 读取配置)。"""
    settings = get_settings()
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": settings.logging.format,
                "datefmt": settings.logging.date_format,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": settings.logging.level,
                "formatter": "standard",
            },
        },
        "loggers": {
            "": {  # root
                "handlers": ["console"],
                "level": settings.logging.level,
                "propagate": True,
            },
        },
    })
