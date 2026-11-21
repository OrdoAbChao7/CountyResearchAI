"""县域长周期兴衰史分析器(long-history 模式)。

针对县域做**数百年尺度的历史命运分析**,回答 9 个核心问题:
    1. 为什么这个县会形成?
    2. 最初依靠什么地理/资源/交通/行政功能存在?
    3. 传统时代主要经济来源是什么?
    4. 近代受到哪些战争/交通/市场变化影响?
    5. 计划经济时期是否被国营工业/水利/矿山等重新组织?
    6. 改革开放后靠什么发展?
    7. 新世纪为何再兴/停滞/边缘化?
    8. 决定该县长期命运的关键变量是什么?
    9. 属于哪一种县域长周期模型?

设计要点(与 RiseFallAnalyzer 保持一致):
    - 任务 → 模板映射:优先用 prompts/ 下模板,不存在用 fallback
    - 单任务失败不阻断整体(fail_fast=False 时降级为空)
    - JSON 解析容错:```json 代码块 / 纯 JSON / 文本嵌入
    - 长周期模型 10 类 + mixed
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from ..config import Settings, get_settings
from ..domain.research_contracts import EvidenceChunk, EvidencePack, QuestionSlot
from ..evaluation.checkpoints import CheckpointStore
from ..evidence.ledger import EvidenceLedger, build_evidence_ledger
from ..models import (
    CountyInfo,
    CountyLongHistoryAnalysis,
    GeoHistoricalFactor,
    HistoricalPeriod,
    LongHistoryPattern,
    ProcessedData,
)
from .base import LLMClient
from .client import OpenAICompatibleClient
from .prompt_loader import PromptLoader

logger = logging.getLogger(__name__)


def _safe_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]


def _parse_json_lenient(content: str) -> dict | list | None:
    """容错解析 LLM 返回的 JSON(支持数组/对象)。"""
    if not content:
        return None
    text = content.strip()
    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. 剥离 ```json ... ``` 代码块
    fence_match = re.search(r"```(?:json)?\s*([\[\{][\s\S]*?[\]\}])\s*```", text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass
    # 3. 文本中提取首个 {...} 或 [...] 对象
    obj_match = re.search(r"[\[\{][\s\S]*[\]\}]", text)
    if obj_match:
        try:
            return json.loads(obj_match.group())
        except json.JSONDecodeError:
            pass
    return None


@dataclass(frozen=True)
class _TaskConfig:
    template_name: str | None
    fallback_prompt: str
    description: str = ""
    output_type: str = "json"  # "json" / "markdown"


class LongHistoryAnalyzer:
    """县域长周期兴衰史分析器。

    Usage:
        a = LongHistoryAnalyzer()
        result = a.analyze(county=ci, data=processed)
    """

    PERIODS_CONFIG = _TaskConfig(
        template_name="long_history_periods",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:将该县从建县至今划分 4-7 个历史阶段。\n"
            "输出严格 JSON: {periods: [{name, start, end, summary, dominant_logic, key_events: [], evidence: []}]}\n"
            "只输出 JSON。"
        ),
        description="长周期历史阶段划分",
        output_type="json",
    )

    GEO_ORIGIN_CONFIG = _TaskConfig(
        template_name="geo_origin_analysis",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:分析该县形成的 3-6 个地理历史因子。\n"
            "输出严格 JSON: {geo_factors: [{name, description, impact, evidence: []}]}\n"
            "只输出 JSON。"
        ),
        description="建县与地理逻辑分析",
        output_type="json",
    )

    TRADITIONAL_CONFIG = _TaskConfig(
        template_name="traditional_economy",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:分析该县传统时代(1949 前)的经济社会生存方式,600-1200 字,Markdown,小标题。\n"
            "不写招商建议,区分事实与推断([推断])。"
        ),
        description="传统时代生存方式",
        output_type="markdown",
    )

    MODERN_CONFIG = _TaskConfig(
        template_name="modern_shocks",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:分析近代(1840-1949)冲击与变迁,600-1000 字,Markdown,小标题。\n"
            "不写招商建议。"
        ),
        description="近代冲击与变迁",
        output_type="markdown",
    )

    STATE_CONFIG = _TaskConfig(
        template_name="state_period",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:分析计划经济时期(1949-1978)国家再组织,600-1000 字,Markdown,小标题。\n"
            "不写招商建议。"
        ),
        description="计划经济时期再组织",
        output_type="markdown",
    )

    REFORM_CONFIG = _TaskConfig(
        template_name="reform_period",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:分析改革开放前期(1978-2000)产业重塑,600-1000 字,Markdown,小标题。\n"
            "不写招商建议。"
        ),
        description="改革开放产业重塑",
        output_type="markdown",
    )

    CONTEMPORARY_CONFIG = _TaskConfig(
        template_name="contemporary_long_view",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "参考:\n```\n{{ processed_data }}\n```\n\n"
            "任务:长周期视角分析新世纪(2001-至今)发展,600-1000 字,Markdown,小标题。\n"
            "不写招商建议。"
        ),
        description="新世纪长周期视角分析",
        output_type="markdown",
    )

    PATTERN_CONFIG = _TaskConfig(
        template_name="long_history_pattern",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "已完成分析:\n```\n{{ analysis_content }}\n```\n\n"
            "任务:归入 10 种长周期模型之一。\n"
            "输出严格 JSON: {pattern_type, summary, confidence, dominant_variables: [], evidence: []}\n"
            "只输出 JSON。"
        ),
        description="长周期兴衰模型归纳",
        output_type="json",
    )

    SUMMARY_CONFIG = _TaskConfig(
        template_name="long_history_summary",
        fallback_prompt=(
            "县名: {{ county }}\n\n"
            "已完成分析:\n```\n{{ analysis_content }}\n```\n\n"
            "任务:撰写执行摘要(600-900 字),不写招商建议,面向投资者/决策者。"
        ),
        description="长周期执行摘要",
        output_type="markdown",
    )

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt_loader: PromptLoader | None = None,
        settings: Settings | None = None,
        checkpoint_path: Path | str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._llm = llm or OpenAICompatibleClient(settings=self._settings)
        self._prompt_loader = prompt_loader or PromptLoader(settings=self._settings)
        self._checkpoint_store = (
            CheckpointStore(Path(checkpoint_path)) if checkpoint_path is not None else None
        )
        self._checkpoint_config: dict[str, Any] | None = None
        self._checkpoint_results: dict[str, Any] = {}
        self._checkpoint_analysis_date: str | None = None

    def with_checkpoint(self, path: Path | str) -> LongHistoryAnalyzer:
        """Return an analyzer configured to persist and resume one analysis run."""
        return LongHistoryAnalyzer(
            llm=self._llm,
            prompt_loader=self._prompt_loader,
            settings=self._settings,
            checkpoint_path=path,
        )

    # ---- 总入口 ----

    def analyze(self, county: CountyInfo, data: ProcessedData) -> CountyLongHistoryAnalysis:
        """执行长周期兴衰史研究,返回 CountyLongHistoryAnalysis。

        流程: periods → geo_origin → traditional → modern → state → reform
              → contemporary → pattern → summary
        """
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data_text = data.render_for_llm(max_chars=18000)
        county_display = county.display()
        if self._checkpoint_store is not None:
            input_hash = hashlib.sha256(data.model_dump_json().encode("utf-8")).hexdigest()
            self._checkpoint_config = {
                "schema_version": 2,
                "county": county_display,
                "provider": self._settings.llm.provider,
                "model": self._settings.llm.model,
                "temperature": self._settings.llm.temperature,
                "max_tokens": self._settings.llm.max_tokens,
                "input_sha256": input_hash,
                "prompt_sha256": self._prompt_fingerprint(),
            }
            state = self._checkpoint_store.start(
                config=self._checkpoint_config,
                resume=self._checkpoint_store.path.exists(),
            )
            results = state.get("results", {})
            if not isinstance(results, dict):
                raise ValueError("long-history checkpoint results must be an object")
            self._checkpoint_results = results
            checkpoint_date = state.get("analysis_date")
            if not isinstance(checkpoint_date, str) or not checkpoint_date:
                checkpoint_date = date_str
            self._checkpoint_analysis_date = checkpoint_date
            if state.get("analysis_date") != checkpoint_date:
                self._checkpoint_store.save(
                    config=self._checkpoint_config,
                    state={"analysis_date": checkpoint_date, "results": results},
                )
            date_str = checkpoint_date

        logger.info("长周期研究启动 | 县=%s", county_display)
        ledger = build_evidence_ledger(data)
        period_ledger = self._build_period_ledger(ledger)

        # 1. 历史阶段划分
        periods = self._run_checkpointed(
            "periods",
            lambda: self.extract_periods(
                county=county_display, date_str=date_str, data_text=data_text,
            ),
            list[HistoricalPeriod],
        )
        # 2. 建县与地理逻辑
        geo_context, geo_pack = self._history_pack_context(
            data, period_ledger, "地理 建县 区位 河流 交通 行政", "", 6000
        )
        geo_factors = self._run_checkpointed(
            "geo_factors",
            lambda: self.analyze_geo_origin(
                county=county_display, date_str=date_str, data_text=geo_context,
            ),
            list[GeoHistoricalFactor],
        )
        # 3. 传统时代生存方式
        traditional_range = self._resolve_period_for_task(periods, "before 1840")
        traditional_context, traditional_pack = self._history_pack_context(
            data, period_ledger, "传统 农业 手工业 商贸 盐业", traditional_range, 6000
        )
        traditional = self._run_checkpointed(
            "traditional",
            lambda: self.analyze_traditional_economy(
                county=county_display, date_str=date_str, data_text=traditional_context,
            ),
            str,
        )
        # 4. 近代冲击
        modern_range = self._resolve_period_for_task(periods, "1840-1948")
        modern_context, modern_pack = self._history_pack_context(
            data, period_ledger, "近代 战争 铁路 公路 口岸 工业", modern_range, 6000
        )
        modern = self._run_checkpointed(
            "modern",
            lambda: self.analyze_modern_shocks(
                county=county_display, date_str=date_str, data_text=modern_context,
            ),
            str,
        )
        # 5. 计划经济
        state_range = self._resolve_period_for_task(periods, "1949-1978")
        state_context, state_pack = self._history_pack_context(
            data, period_ledger, "计划经济 国营 工厂 水利 矿山 1950 1960 1970", state_range, 6000
        )
        state_period = self._run_checkpointed(
            "state_period",
            lambda: self.analyze_state_period(
                county=county_display, date_str=date_str, data_text=state_context,
            ),
            str,
        )
        # 6. 改革开放
        reform_range = self._resolve_period_for_task(periods, "1978-2000")
        reform_context, reform_pack = self._history_pack_context(
            data, period_ledger, "改革开放 乡镇企业 外资 民营 1980 1990", reform_range, 6000
        )
        reform = self._run_checkpointed(
            "reform",
            lambda: self.analyze_reform_period(
                county=county_display, date_str=date_str, data_text=reform_context,
            ),
            str,
        )
        # 7. 新世纪
        contemporary_range = self._resolve_period_for_task(periods, "2001-至今")
        contemporary_context, contemporary_pack = self._history_pack_context(
            data, period_ledger, "新世纪 产业 转型 发展 2000 2010 2020", contemporary_range, 6000
        )
        contemporary = self._run_checkpointed(
            "contemporary",
            lambda: self.analyze_contemporary_status(
                county=county_display, date_str=date_str, data_text=contemporary_context,
            ),
            str,
        )

        # 8. 长周期模型归纳(输入前 7 项结果)
        pattern_input = self._build_pattern_input(
            periods=periods, geo_factors=geo_factors,
            traditional=traditional, modern=modern,
            state_period=state_period, reform=reform,
            contemporary=contemporary,
        )
        long_pattern = self._run_checkpointed(
            "long_pattern",
            lambda: self.classify_long_history_pattern(
                county=county_display, date_str=date_str, analysis_content=pattern_input,
            ),
            LongHistoryPattern,
        )

        # 9. 执行摘要
        summary_input = self._build_summary_input(
            periods=periods, geo_factors=geo_factors,
            traditional=traditional, modern=modern,
            state_period=state_period, reform=reform,
            contemporary=contemporary, long_pattern=long_pattern,
        )
        summary = self._run_checkpointed(
            "summary",
            lambda: self.generate_summary(
                county=county_display, analysis_content=summary_input,
            ),
            str,
        )

        return CountyLongHistoryAnalysis(
            county=county,
            periods=periods,
            geo_factors=geo_factors,
            traditional_economy=traditional,
            modern_shocks=modern,
            state_period_reorganization=state_period,
            reform_period_transformation=reform,
            contemporary_status=contemporary,
            long_history_pattern=long_pattern,
            summary=summary,
            evidence_packs=[
                geo_pack,
                traditional_pack,
                modern_pack,
                state_pack,
                reform_pack,
                contemporary_pack,
            ],
        )

    def _run_checkpointed(
        self, key: str, operation: Callable[[], Any], result_type: Any
    ) -> Any:
        if self._checkpoint_store is None or self._checkpoint_config is None:
            return operation()
        adapter = TypeAdapter(result_type)
        if key in self._checkpoint_results:
            return adapter.validate_python(self._checkpoint_results[key])
        result = operation()
        self._checkpoint_results[key] = adapter.dump_python(result, mode="json")
        self._checkpoint_store.save(
            config=self._checkpoint_config,
            state={
                "analysis_date": self._checkpoint_analysis_date,
                "results": self._checkpoint_results,
            },
        )
        return result

    def _prompt_fingerprint(self) -> str:
        digest = hashlib.sha256()
        configs = (
            self.PERIODS_CONFIG,
            self.GEO_ORIGIN_CONFIG,
            self.TRADITIONAL_CONFIG,
            self.MODERN_CONFIG,
            self.STATE_CONFIG,
            self.REFORM_CONFIG,
            self.CONTEMPORARY_CONFIG,
            self.PATTERN_CONFIG,
            self.SUMMARY_CONFIG,
        )
        for config in configs:
            digest.update((config.template_name or "").encode("utf-8"))
            digest.update(config.fallback_prompt.encode("utf-8"))
            if config.template_name and self._prompt_loader.has_template(config.template_name):
                template = self._prompt_loader.get_template(config.template_name)
                if template.filename:
                    digest.update(Path(template.filename).read_bytes())
        return digest.hexdigest()

    @staticmethod
    def _build_period_ledger(ledger: EvidenceLedger) -> EvidenceLedger:
        period_ledger = EvidenceLedger()
        derived_by_parent: dict[str, list[EvidenceChunk]] = {}
        for source in ledger.sources.values():
            derived_chunks = []
            for passage_start, passage_end in LongHistoryAnalyzer._sentence_spans(source.content):
                raw_text = source.content[passage_start:passage_end]
                leading = len(raw_text) - len(raw_text.lstrip())
                trailing = len(raw_text.rstrip())
                start = passage_start + leading
                end = passage_start + trailing
                text = source.content[start:end]
                if not text:
                    continue
                parent = next(
                    (
                        chunk
                        for chunk in source.chunks
                        if chunk.start_offset is not None
                        and chunk.end_offset is not None
                        and chunk.start_offset <= start < chunk.end_offset
                    ),
                    None,
                )
                parent_id = parent.chunk_id if parent else ""
                derived_chunks.append(EvidenceChunk(
                    chunk_id=f"{parent_id or source.doc_id}:period:{start}:{end}",
                    document_id=source.doc_id,
                    parent_chunk_id=parent_id,
                    text=text,
                    start_offset=start,
                    end_offset=end,
                    offset_status="exact",
                    year_hints=sorted(set(re.findall(r"(?<!\d)(?:1\d{3}|20\d{2})(?!\d)", text))),
                ))
                if parent_id:
                    derived_by_parent.setdefault(parent_id, []).append(derived_chunks[-1])
            period_ledger.add_source(source.model_copy(update={"chunks": derived_chunks}))
        for claim in ledger.claims.values():
            mapped_chunks = [
                chunk
                for parent_id in claim.evidence_chunk_ids
                for chunk in derived_by_parent.get(parent_id, [])
            ]
            statement = " ".join(claim.statement.split())
            matching_chunks = [
                chunk
                for chunk in mapped_chunks
                if statement and statement in " ".join(chunk.text.split())
            ]
            if not matching_chunks and claim.value and claim.metric_id:
                matching_chunks = [
                    chunk
                    for chunk in mapped_chunks
                    if claim.value in chunk.text and claim.metric_id in chunk.text
                ]
            if not matching_chunks:
                continue
            remapped_claim = claim.model_copy(update={
                "evidence_chunk_ids": [chunk.chunk_id for chunk in matching_chunks],
                "source_ids": [
                    source_id for source_id in claim.source_ids
                    if source_id in period_ledger.sources
                ],
            })
            period_ledger.add_claim(remapped_claim)
        return period_ledger

    @staticmethod
    def _sentence_spans(text: str) -> list[tuple[int, int]]:
        """Split passages without treating decimal points as sentence endings."""
        spans = []
        start = 0
        for index, char in enumerate(text):
            boundary = char in "。！？!?；;\n"
            if char == ".":
                previous_is_digit = index > 0 and text[index - 1].isdigit()
                next_is_digit = index + 1 < len(text) and text[index + 1].isdigit()
                boundary = not (previous_is_digit and next_is_digit)
            if boundary:
                spans.append((start, index + 1))
                start = index + 1
        if start < len(text):
            spans.append((start, len(text)))
        return spans

    @staticmethod
    def _resolve_period_for_task(
        periods: list[HistoricalPeriod], fallback: str
    ) -> str:
        """Narrow a task's evidence window to extracted historical periods."""
        fallback_years = [
            int(year)
            for year in re.findall(r"(?<!\d)(?:1\d{3}|20\d{2})(?!\d)", fallback)
        ]
        if re.search(r"before|prior|之前|以前|前", fallback, re.IGNORECASE):
            task_start, task_end = 1, max(fallback_years, default=1840)
        elif re.search(r"至今|现在|目前|present", fallback, re.IGNORECASE):
            task_start, task_end = min(fallback_years, default=2001), 9999
        elif fallback_years:
            task_start, task_end = min(fallback_years), max(fallback_years)
        else:
            return fallback

        overlapping = []
        for period in periods:
            start_years = re.findall(r"(?<!\d)(?:1\d{3}|20\d{2})(?!\d)", period.start)
            end_years = re.findall(r"(?<!\d)(?:1\d{3}|20\d{2})(?!\d)", period.end)
            if not start_years:
                continue
            start_year = int(start_years[0])
            if end_years:
                end_year = int(end_years[-1])
            elif re.search(r"至今|现在|目前|present", period.end, re.IGNORECASE):
                end_year = task_end
            else:
                end_year = start_year
            clipped_start = max(task_start, start_year)
            clipped_end = min(task_end, end_year)
            if clipped_start <= clipped_end:
                overlapping.append((clipped_start, clipped_end))
        if not overlapping:
            return fallback
        start = min(window[0] for window in overlapping)
        end = max(window[1] for window in overlapping)
        return f"{start}-{end}"

    @staticmethod
    def _history_pack_context(
        data: ProcessedData,
        ledger: EvidenceLedger,
        keywords: str,
        period: str,
        max_chars: int,
    ) -> tuple[str, EvidencePack]:
        terms = [term for term in keywords.split() if not term.isdigit()]
        slot = QuestionSlot(
            slot_id=f"long_history:{period or 'geography'}",
            research_question=f"长周期历史任务：{keywords} {period}".strip(),
            required_metrics=terms,
            region=data.county.name,
            time_period=period,
            budget_chars=max_chars,
        )
        pack = ledger.select_evidence_pack(slot)
        if not pack.selected_chunks:
            return LongHistoryAnalyzer._history_context(data, keywords, max_chars), pack
        rendered = data.model_copy(update={"evidence_pack": pack}).render_for_llm(max_chars)
        return rendered, pack

    @staticmethod
    def _history_context(data: ProcessedData, keywords: str, max_chars: int) -> str:
        """Select a source-diverse, topic-relevant context for a historical subtask."""
        terms = tuple(keywords.split())
        per_document: list[tuple[object, list[tuple[int, str]]]] = []
        for doc in data.docs:
            body = doc.content or doc.snippet
            passages = [
                body[start:end].strip()
                for start, end in LongHistoryAnalyzer._sentence_spans(body)
                if body[start:end].strip()
            ]
            if not passages:
                passages = [doc.snippet or doc.title]
            ranked_passages = sorted(
                ((sum(part.count(term) for term in terms), part) for part in passages),
                key=lambda item: item[0],
                reverse=True,
            )
            per_document.append((doc, ranked_passages))

        candidates = sorted(
            (
                (score, doc_index, passage)
                for doc_index, (_, passages) in enumerate(per_document)
                for score, passage in passages
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        selected: dict[int, list[str]] = {i: [] for i in range(len(per_document))}
        used = 0
        for _, doc_index, passage in candidates:
            doc, _ = per_document[doc_index]
            header_cost = len(f"[{doc.title}]\n来源: {doc.url}\n") if not selected[doc_index] else 0
            separator_cost = 2 if used else 0
            available = max_chars - used - header_cost - separator_cost
            if available > 0:
                excerpt = passage[:available]
                selected[doc_index].append(excerpt)
                used += header_cost + len(excerpt) + separator_cost

        blocks = []
        for index, (doc, _) in enumerate(per_document):
            if selected[index]:
                blocks.append(f"[{doc.title}]\n来源: {doc.url}\n" + "\n".join(selected[index]))
        context = "\n\n".join(blocks)
        if context:
            return context[:max_chars]
        return data.render_for_llm(max_chars=max_chars)

    # ---- 各子任务 ----

    def extract_periods(
        self, *, county: str, date_str: str, data_text: str,
    ) -> list[HistoricalPeriod]:
        resp = self._run_task(
            config=self.PERIODS_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        if resp is None:
            return []
        data = _parse_json_lenient(resp.content)
        if not isinstance(data, dict):
            return []
        raw_periods = data.get("periods", []) if isinstance(data, dict) else []
        periods: list[HistoricalPeriod] = []
        for raw_period in raw_periods:
            periods.append(HistoricalPeriod(
                name=str(raw_period.get("name", "")),
                start=str(raw_period.get("start", "")),
                end=str(raw_period.get("end", "")),
                summary=str(raw_period.get("summary", "")),
                dominant_logic=str(raw_period.get("dominant_logic", "")),
                key_events=_safe_str_list(raw_period.get("key_events", [])),
                evidence=_safe_str_list(raw_period.get("evidence", [])),
            ))
        logger.info("历史阶段划分完成 | 阶段数=%d", len(periods))
        return periods

    def analyze_geo_origin(
        self, *, county: str, date_str: str, data_text: str,
    ) -> list[GeoHistoricalFactor]:
        resp = self._run_task(
            config=self.GEO_ORIGIN_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        if resp is None:
            return []
        data = _parse_json_lenient(resp.content)
        if not isinstance(data, dict):
            return []
        raw_factors = data.get("geo_factors", [])
        factors: list[GeoHistoricalFactor] = []
        for raw_factor in raw_factors:
            factors.append(GeoHistoricalFactor(
                name=str(raw_factor.get("name", "")),
                description=str(raw_factor.get("description", "")),
                impact=str(raw_factor.get("impact", "")),
                evidence=_safe_str_list(raw_factor.get("evidence", [])),
            ))
        logger.info("建县与地理逻辑完成 | 因子数=%d", len(factors))
        return factors

    def analyze_traditional_economy(
        self, *, county: str, date_str: str, data_text: str,
    ) -> str:
        resp = self._run_task(
            config=self.TRADITIONAL_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        return resp.content if resp else "_传统时代生存方式资料不足,需补充县志与地方志。_"

    def analyze_modern_shocks(
        self, *, county: str, date_str: str, data_text: str,
    ) -> str:
        resp = self._run_task(
            config=self.MODERN_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        return resp.content if resp else "_近代冲击与变迁资料不足。_"

    def analyze_state_period(
        self, *, county: str, date_str: str, data_text: str,
    ) -> str:
        resp = self._run_task(
            config=self.STATE_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        return resp.content if resp else "_计划经济时期再组织资料不足。_"

    def analyze_reform_period(
        self, *, county: str, date_str: str, data_text: str,
    ) -> str:
        resp = self._run_task(
            config=self.REFORM_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        return resp.content if resp else "_改革开放产业重塑资料不足。_"

    def analyze_contemporary_status(
        self, *, county: str, date_str: str, data_text: str,
    ) -> str:
        resp = self._run_task(
            config=self.CONTEMPORARY_CONFIG,
            county=county, date=date_str, processed_data=data_text,
        )
        return resp.content if resp else "_新世纪以来发展变化资料不足。_"

    def classify_long_history_pattern(
        self, *, county: str, date_str: str, analysis_content: str,
    ) -> LongHistoryPattern:
        resp = self._run_task(
            config=self.PATTERN_CONFIG,
            county=county, date=date_str, analysis_content=analysis_content,
        )
        if resp is None:
            return LongHistoryPattern()
        data = _parse_json_lenient(resp.content)
        if not isinstance(data, dict):
            return LongHistoryPattern()
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        pattern = LongHistoryPattern(
            pattern_type=str(data.get("pattern_type", "unknown")),
            summary=str(data.get("summary", "")),
            confidence=confidence,
            dominant_variables=_safe_str_list(data.get("dominant_variables", [])),
            evidence=_safe_str_list(data.get("evidence", [])),
        )
        logger.info(
            "长周期模型归纳完成 | type=%s | confidence=%.2f | dominant=%s",
            pattern.pattern_type, pattern.confidence, pattern.dominant_variables,
        )
        return pattern

    def generate_summary(self, *, county: str, analysis_content: str) -> str:
        resp = self._run_task(
            config=self.SUMMARY_CONFIG,
            county=county, date="", analysis_content=analysis_content,
        )
        if resp is None:
            return (
                f"本报告针对 {county} 县域开展长周期兴衰史研究,"
                "覆盖建县逻辑、传统经济、近代冲击、计划经济重塑、"
                "改革开放转型与新世纪变化,并归纳其长周期兴衰模型。"
            )
        return resp.content

    # ---- 内部方法 ----

    def _run_task(self, config: _TaskConfig, **context: object):
        prompt = self._build_prompt_from_config(config=config, **context)
        try:
            resp = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=self._settings.llm.temperature,
                max_tokens=self._settings.llm.max_tokens,
            )
            logger.info(
                "%s 完成 | model=%s | tokens=%d",
                config.description, resp.model, resp.total_tokens,
            )
            return resp
        except Exception as e:
            logger.warning(
                "%s 失败(降级) | err=%s", config.description, e, exc_info=True,
            )
            if self._settings.runtime.fail_fast:
                raise
            return None

    def _build_prompt_from_config(self, config: _TaskConfig, **context: object) -> str:
        if config.template_name and self._prompt_loader.has_template(config.template_name):
            return self._prompt_loader.render(config.template_name, **context)
        return self._prompt_loader.render_string(config.fallback_prompt, **context)

    @staticmethod
    def _build_pattern_input(
        periods: list[HistoricalPeriod],
        geo_factors: list[GeoHistoricalFactor],
        traditional: str, modern: str,
        state_period: str, reform: str, contemporary: str,
    ) -> str:
        blocks: list[str] = []
        if periods:
            p_lines = []
            for period in periods:
                rng = f"{period.start}–{period.end}" if (period.start or period.end) else "(时间不详)"
                logic = f" | 逻辑:{period.dominant_logic}" if period.dominant_logic else ""
                p_lines.append(f"- **{period.name}** ({rng}){logic}\n  {period.summary}")
            blocks.append("## 历史阶段\n" + "\n".join(p_lines))
        if geo_factors:
            g_lines = [f"- {factor.name}: {factor.impact}" for factor in geo_factors]
            blocks.append("## 地理历史因子\n" + "\n".join(g_lines))
        if traditional:
            blocks.append(f"## 传统时代生存方式\n{traditional[:800]}")
        if modern:
            blocks.append(f"## 近代冲击与变迁\n{modern[:600]}")
        if state_period:
            blocks.append(f"## 计划经济时期再组织\n{state_period[:600]}")
        if reform:
            blocks.append(f"## 改革开放产业重塑\n{reform[:600]}")
        if contemporary:
            blocks.append(f"## 新世纪发展变化\n{contemporary[:600]}")
        return "\n\n".join(blocks)

    @staticmethod
    def _build_summary_input(
        periods: list[HistoricalPeriod],
        geo_factors: list[GeoHistoricalFactor],
        traditional: str, modern: str,
        state_period: str, reform: str, contemporary: str,
        long_pattern: LongHistoryPattern,
    ) -> str:
        blocks: list[str] = []
        blocks.append(f"## 长周期模型\n{long_pattern.pattern_type}: {long_pattern.summary}")
        if long_pattern.dominant_variables:
            blocks.append(f"**主导变量**: {', '.join(long_pattern.dominant_variables)}")
        if periods:
            p_lines = [
                f"- {period.name}({period.start}–{period.end}): "
                f"{period.dominant_logic or period.summary[:40]}"
                for period in periods
            ]
            blocks.append("## 历史阶段\n" + "\n".join(p_lines))
        if geo_factors:
            g_lines = [f"- {factor.name}: {factor.impact}" for factor in geo_factors]
            blocks.append("## 地理因子\n" + "\n".join(g_lines))
        sections = [
            ("传统时代", traditional),
            ("近代冲击", modern),
            ("计划经济", state_period),
            ("改革开放", reform),
            ("新世纪", contemporary),
        ]
        for title, content in sections:
            if content and not content.startswith("_"):
                blocks.append(f"## {title}\n{content[:300]}")
        return "\n\n".join(blocks)
