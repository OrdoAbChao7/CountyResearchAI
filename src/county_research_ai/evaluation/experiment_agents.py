"""不调用 CountyResearchAI 专有研究模块的 A/B 研究器。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..application.context import ResearchContext
from ..domain.modes import normalize_mode
from ..llm.base import LLMResponse
from ..models import RawDoc, ResearchRequest
from .fixed_input import FixedInputPack
from .strict_container import StrictRealContainer


@dataclass(frozen=True)
class ResearchAgentResult:
    report: str
    documents: list[RawDoc]
    usage_known: bool
    metadata: dict[str, Any] = field(default_factory=dict)


class TraditionalSearchResearcher:
    """固定查询、阅读结果、一次综合的传统搜索基线。"""

    def run(
        self,
        *,
        county: str,
        focus: str,
        mode: str,
        llm: Any,
        search: Any,
        output_dir: Path,
        generation_tokens: int = 2048,
        max_results: int = 10,
    ) -> ResearchAgentResult:
        queries = [
            f"{county} {focus} 统计公报 产业现状",
            f"{county} {focus} 龙头企业 产业链",
            f"{county} {focus} 政策 规划 风险",
        ]
        documents = _search_unique(search, queries, max_results=max_results)
        response = llm.chat(
            [{"role": "user", "content": _report_prompt(county, focus, mode, documents, "传统网页检索") }],
            max_tokens=generation_tokens,
        )
        result = ResearchAgentResult(
            report=response.content,
            documents=documents,
            usage_known=_usage_known(response),
            metadata={"queries": queries, "planning_used": False},
        )
        _persist_result(output_dir, result)
        return result


class GeneralPurposeAIResearcher:
    """先自主规划检索词、再综合的通用联网 AI 基线。"""

    def run(
        self,
        *,
        county: str,
        focus: str,
        mode: str,
        llm: Any,
        search: Any,
        output_dir: Path,
        planning_tokens: int = 512,
        generation_tokens: int = 2048,
        max_results: int = 10,
    ) -> ResearchAgentResult:
        planning = llm.chat(
            [{
                "role": "user",
                "content": (
                    f"你是通用联网研究助手。为研究 {county} 的 {focus}（任务模式 {mode}），"
                    "只输出 JSON：{\"queries\":[\"...\"]}，最多 3 个检索词。"
                ),
            }],
            max_tokens=planning_tokens,
        )
        queries = _parse_queries(planning.content) or [
            f"{county} {focus} 统计公报",
            f"{county} {focus} 企业产业链",
        ]
        documents = _search_unique(search, queries[:3], max_results=max_results)
        response = llm.chat(
            [{"role": "user", "content": _report_prompt(county, focus, mode, documents, "通用联网 AI") }],
            max_tokens=generation_tokens,
        )
        result = ResearchAgentResult(
            report=response.content,
            documents=documents,
            usage_known=_usage_known(planning) and _usage_known(response),
            metadata={"queries": queries[:3], "planning_used": bool(_parse_queries(planning.content))},
        )
        _persist_result(output_dir, result)
        return result


class FixedInputResearcher:
    """在不搜索的前提下，使用冻结文档包完成一次独立分析。"""

    def run(
        self,
        *,
        county: str,
        focus: str,
        mode: str,
        documents: list[RawDoc],
        llm: Any,
        search: Any | None,
        output_dir: Path,
        input_pack_id: str,
        input_hash: str,
        generation_tokens: int = 2048,
    ) -> ResearchAgentResult:
        response = llm.chat(
            [{
                "role": "user",
                "content": _report_prompt(
                    county,
                    focus,
                    mode,
                    documents,
                    "固定输入分析研究员",
                ),
            }],
            max_tokens=generation_tokens,
        )
        result = ResearchAgentResult(
            report=response.content,
            documents=list(documents),
            usage_known=_usage_known(response),
            metadata={
                "input_pack_id": input_pack_id,
                "input_hash": input_hash,
                "search_used": False,
            },
        )
        _persist_result(output_dir, result)
        return result


class FixedInputGeneralPurposeAIResearcher:
    """同一冻结资料上的通用 AI 分析基线；规划阶段不执行搜索。"""

    def run(
        self,
        *,
        county: str,
        focus: str,
        mode: str,
        documents: list[RawDoc],
        llm: Any,
        search: Any | None,
        output_dir: Path,
        input_pack_id: str,
        input_hash: str,
        planning_tokens: int = 512,
        generation_tokens: int = 2048,
    ) -> ResearchAgentResult:
        planning = llm.chat(
            [{
                "role": "user",
                "content": (
                    f"为{county}的{focus}固定资料制定分析提纲（模式：{mode}），"
                    "不要检索外部资料，只输出 JSON："
                    '{"angles":["..."]}，最多 4 个分析角度。\n\n'
                    f"资料：{_render_documents(documents)}"
                ),
            }],
            max_tokens=planning_tokens,
        )
        angles = _parse_angles(planning.content)
        final_prompt = _report_prompt(
            county,
            focus,
            mode,
            documents,
            "通用 AI 固定输入分析研究员",
        )
        if angles:
            final_prompt += f"\n\n分析提纲：{json.dumps(angles, ensure_ascii=False)}"
        response = llm.chat(
            [{"role": "user", "content": final_prompt}],
            max_tokens=generation_tokens,
        )
        result = ResearchAgentResult(
            report=response.content,
            documents=list(documents),
            usage_known=_usage_known(planning) and _usage_known(response),
            metadata={
                "input_pack_id": input_pack_id,
                "input_hash": input_hash,
                "planning_used": bool(angles),
                "analysis_angles": angles,
                "search_used": False,
            },
        )
        _persist_result(output_dir, result)
        return result


class CountyResearchAIFixedInputResearcher:
    """通过 CountyResearchAI 真实分析器处理冻结文档，不调用搜索。"""

    def run(
        self,
        *,
        pack: FixedInputPack,
        container: StrictRealContainer,
        output_dir: Path,
    ) -> ResearchAgentResult:
        context = ResearchContext.from_request(
            ResearchRequest(
                county=pack.region,
                focus=pack.focus,
                mode=pack.mode,
                options={"no_cache": True},
            )
        )
        context = context.model_copy(
            update={"raw_docs": list(pack.documents), "focus": pack.focus}
        )
        context = container.app.application.build_evidence(context)
        context = container.app.application.analyze(context)
        handler = container.app.modes.get(normalize_mode(pack.mode))
        rendered = handler.render(context)
        result = ResearchAgentResult(
            report=rendered.markdown,
            documents=list(pack.documents),
            usage_known=bool(
                container.instrumented_llm is not None
                and container.instrumented_llm.usage_known
            ),
            metadata={
                "input_pack_id": pack.pack_id,
                "input_hash": pack.source_hash,
                "search_used": False,
            },
        )
        _persist_result(output_dir, result)
        return result


def _search_unique(search: Any, queries: list[str], *, max_results: int = 10) -> list[RawDoc]:
    documents: list[RawDoc] = []
    seen: set[str] = set()
    for query in queries:
        for document in search.search(query, max_results=max_results):
            key = document.url or document.title
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            documents.append(document)
    return documents


def _render_documents(documents: list[RawDoc]) -> str:
    return "\n\n".join(
        f"[{index}] {doc.title}\nURL: {doc.url}\n{(doc.content or doc.snippet)[:1800]}"
        for index, doc in enumerate(documents, start=1)
    )


def _report_prompt(
    county: str,
    focus: str,
    mode: str,
    documents: list[RawDoc],
    method: str,
) -> str:
    evidence = _render_documents(documents)
    return (
        f"你是{method}。研究对象：{county}；方向：{focus}；模式：{mode}。\n"
        "仅依据下列资料写一份中文研究报告。逐条区分事实、推断和资料缺口，"
        "每个关键事实给出匹配来源，不要编造没有资料支持的数字。\n\n"
        f"资料：\n{evidence or '(没有检索到资料)'}"
    )


def _parse_queries(content: str) -> list[str]:
    try:
        data = json.loads(content)
        queries = data.get("queries", []) if isinstance(data, dict) else data
        if isinstance(queries, list):
            return [str(query).strip() for query in queries if str(query).strip()]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return []


def _parse_angles(content: str) -> list[str]:
    try:
        data = json.loads(content)
        angles = data.get("angles", []) if isinstance(data, dict) else []
        if isinstance(angles, list):
            return [str(angle).strip() for angle in angles if str(angle).strip()][:4]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return []


def _usage_known(response: LLMResponse) -> bool:
    return response.total_tokens > 0 or response.prompt_tokens > 0 or response.completion_tokens > 0


def _persist_result(output_dir: Path, result: ResearchAgentResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.md").write_text(result.report, encoding="utf-8")
    (output_dir / "sources.json").write_text(
        json.dumps(
            [
                {
                    "title": doc.title,
                    "url": doc.url,
                    "content": doc.content,
                    "source": doc.source,
                    "metadata": doc.metadata,
                }
                for doc in result.documents
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
