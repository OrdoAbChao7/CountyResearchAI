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

from jinja2 import Template

from .config import get_settings
from .exceptions import ConfigError, LLMError, PipelineError, SearchError
from .llm.analyzer import LLMAnalyzer
from .llm.base import LLMClient, LLMResponse
from .llm.client import OpenAICompatibleClient
from .models import (
    AnalysisResult,
    CountyInfo,
    ProcessedData,
    RawDoc,
    ReportSection,
    ResearchReport,
    ResearchRequest,
)
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
    ) -> None:
        self.search = search
        self.storage = storage
        self.llm = llm
        # analyzer 默认基于传入的 llm 客户端构造
        self.analyzer = analyzer or LLMAnalyzer(llm=llm)

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

        logger.info("研究启动 | 县=%s | 方向=%s", county_info.display(), request.focus)
        logger.info(
            "Pipeline 阶段 | search=%s | process=%s | analyze=%s | report=%s",
            stages.search, stages.process, stages.analyze, stages.report,
        )

        # -------- 阶段 1: 采集 --------
        raw_docs: list[RawDoc] = []
        if stages.search:
            try:
                raw_docs = self._stage_search(county_info, request.focus)
                logger.info("阶段搜索完成 | 文档数=%d", len(raw_docs))
            except Exception as e:
                self._handle_stage_error("search", e, fail_fast)
        else:
            logger.info("阶段搜索已跳过")

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
                    county_info, request.focus, raw_docs,
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
                analyses = self._stage_analyze(county_info, request.focus, processed)
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
                    county_info, request.focus, date_str, analyses, processed,
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

    # ---- 各阶段内部方法 ----

    def _stage_search(self, county: CountyInfo, focus: str) -> list[RawDoc]:
        """阶段 1: 调用 SearchCollector 采集原始数据(Web + Gov 并发)。

        优先使用 SearchCollector.collect(基于多查询模板并发采集):
            - 如果 self.search 是 SearchCollector,直接调用 collect;
            - 否则退化为单 provider 调用 search()(兼容 MockSearchProvider 等兜底场景)。
        """
        if isinstance(self.search, SearchCollector):
            settings = get_settings()
            try:
                return self.search.collect(
                    county=county.display(),
                    focus=focus,
                    max_results=settings.search.max_results,
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

    def _stage_process(
        self,
        county: CountyInfo,
        focus: str,
        raw_docs: list[RawDoc],
        *,
        cache_hours: int,
    ) -> ProcessedData:
        """阶段 2: 先尝试读取缓存;未命中则构造 ProcessedData 并落盘。"""
        if cache_hours > 0:
            cached = self.storage.load_processed(county.name, focus, max_age_hours=cache_hours)
            if cached is not None:
                logger.info("处理阶段命中缓存 | 县=%s | 方向=%s", county.name, focus)
                return cached

        # 无缓存 → 构造 ProcessedData(MVP:仅做长度统计与简单去重)
        seen_urls: set[str] = set()
        unique: list[RawDoc] = []
        total = 0
        for doc in raw_docs:
            if doc.url in seen_urls:
                continue
            seen_urls.add(doc.url)
            unique.append(doc)
            total += len(doc.content) + len(doc.snippet)

        processed = ProcessedData(
            county=county,
            focus=focus,
            docs=unique,
            total_chars=total,
        )
        self.storage.save_processed(county.name, focus, processed)
        self.storage.save_raw(county.name, unique)
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

        # 渲染 Markdown
        md = self._render_markdown(report)

        # 文件名 + 存盘
        filename = self._render_filename(settings.app.report_filename_template, {
            "county": county.name,
            "focus": focus,
            "date": date_str,
        })
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

    @staticmethod
    def _build_analysis_prompt(
        task: str, county: CountyInfo, focus: str, date: str, data_text: str
    ) -> str:
        """MVP 简易 prompt 构造;真实实现替换为 prompts/ 模板渲染。"""
        task_prompt = {
            "industry_status": "请分析该县该产业的现状、规模、产业链结构与市场主体。",
            "advantages": "请分析该县在该产业上的核心优势(区位/资源/政策/龙头企业等)。",
            "shortcomings": "请分析该县在该产业上的短板与风险。",
            "recommendations": "请给出可落地的发展建议(问题→对策→路径)。",
        }.get(task, f"请分析该县{focus}产业的{task}。")

        return (
            f"## 研究对象\n- 县名: {county.display()}\n- 方向: {focus}\n- 日期: {date}\n\n"
            f"## 参考数据\n```\n{data_text or '(暂无数据,使用示例数据)'}\n```\n\n"
            f"## 任务\n{task_prompt}\n\n"
            "请用中文 Markdown 输出,每条结论有数据或事实支撑,字数 500-800。"
        )

    @staticmethod
    def _build_summary(county: CountyInfo, focus: str, analyses: list[AnalysisResult]) -> str:
        """简易摘要:从 analyses 首段抽取 2-3 句,若无则输出占位。"""
        if not analyses:
            return f"本报告针对 {county.display()} {focus} 产业开展初步研究。"
        head = analyses[0].content.splitlines()[:5]
        head_clean = [ln for ln in head if ln.strip() and not ln.strip().startswith("#")]
        text = " ".join(head_clean[:2]) if head_clean else analyses[0].content[:200]
        return f"本报告基于自动采集与分析,对 {county.display()} {focus} 产业进行了研究。\n\n{text}"

    @staticmethod
    def _render_markdown(report: ResearchReport) -> str:
        """简易 Markdown 渲染器。"""
        title = f"# {report.county.display()} {report.focus}产业研究报告"
        date_line = f"\n> 生成日期: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}  "
        version_line = f"> 报告版本: {report.version}  \n"

        parts = [title, date_line, version_line]
        for sec in report.sections:
            parts.append(f"\n## {sec.title}\n")
            parts.append(sec.content.rstrip())
            if sec.sources and sec.title != "数据来源":
                parts.append(f"\n> 数据参考来源数: {len(sec.sources)}")
        parts.append("")
        return "\n".join(parts)

    @staticmethod
    def _render_filename(template: str, context: dict[str, str]) -> str:
        """用 Jinja2 渲染报告文件名。"""
        try:
            return Template(template).render(**context)
        except Exception as e:
            raise ConfigError("报告文件名模板渲染失败", context={
                "template": template, "context": context, "error": str(e),
            }) from e


# ===== 默认工厂(路径A Mock 兜底) =====


class MockSearchProvider(SearchProvider):
    """Mock 搜索:返回构造的示例 RawDoc,链路可跑不需要真实 API。"""

    name = "mock"

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        logger.debug("MockSearch.search | query=%s", query)
        county_hint = query.split()[0] if query else "某县"
        focus_hint = query.split()[1] if len(query.split()) > 1 else "产业"
        now = datetime.now(timezone.utc)
        return [
            RawDoc(
                title=f"{county_hint}{focus_hint}产业年产值突破百亿",
                url=f"https://example.gov.cn/{county_hint}/tjgb-1",
                snippet="近年该县特色产业快速发展,规上企业超过80家,从业人员超3万人。",
                content=(
                    f"据{county_hint}2025年统计公报,{focus_hint}产业规上企业达到82家,"
                    f"实现产值120亿元,同比增长15%。产业园区占地约2000亩,"
                    f"入驻企业56家,形成了上游种植、中游加工、下游销售的完整链条。"
                ),
                source="mock-gov",
                fetched_at=now,
            ),
            RawDoc(
                title=f"{county_hint}十四五{focus_hint}产业发展规划",
                url=f"https://example.gov.cn/{county_hint}/fzgh-2",
                snippet="该县十四五规划明确提出重点打造百亿级特色产业集群。",
                content=(
                    f"《{county_hint}十四五{focus_hint}产业发展规划》提出:"
                    f"到2027年实现产值200亿元,培育龙头企业10家,"
                    f"建成省级产业园区1个,公共服务平台3个。"
                    f"重点方向:品牌建设、精深加工、冷链物流、电子商务。"
                ),
                source="mock-gov",
                fetched_at=now,
            ),
            RawDoc(
                title=f"龙头XX股份带动{focus_hint}产业升级",
                url=f"https://example.com/news/{county_hint}-top-enterprise",
                snippet=f"本地龙头XX股份{focus_hint}精深加工线投产,年新增产值20亿。",
                content=(
                    f"本地龙头企业XX股份2024年投产国内首条智能化{focus_hint}精深加工线,"
                    f"年产能达12万吨,新增产值约20亿元。该企业通过'公司+合作社+农户'模式,"
                    f"带动全县6000余农户增收,户均年增收约1.5万元。"
                ),
                source="mock-news",
                fetched_at=now,
            ),
        ]


class MockStorage(Storage):
    """已弃用 — 早期路径 A 阶段的简易存储实现。

    保留此类的目的:
        1. 作为单元测试中 LocalFSStorage 的轻量替代(不依赖磁盘)
        2. 与 LocalFSStorage 的行为对照参考

    正式生产链路请使用 LocalFSStorage(见 storage/local_fs.py)。
    本类不再被 create_default_pipeline 使用。
    """

    name = "mock-storage"

    def __init__(self) -> None:
        settings = get_settings()
        self._raw_dir = settings.data_dir / settings.storage.raw_subdir
        self._proc_dir = settings.data_dir / settings.storage.processed_subdir
        self._reports_dir = settings.reports_dir
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        self._proc_dir.mkdir(parents=True, exist_ok=True)
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, Any] = {}

    def save_raw(self, county: str, docs: list[RawDoc]) -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        layout = get_settings().storage.archive_layout
        sub = layout.format(county=county, date=date_str)
        p = self._raw_dir / sub
        p.mkdir(parents=True, exist_ok=True)
        f = p / "raw_docs.json"
        f.write_text(
            "[" + ",".join(d.model_dump_json(indent=2) for d in docs) + "]",
            encoding="utf-8",
        )
        return p

    def load_raw(self, county: str) -> list[RawDoc]:
        sub = self._raw_dir / county
        if not sub.exists():
            return []
        latest = sorted(sub.glob("*/raw_docs.json"), reverse=True)
        if not latest:
            return []
        import json
        data = json.loads(latest[0].read_text(encoding="utf-8"))
        return [RawDoc(**d) for d in data]

    def save_processed(self, county: str, focus: str, data: ProcessedData) -> Path:
        p = self._proc_dir / county
        p.mkdir(parents=True, exist_ok=True)
        f = p / f"{focus}.json"
        f.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        self._mem[f"{county}:{focus}"] = f
        return f

    def load_processed(
        self, county: str, focus: str, max_age_hours: int = 0
    ) -> ProcessedData | None:
        p = self._proc_dir / county / f"{focus}.json"
        if not p.exists():
            return None
        if max_age_hours > 0:
            import time
            age_h = (time.time() - p.stat().st_mtime) / 3600
            if age_h > max_age_hours:
                logger.info("processed 缓存已过期 | 县=%s | 方向=%s | 年龄=%.1fh",
                            county, focus, age_h)
                return None
        import json
        data = json.loads(p.read_text(encoding="utf-8"))
        return ProcessedData(**data)

    def save_report(self, filename: str, content: str) -> Path:
        p = self._reports_dir / filename
        p.write_text(content, encoding="utf-8")
        logger.info("报告已写入: %s", p)
        return p


class MockLLMClient(LLMClient):
    """Mock LLM:根据 task 返回构造的分析文本,无需真实 API。"""

    name = "mock-llm"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        # 从 messages 中解析 task 关键词
        user_msg = "\n".join(m.get("content", "") for m in messages)
        task = "industry_status"
        if "优势" in user_msg:
            task = "advantages"
        elif "短板" in user_msg or "风险" in user_msg:
            task = "shortcomings"
        elif "建议" in user_msg or "对策" in user_msg:
            task = "recommendations"

        content = {
            "industry_status": (
                "## 产业概况\n"
                "该县该产业已形成'种植(上游)—加工(中游)—销售(下游)'完整产业链,"
                "规上企业80余家,2025年产值约120亿元,占全县GDP约18%,是县域经济第一支柱产业。\n\n"
                "## 产业链结构\n"
                "- 上游:种源培育与规模化种植,全县种植面积约50万亩\n"
                "- 中游:82家规上加工企业,主要产品为初加工原料、食品、保健品三大类\n"
                "- 下游:覆盖全国的线下经销网络 + 电商渠道占比已达35%\n\n"
                "## 市场主体\n"
                "1家主板上市龙头,3家省级专精特新企业,产业园区1个(省级),入驻企业56家。\n\n"
                "## 发展阶段判断\n"
                "处于**成长期后期向成熟期过渡**阶段——规模基本形成,但精深加工与品牌溢价仍有提升空间。"
            ),
            "advantages": (
                "## 核心优势\n"
                "1. **资源禀赋** — 县域气候土壤适配度全国Top3,原料品质稳定,具备产地差异化基础\n"
                "2. **产业基础** — 60年种植传统,熟练工人充足,配套加工产能集中\n"
                "3. **龙头带动** — XX股份上市后具备全国品牌影响力,精深加工技术领先\n"
                "4. **政策支持** — 纳入省级特色产业集群,十四五规划明确百亿级目标与配套资金"
            ),
            "shortcomings": (
                "## 主要短板\n"
                "1. **精深加工占比偏低** — 初加工占产值70%,利润率仅为精深加工的1/5,附加值挖掘不足\n"
                "2. **区域品牌辨识度弱** — 企业品牌强、区域品牌弱,消费者对该县与该产业的关联度认知低\n"
                "3. **数字化水平滞后** — 中小企业信息化覆盖率不足40%,供应链协同效率偏低\n"
                "4. **人才供给不足** — 食品加工、电商运营、品牌营销等中高端岗位招聘困难"
            ),
            "recommendations": (
                "## 建议一:补精深加工短板(1年内见成效)\n"
                "- **问题**:初加工占比过高,价值链中高端环节缺失\n"
                "- **对策**:通过专项技改补贴 + 龙头示范线带动,引导企业向功能食品、生物提取延伸\n"
                "- **路径**:"
                "  短期(6个月):出台精深加工技改补贴(设备投入补贴30%,上限500万);"
                "  中期(1-2年):龙头XX股份开放工艺合作,建设共享中试车间;"
                "  长期(3年):打造精深加工产业集聚区\n"
                "- **责任主体**:县工信局+龙头企业+产业园区管委会\n"
                "- **预期成效**:2027年精深加工占比提升至40%,产业利润率提升3-5个百分点\n\n"
                "## 建议二:区域品牌建设(1年启动,3年见规模)\n"
                "- **问题**:消费者对该县与该产业关联度低,产品溢价难以实现\n"
                "- **对策**:打造地理标志证明商标 + 统一区域公共品牌 + 电商矩阵运营\n"
                "- **路径**:"
                "  短期:完成地理标志申报,统一区域品牌VI;"
                "  中期:入驻头部电商公共品牌专区,对接MCN资源;"
                "  长期:进入国家级特色农产品优势区\n"
                "- **责任主体**:县农业农村局+商务局+市场监管局\n"
                "- **预期成效**:2028年区域品牌知名度进入全国Top10,产品溢价空间提升15%+"
            ),
        }[task]

        return LLMResponse(
            content=content,
            model="mock-llm-v1",
            prompt_tokens=800,
            completion_tokens=1200,
            total_tokens=2000,
        )


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
