"""LLM 产业分析器。

按 settings.llm.tasks 列表依次调用 LLM,对清洗后的数据进行产业分析,
产出结构化的 AnalysisResult 列表。

设计要点:
    - task → 模板映射:优先用 prompts/ 下的模板文件,不存在则用内联 fallback
    - 单任务失败不阻断整体:fail_fast=False 时降级为占位结果
    - generate_summary:单独提供执行摘要生成(使用 summary.md 模板)
    - 与 pipeline 解耦:pipeline 调用 analyze() 即可,无需关心 prompt 细节

task 模板映射(当前):
    industry_status   → industry_analysis.md
    advantages        → (fallback 内联)
    shortcomings      → (fallback 内联)
    recommendations   → recommendations.md
    summary           → summary.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import Settings, get_settings
from ..models import AnalysisResult, CountyInfo, DiscoveryCandidate, DiscoveryResult, ProcessedData
from .base import LLMClient
from .client import OpenAICompatibleClient
from .prompt_loader import PromptLoader

logger = logging.getLogger(__name__)


def _safe_str_list(value) -> list[str]:
    """将任意值安全转换为 list[str]。

    用于解析 LLM 返回的 JSON 字段,容忍 None / 单值 / 列表 等多种格式。
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]


@dataclass(frozen=True)
class TaskConfig:
    """单个分析任务的配置。

    Attributes:
        template_name: 模板文件名(不含扩展名);None 表示无模板,纯用 fallback
        fallback_prompt: 模板文件不存在时的内联 prompt(Jinja2 语法)
        description: 任务描述(用于日志)
    """
    template_name: str | None
    fallback_prompt: str
    description: str = ""


class LLMAnalyzer:
    """基于 LLM 的产业分析器。

    Usage:
        analyzer = LLMAnalyzer()  # 默认用 OpenAICompatibleClient + PromptLoader
        results = analyzer.analyze(county=ci, focus="竹产业", data=processed)
        summary = analyzer.generate_summary(county=ci, focus="竹产业", analyses=results)
    """

    # task → 配置映射
    # 模板文件存在时优先用模板;不存在时用 fallback_prompt
    TASK_CONFIGS: dict[str, TaskConfig] = {
        "industry_status": TaskConfig(
            template_name="industry_analysis",
            fallback_prompt=(
                "## 研究对象\n- 县名: {{ county }}\n- 方向: {{ focus }}\n- 日期: {{ date }}\n\n"
                "## 参考数据\n```\n{{ processed_data }}\n```\n\n"
                "## 任务\n请分析该县该产业的现状、规模、产业链结构与市场主体。"
                "用中文 Markdown 输出,每条结论有数据支撑,字数 500-800。"
            ),
            description="产业现状分析",
        ),
        "advantages": TaskConfig(
            template_name="advantages",  # 模板不存在则用 fallback
            fallback_prompt=(
                "## 研究对象\n- 县名: {{ county }}\n- 方向: {{ focus }}\n- 日期: {{ date }}\n\n"
                "## 参考数据\n```\n{{ processed_data }}\n```\n\n"
                "## 任务\n请分析该县在该产业上的核心优势"
                "(区位/资源/政策/龙头企业/产业基础等)。"
                "用中文 Markdown 输出,3-5 条要点,每条带数据或事实支撑。"
            ),
            description="优势分析",
        ),
        "shortcomings": TaskConfig(
            template_name="shortcomings",
            fallback_prompt=(
                "## 研究对象\n- 县名: {{ county }}\n- 方向: {{ focus }}\n- 日期: {{ date }}\n\n"
                "## 参考数据\n```\n{{ processed_data }}\n```\n\n"
                "## 任务\n请分析该县在该产业上的短板与风险"
                "(产业链/技术/人才/市场/制度等维度)。"
                "用中文 Markdown 输出,3-5 条要点,每条说明问题本质。"
            ),
            description="短板分析",
        ),
        "recommendations": TaskConfig(
            template_name="recommendations",
            fallback_prompt=(
                "## 研究对象\n- 县名: {{ county }}\n- 方向: {{ focus }}\n- 日期: {{ date }}\n\n"
                "## 参考数据\n```\n{{ processed_data }}\n```\n\n"
                "## 任务\n请给出可落地的发展建议,遵循'问题→对策→路径→责任→成效'结构。"
                "用中文 Markdown 输出,2-3 条建议,符合县级事权与资源约束。"
            ),
            description="发展建议",
        ),
    }

    # 摘要任务(不在 settings.llm.tasks 里,单独调用)
    SUMMARY_CONFIG = TaskConfig(
        template_name="summary",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n- 方向: {{ focus }}\n\n"
            "## 输入材料\n```\n{{ analysis_content }}\n```\n\n"
            "## 任务\n请撰写执行摘要:一句话结论 + 3-5 条关键发现 + 2-3 条决策建议。"
            "面向决策者,结论先行,总字数 400-600。"
        ),
        description="执行摘要",
    )

    # 产业方向发现任务(用户未指定 --focus 时调用)
    DISCOVER_CONFIG = TaskConfig(
        template_name="discovery",
        fallback_prompt=(
            "## 研究对象\n- 县名: {{ county }}\n- 日期: {{ date }}\n\n"
            "## 参考数据\n```\n{{ search_results }}\n```\n\n"
            "## 任务\n请识别该县最具代表性的 3-5 个重点产业方向,"
            "输出 JSON 格式: {candidates: [{industry, confidence, reason}], selected_focus}。"
            "每个候选要有数据支撑(产值/企业数/政府规划)。"
        ),
        description="产业方向自动发现",
    )

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt_loader: PromptLoader | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._llm = llm or OpenAICompatibleClient(settings=self._settings)
        self._prompt_loader = prompt_loader or PromptLoader(settings=self._settings)

    # ---- 公开接口 ----

    def analyze(
        self,
        county: CountyInfo,
        focus: str,
        data: ProcessedData,
        tasks: list[str] | None = None,
    ) -> list[AnalysisResult]:
        """按 task 列表依次分析,返回 AnalysisResult 列表。

        Args:
            county: 县域信息
            focus: 研究方向
            data: 清洗后的数据
            tasks: 任务列表(None 则用 settings.llm.tasks)

        Returns:
            AnalysisResult 列表(顺序与 tasks 一致)
        """
        task_list = tasks or self._settings.llm.tasks
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data_text = data.render_for_llm(max_chars=15000)

        results: list[AnalysisResult] = []
        for task in task_list:
            result = self._run_single_task(
                task=task,
                county=county,
                focus=focus,
                date_str=date_str,
                data_text=data_text,
            )
            results.append(result)
        return results

    def generate_summary(
        self,
        county: CountyInfo,
        focus: str,
        analyses: list[AnalysisResult],
    ) -> str:
        """生成执行摘要(使用 summary.md 模板或 fallback)。

        Args:
            county: 县域信息
            focus: 研究方向
            analyses: 已完成的分析结果列表

        Returns:
            摘要文本(Markdown)
        """
        # 拼接已有分析作为输入
        analysis_content = "\n\n".join(
            f"## {a.task}\n{a.content}" for a in analyses
        )
        if not analysis_content:
            analysis_content = "(暂无分析内容)"

        prompt = self._build_prompt_from_config(
            config=self.SUMMARY_CONFIG,
            county=county.display(),
            focus=focus,
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            processed_data=analysis_content,
            analysis_content=analysis_content,
        )

        try:
            resp = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=self._settings.llm.temperature,
                max_tokens=self._settings.llm.max_tokens,
            )
            logger.info(
                "摘要生成完成 | model=%s | tokens=%d",
                resp.model, resp.total_tokens,
            )
            return resp.content
        except Exception as e:
            logger.warning("摘要生成失败(降级为简易摘要) | err=%s", e)
            if self._settings.pipeline.fail_fast:
                raise
            # 降级:从首个分析抽取首段
            return self._fallback_summary(county, focus, analyses)

    def discover_focus(
        self,
        county: CountyInfo,
        raw_docs: list,
    ) -> DiscoveryResult:
        """从搜索结果中自动识别该县的重点产业方向。

        Args:
            county: 县域信息
            raw_docs: 搜索阶段产出的 RawDoc 列表

        Returns:
            DiscoveryResult 包含候选产业方向列表与选定的 focus
        """
        # 将搜索结果渲染为文本
        search_text = self._render_search_results(raw_docs)
        if not search_text.strip():
            logger.warning("产业方向发现:搜索结果为空,降级为通用推断")
            return self._fallback_discovery(county)

        prompt = self._build_prompt_from_config(
            config=self.DISCOVER_CONFIG,
            county=county.display(),
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            search_results=search_text,
        )

        logger.info("开始产业方向自动发现 | 县=%s | 搜索结果数=%d",
                    county.display(), len(raw_docs))
        try:
            resp = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=self._settings.llm.temperature,
                max_tokens=self._settings.llm.max_tokens,
            )
            logger.info(
                "产业方向发现完成 | model=%s | tokens=%d",
                resp.model, resp.total_tokens,
            )

            result = self._parse_discovery_response(
                resp.content,
                model=resp.model,
                tokens_used=resp.total_tokens,
            )
            logger.info(
                "产业方向发现结果 | 选定=%s | 候选数=%d",
                result.selected_focus, len(result.candidates),
            )
            return result
        except Exception as e:
            logger.warning(
                "产业方向发现失败(降级为通用推断) | err=%s", e, exc_info=True,
            )
            if self._settings.pipeline.fail_fast:
                raise
            return self._fallback_discovery(county)

    @staticmethod
    def _render_search_results(raw_docs: list) -> str:
        """将 RawDoc 列表渲染为 LLM 可读文本。

        格式:每条文档带编号 [N],便于 LLM 在 evidence_urls/supporting_documents 中引用。
        """
        blocks: list[str] = []
        for i, doc in enumerate(raw_docs, start=1):
            content = doc.content or doc.snippet or ""
            if not content:
                content = "(无摘要)"
            # 截断到 500 字符/文档,避免超出 token
            if len(content) > 500:
                content = content[:497] + "..."
            block = (
                f"[{i}] 标题: {doc.title}\n"
                f"    URL: {doc.url}\n"
                f"    内容: {content}"
            )
            blocks.append(block)
        return "\n\n---\n\n".join(blocks)

    @staticmethod
    def _parse_discovery_response(
        content: str,
        *,
        model: str = "",
        tokens_used: int = 0,
    ) -> DiscoveryResult:
        """解析 LLM 返回的 JSON,构造 DiscoveryResult(含证据链字段)。"""
        import json
        import re

        # 尝试直接解析
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # 尝试从文本中提取 JSON 块
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return DiscoveryResult(
                        candidates=[],
                        selected_focus="",
                        model=model,
                        tokens_used=tokens_used,
                    )
            else:
                return DiscoveryResult(
                    candidates=[],
                    selected_focus="",
                    model=model,
                    tokens_used=tokens_used,
                )

        candidates_data = data.get("candidates", [])
        candidates = [
            DiscoveryCandidate(
                industry=c.get("industry", ""),
                confidence=float(c.get("confidence", 0.5)),
                reason=c.get("reason", ""),
                evidence_urls=_safe_str_list(c.get("evidence_urls", [])),
                related_keywords=_safe_str_list(c.get("related_keywords", [])),
                supporting_documents=_safe_str_list(c.get("supporting_documents", [])),
            )
            for c in candidates_data
        ]
        selected_focus = data.get("selected_focus", "")
        if not selected_focus and candidates:
            # 取置信度最高的
            best = max(candidates, key=lambda c: c.confidence)
            selected_focus = best.industry

        return DiscoveryResult(
            candidates=candidates,
            selected_focus=selected_focus,
            model=model,
            tokens_used=tokens_used,
        )

    @staticmethod
    def _fallback_discovery(county: CountyInfo) -> DiscoveryResult:
        """发现失败时的降级:返回通用候选(无证据链,需用户手动确认)。"""
        return DiscoveryResult(
            candidates=[
                DiscoveryCandidate(
                    industry="特色农业",
                    confidence=0.4,
                    reason="县域经济通常以农业为基础(降级推断,无具体数据支撑)",
                    evidence_urls=[],
                    related_keywords=["农业", "特色", "县域"],
                    supporting_documents=[],
                ),
                DiscoveryCandidate(
                    industry="乡村旅游",
                    confidence=0.4,
                    reason="县域常见产业方向(降级推断,无具体数据支撑)",
                    evidence_urls=[],
                    related_keywords=["旅游", "乡村", "文旅"],
                    supporting_documents=[],
                ),
                DiscoveryCandidate(
                    industry="先进制造业",
                    confidence=0.3,
                    reason="需根据具体县情判断(降级推断,无具体数据支撑)",
                    evidence_urls=[],
                    related_keywords=["制造业", "工业园区"],
                    supporting_documents=[],
                ),
            ],
            selected_focus="",
            model="fallback",
            tokens_used=0,
        )

    # ---- 内部方法 ----

    def _run_single_task(
        self,
        task: str,
        county: CountyInfo,
        focus: str,
        date_str: str,
        data_text: str,
    ) -> AnalysisResult:
        """执行单个分析任务,失败时降级为占位结果。"""
        config = self.TASK_CONFIGS.get(task)
        if config is None:
            # 未知 task:用通用 fallback
            logger.warning("未知分析任务(使用通用 fallback) | task=%s", task)
            config = TaskConfig(
                template_name=None,
                fallback_prompt=(
                    "## 研究对象\n- 县名: {{ county }}\n- 方向: {{ focus }}\n- 日期: {{ date }}\n\n"
                    "## 参考数据\n```\n{{ processed_data }}\n```\n\n"
                    "## 任务\n请分析该县该产业的 {{ task }}。"
                ),
                description=task,
            )

        prompt = self._build_prompt_from_config(
            config=config,
            county=county.display(),
            focus=focus,
            date=date_str,
            processed_data=data_text,
            analysis_content=data_text,
            task=task,
        )

        logger.info("调用 LLM 分析任务 | task=%s | desc=%s", task, config.description)
        try:
            resp = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=self._settings.llm.temperature,
                max_tokens=self._settings.llm.max_tokens,
            )
            logger.info(
                "分析任务完成 | task=%s | model=%s | tokens=%d",
                task, resp.model, resp.total_tokens,
            )
            return AnalysisResult(
                task=task,
                content=resp.content,
                model=resp.model,
                tokens_used=resp.total_tokens,
            )
        except Exception as e:
            logger.warning(
                "分析任务失败(降级为占位) | task=%s | err=%s",
                task, e, exc_info=True,
            )
            if self._settings.pipeline.fail_fast:
                raise
            return AnalysisResult(
                task=task,
                content=f"> 【该分析任务暂未完成: {e}】",
                model="failed",
                tokens_used=0,
            )

    def _build_prompt_from_config(
        self,
        config: TaskConfig,
        **context: object,
    ) -> str:
        """根据 TaskConfig 构建 prompt:优先用模板文件,否则用 fallback 字符串。"""
        if config.template_name and self._prompt_loader.has_template(config.template_name):
            logger.debug("使用模板文件 | template=%s", config.template_name)
            return self._prompt_loader.render(config.template_name, **context)
        logger.debug("使用 fallback prompt | template=%s", config.template_name or "(无)")
        return self._prompt_loader.render_string(config.fallback_prompt, **context)

    @staticmethod
    def _fallback_summary(
        county: CountyInfo, focus: str, analyses: list[AnalysisResult]
    ) -> str:
        """摘要生成失败时的简易降级。"""
        if not analyses:
            return f"本报告针对 {county.display()} {focus} 产业开展初步研究。"
        head = analyses[0].content.splitlines()[:5]
        head_clean = [ln for ln in head if ln.strip() and not ln.strip().startswith("#")]
        text = " ".join(head_clean[:2]) if head_clean else analyses[0].content[:200]
        return (
            f"本报告基于自动采集与分析,对 {county.display()} {focus} 产业进行了研究。\n\n"
            f"{text}"
        )
