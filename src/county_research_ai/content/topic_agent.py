"""选题代理:从本地研究数据库中发现有传播价值的研究案例。

输入: 本地 reports/ 目录(或空,自动扫描)
输出: Top N 选题候选列表

设计要点:
    - 第一版不联网,仅基于已有研究报告数据库
    - 评价指标:历史反差度、产业代表性、数据丰富度
    - 输出 Top N 选题供创作者参考
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT, Settings, get_settings
from ..llm.base import LLMClient
from ..llm.client import OpenAICompatibleClient
from ..llm.prompt_loader import PromptLoader
from ..models import TopicCandidate
from .templates import _TaskConfig, _parse_json_lenient, _safe_str_list

logger = logging.getLogger(__name__)


class TopicAgent:
    """选题发现代理。

    Usage:
        agent = TopicAgent()
        candidates = agent.discover(top_n=10)
        # candidates: list[TopicCandidate]
    """

    TOPIC_CONFIG = _TaskConfig(
        template_name="topic_selection",
        fallback_prompt=(
            "## 县名\n{{ county }}\n\n"
            "## 研究报告摘要\n```\n{{ report_excerpt }}\n```\n\n"
            "## 任务\n评估该县产业研究案例的传播价值。\n"
            "要求:\n"
            "1. 评分标准:历史反差度(0-40分)、产业代表性(0-30分)、数据丰富度(0-30分)\n"
            "2. 提炼历史反差、兴衰模式、关键数据亮点\n"
            "3. 输出严格 JSON: {county, core_industry, historical_contrast, "
            "rise_fall_pattern, key_data:[], score, reason}\n"
            "只输出 JSON。"
        ),
        description="选题评估",
    )

    # 报告摘要截断长度(防止超出 LLM 上下文)
    _MAX_EXCERPT_CHARS = 800

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt_loader: PromptLoader | None = None,
        settings: Settings | None = None,
        reports_dir: Path | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._llm = llm or OpenAICompatibleClient(settings=self._settings)
        self._prompt_loader = prompt_loader or PromptLoader(settings=self._settings)
        self._reports_dir = reports_dir or PROJECT_ROOT / "reports"

    # ---- 公开入口 ----

    def discover(self, *, top_n: int = 10) -> list[TopicCandidate]:
        """从本地研究数据库发现选题候选。

        Args:
            top_n: 返回前 N 个候选(默认 10)

        Returns:
            TopicCandidate 列表(按 score 降序);失败或无报告时返回空列表
        """
        # 1. 扫描本地报告
        report_files = self._scan_reports()
        if not report_files:
            logger.warning("未找到研究报告 | 目录=%s", self._reports_dir)
            return []

        logger.info("发现 %d 份研究报告", len(report_files))

        # 2. 逐个评估
        candidates: list[TopicCandidate] = []
        for report_path in report_files:
            try:
                candidate = self._evaluate_report(report_path)
                if candidate and candidate.score > 0:
                    candidates.append(candidate)
            except Exception as e:
                logger.error("报告评估失败 | 路径=%s | error=%s", report_path, e, exc_info=True)
                continue

        # 3. 排序并返回 Top N
        candidates.sort(key=lambda c: c.score, reverse=True)
        top_candidates = candidates[:top_n]

        logger.info("选题发现完成 | 总候选=%d | Top%d 已筛选", len(candidates), top_n)
        return top_candidates

    # ---- 内部方法 ----

    def _scan_reports(self) -> list[Path]:
        """扫描本地 reports/ 目录,返回所有 .md 文件路径。"""
        if not self._reports_dir.exists():
            logger.warning("报告目录不存在 | 路径=%s", self._reports_dir)
            return []

        # 扫描所有 Markdown 文件
        report_files = list(self._reports_dir.glob("*.md"))
        # 按修改时间降序(最新报告优先)
        report_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return report_files

    def _evaluate_report(self, report_path: Path) -> TopicCandidate | None:
        """评估单个研究报告的传播价值。"""
        # 读取报告摘要(前 800 字)
        try:
            report_text = report_path.read_text(encoding="utf-8")
            report_excerpt = report_text[: self._MAX_EXCERPT_CHARS]
        except Exception as e:
            logger.error("报告读取失败 | 路径=%s | error=%s", report_path, e)
            return None

        # 从文件名提取县名(格式: {县名}_{方向}_{日期}.md 或 {县名}_兴衰规律_{日期}.md)
        county = self._extract_county_from_filename(report_path.name)
        if not county:
            logger.warning("县名提取失败 | 文件名=%s", report_path.name)
            return None

        # 调用 LLM 评估
        resp = self._run_task(
            config=self.TOPIC_CONFIG,
            county=county,
            report_excerpt=report_excerpt,
        )
        if resp is None:
            return None

        data = _parse_json_lenient(resp.content)
        if not data:
            logger.warning("选题评估解析失败 | 县=%s | raw_len=%d", county, len(resp.content))
            return None

        candidate = TopicCandidate(
            county=str(data.get("county", county)),
            core_industry=str(data.get("core_industry", "")),
            historical_contrast=str(data.get("historical_contrast", "")),
            rise_fall_pattern=str(data.get("rise_fall_pattern", "")),
            key_data=_safe_str_list(data.get("key_data", [])),
            report_path=str(report_path),
            score=float(data.get("score", 0.0)),
            reason=str(data.get("reason", "")),
        )
        logger.info("选题评估完成 | 县=%s | 评分=%.1f", county, candidate.score)
        return candidate

    def _extract_county_from_filename(self, filename: str) -> str:
        """从报告文件名提取县名。

        支持格式:
            - {县名}_{方向}_{日期}.md (如 "信丰县_电子信息产业_20260806.md")
            - {县名}_兴衰规律_{日期}.md (如 "鹤岗市_兴衰规律_20260806.md")
            - {县名}_长周期兴衰史_{日期}.md (如 "信丰县_长周期兴衰史_20260806.md")
        """
        # 去掉 .md 后缀
        stem = filename.replace(".md", "")
        # 分割下划线
        parts = stem.split("_")
        if parts:
            return parts[0]
        return ""

    def _run_task(self, config: _TaskConfig, **context: Any):
        """执行单个任务,返回 LLMResponse;失败时按 fail_fast 决策。"""
        prompt = self._build_prompt_from_config(config=config, **context)
        try:
            resp = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=self._settings.llm.temperature,
            )
            return resp
        except Exception as e:
            logger.error(
                "选题评估 LLM 失败 | template=%s | error=%s",
                config.template_name, e, exc_info=True,
            )
            return None

    def _build_prompt_from_config(self, config: _TaskConfig, **context: Any) -> str:
        """从配置渲染提示词(优先模板,fallback 兜底)。"""
        try:
            return self._prompt_loader.render(config.template_name, **context)
        except Exception as e:
            logger.warning(
                "提示词模板加载失败(使用 fallback) | template=%s | error=%s",
                config.template_name, e,
            )
            return config.fallback_prompt