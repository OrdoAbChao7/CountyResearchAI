"""Agent 工具注册表。

工具是 Agent 与 services / Knowledge Graph 之间的唯一通道：
- 搜索类工具自动把资料写入 EvidenceService；
- 图谱类工具只读，默认只返回已验证关系；
- 定量工具只做确定性数学计算。
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..domain.intelligence import VerificationStatus
from ..knowledge_graph.graph_rag.query_engine import GraphQueryResult
from ..models import RawDoc
from .base import AgentContext, ToolObservation, timed

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any], AgentContext], ToolObservation]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    """按 Agent 白名单暴露工具。"""

    def __init__(self, tools: list[AgentTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self, names: tuple[str, ...] | list[str] | None = None) -> list[dict[str, Any]]:
        selected = names or tuple(self._tools)
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for name, tool in self._tools.items()
            if name in selected
        ]

    def execute(
        self, name: str, arguments: dict[str, Any], context: AgentContext
    ) -> ToolObservation:
        tool = self._tools.get(name)
        if tool is None:
            return ToolObservation(tool=name, ok=False, error="tool_not_registered")
        try:
            return timed(lambda: tool.handler(arguments, context))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agent tool failed | tool=%s | err=%s", name, exc, exc_info=True)
            return ToolObservation(tool=name, ok=False, error=str(exc), summary=f"{name} failed")


# ===== 辅助 =====

def _int_arg(arguments: dict[str, Any], key: str, default: int, *, maximum: int = 50) -> int:
    try:
        value = int(arguments.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return []


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        raise ValueError("expected a list of numbers")
    return [float(v) for v in value]


def _doc_brief(doc: RawDoc) -> dict[str, Any]:
    return {
        "title": doc.title,
        "url": doc.url,
        "source": doc.source,
        "domain_type": doc.domain_type,
        "credibility": doc.credibility_score,
        "excerpt": (doc.snippet or doc.content)[:240],
    }


def _ingest(
    context: AgentContext, docs: list[RawDoc], *, source: str
) -> tuple[list[dict[str, Any]], list[str]]:
    added = context.add_docs(docs)
    items = context.evidence.ingest(docs, county=context.county, focus=context.focus)
    evidence_ids = [item.id for item in items]
    context.emit(
        "evidence_ingested",
        f"{source}: 新增 {added} 篇资料、{len(items)} 条证据",
        agent=source,
        docs=added,
        evidence=len(items),
    )
    return [_doc_brief(d) for d in docs[:12]], evidence_ids


def _graph_observation(tool: str, result: GraphQueryResult) -> ToolObservation:
    data = {
        "answer": result.answer,
        "entities": result.entities[:30],
        "relations": result.relations[:40],
        "evidence": result.evidence[:12],
        "notes": result.notes,
    }
    return ToolObservation(
        tool=tool,
        ok=True,
        summary=result.answer[:300] or "图谱查询完成",
        data=data,
        evidence_ids=result.evidence_ids[:40],
    )


def _summarize_evidence(context: AgentContext, limit: int = 40, max_chars: int = 8000) -> str:
    return context.evidence.render_for_prompt(limit=limit, max_chars=max_chars)


# ===== 搜索工具 =====

def _search_web(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    query = str(arguments.get("query", "")).strip()
    if not query:
        return ToolObservation(tool="search_web", ok=False, error="query is required")
    outcome = context.search.search(query, limit=_int_arg(arguments, "limit", 6, maximum=20))
    docs, evidence_ids = _ingest(context, outcome.docs, source="search_web")
    if outcome.degraded and not outcome.docs:
        return ToolObservation(
            tool="search_web",
            ok=False,
            summary="搜索服务不可用且没有返回结果",
            error=outcome.error or "degraded",
            data={"query": query},
        )
    return ToolObservation(
        tool="search_web",
        ok=True,
        summary=f"检索「{query}」返回 {len(outcome.docs)} 篇资料，抽取 {len(evidence_ids)} 条证据",
        data={"query": query, "documents": docs, "provider": outcome.provider,
              "degraded": outcome.degraded},
        evidence_ids=evidence_ids,
    )


def _search_industry(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    county = str(arguments.get("county") or context.county)
    focus = str(arguments.get("focus") or context.focus or "")
    limit = _int_arg(arguments, "limit", 10, maximum=30)
    outcome = context.search.collect(county, focus, limit=limit)
    docs, evidence_ids = _ingest(context, outcome.docs, source="search_industry")
    return ToolObservation(
        tool="search_industry",
        ok=bool(outcome.docs) or not outcome.degraded,
        summary=(
            f"县域定向采集「{county} {focus}」返回 {len(outcome.docs)} 篇资料，"
            f"抽取 {len(evidence_ids)} 条证据"
        ),
        data={"documents": docs, "provider": outcome.provider, "degraded": outcome.degraded},
        evidence_ids=evidence_ids,
        error=outcome.error,
    )


def _search_supplemental(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    queries = _str_list(arguments.get("queries")) or _str_list(arguments.get("query"))
    if not queries:
        return ToolObservation(tool="search_supplemental", ok=False, error="queries required")
    outcome = context.search.supplemental(queries, limit=_int_arg(arguments, "limit", 6, maximum=20))
    docs, evidence_ids = _ingest(context, outcome.docs, source="search_supplemental")
    return ToolObservation(
        tool="search_supplemental",
        ok=True,
        summary=f"补充检索 {len(queries)} 条查询，返回 {len(outcome.docs)} 篇资料",
        data={"queries": queries, "documents": docs, "degraded": outcome.degraded},
        evidence_ids=evidence_ids,
    )


# ===== 证据工具 =====

def _evidence_search(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    keywords = _str_list(arguments.get("keywords")) or _str_list(arguments.get("query"))
    limit = _int_arg(arguments, "limit", 10, maximum=30)
    items = context.evidence.search(
        keywords, topic=str(arguments.get("topic", "")), limit=limit
    )
    return ToolObservation(
        tool="evidence_search",
        ok=True,
        summary=f"证据库匹配到 {len(items)} 条记录",
        data={
            "evidence": [
                {
                    "id": i.id,
                    "claim": i.claim,
                    "title": i.title,
                    "url": i.url,
                    "year": i.year,
                    "credibility": i.credibility_score,
                    "verification_status": i.verification_status,
                }
                for i in items
            ]
        },
        evidence_ids=[i.id for i in items],
    )


def _evidence_summary(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    text = _summarize_evidence(
        context,
        limit=_int_arg(arguments, "limit", 30, maximum=80),
        max_chars=_int_arg(arguments, "max_chars", 8000, maximum=20000),
    )
    return ToolObservation(
        tool="evidence_summary",
        ok=True,
        summary=f"证据库共 {len(context.evidence.all())} 条记录",
        data={"evidence_text": text},
        evidence_ids=context.evidence.evidence_ids(limit=60),
    )


# ===== 图谱工具 =====

def _graph_query(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    question = str(arguments.get("question", "")).strip()
    if not question:
        return ToolObservation(tool="graph_query", ok=False, error="question required")
    result = context.graph.query(question, county=context.county, focus=context.focus)
    return _graph_observation("graph_query", result)


def _graph_enterprise_relations(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    enterprise = str(arguments.get("enterprise") or arguments.get("name") or "").strip()
    if not enterprise:
        return ToolObservation(tool="graph_enterprise_relations", ok=False, error="enterprise required")
    result = context.graph.enterprise_relations(enterprise, county=context.county)
    return _graph_observation("graph_enterprise_relations", result)


def _graph_supply_chain(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    industry = str(arguments.get("industry") or context.focus or "").strip()
    if not industry:
        return ToolObservation(tool="graph_supply_chain", ok=False, error="industry required")
    result = context.graph.supply_chain(
        industry,
        county=context.county,
        direction=str(arguments.get("direction", "both")),
        depth=_int_arg(arguments, "depth", 2, maximum=3),
    )
    return _graph_observation("graph_supply_chain", result)


def _graph_chain_paths(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    source = str(arguments.get("source", "")).strip()
    target = str(arguments.get("target", "")).strip()
    if not source or not target:
        return ToolObservation(tool="graph_chain_paths", ok=False, error="source and target required")
    result = context.graph.chain_paths(source, target, county=context.county)
    return _graph_observation("graph_chain_paths", result)


def _graph_clusters(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    county = str(arguments.get("county") or context.county)
    result = context.graph.clusters(county, industry=str(arguments.get("industry") or context.focus))
    return _graph_observation("graph_clusters", result)


def _graph_park_enterprises(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    park = str(arguments.get("park") or arguments.get("name") or "").strip()
    if not park:
        return ToolObservation(tool="graph_park_enterprises", ok=False, error="park required")
    result = context.graph.park_enterprises(park, county=context.county)
    return _graph_observation("graph_park_enterprises", result)


def _graph_policy_links(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    industry = str(arguments.get("industry") or context.focus or "").strip()
    if not industry:
        return ToolObservation(tool="graph_policy_links", ok=False, error="industry required")
    result = context.graph.policy_industry_links(industry, county=context.county)
    return _graph_observation("graph_policy_links", result)


def _graph_evidence_trace(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    entity_id = str(arguments.get("entity_id", ""))
    relation_id = str(arguments.get("relation_id", ""))
    if not entity_id and not relation_id:
        return ToolObservation(tool="graph_evidence_trace", ok=False, error="entity_id or relation_id required")
    result = context.graph.evidence_trace(entity_id=entity_id, relation_id=relation_id)
    return _graph_observation("graph_evidence_trace", result)


def _graph_multi_hop(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    entity = str(arguments.get("entity") or arguments.get("name") or "").strip()
    if not entity:
        return ToolObservation(tool="graph_multi_hop", ok=False, error="entity required")
    result = context.graph.multi_hop(
        entity, county=context.county, depth=_int_arg(arguments, "depth", 2, maximum=4)
    )
    return _graph_observation("graph_multi_hop", result)


# ===== 定量工具 =====

def _quant_lq(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    result = context.quant.location_quotient(
        float(arguments["local_industry"]),
        float(arguments["local_total"]),
        float(arguments["reference_industry"]),
        float(arguments["reference_total"]),
        industry_name=str(arguments.get("industry_name") or context.focus),
        region_name=str(arguments.get("region_name") or context.county),
    )
    return ToolObservation(
        tool="quant_location_quotient",
        ok=True,
        summary=result.interpretation,
        data={"metric": result.to_dict()},
        evidence_ids=_str_list(arguments.get("evidence_ids")),
    )


def _quant_shift_share(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    data = context.quant.shift_share(
        float(arguments["local_start"]),
        float(arguments["local_end"]),
        float(arguments["reference_start"]),
        float(arguments["reference_end"]),
        reference_industry_start=(
            float(arguments["reference_industry_start"])
            if arguments.get("reference_industry_start") is not None
            else None
        ),
        reference_industry_end=(
            float(arguments["reference_industry_end"])
            if arguments.get("reference_industry_end") is not None
            else None
        ),
        industry_name=str(arguments.get("industry_name") or context.focus),
    )
    return ToolObservation(
        tool="quant_shift_share",
        ok=True,
        summary=str(data.get("interpretation", "shift-share 计算完成")),
        data={"metric": data},
        evidence_ids=_str_list(arguments.get("evidence_ids")),
    )


def _quant_hhi(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    result = context.quant.hhi(
        _float_list(arguments.get("shares")),
        normalize=bool(arguments.get("normalize", False)),
    )
    return ToolObservation(
        tool="quant_hhi",
        ok=True,
        summary=result.interpretation,
        data={"metric": result.to_dict()},
        evidence_ids=_str_list(arguments.get("evidence_ids")),
    )


def _quant_cr_n(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    result = context.quant.cr_n(
        _float_list(arguments.get("shares")), n=_int_arg(arguments, "n", 4, maximum=20)
    )
    return ToolObservation(
        tool="quant_cr_n",
        ok=True,
        summary=result.interpretation,
        data={"metric": result.to_dict()},
        evidence_ids=_str_list(arguments.get("evidence_ids")),
    )


_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(亿元|万元)")


def _quant_from_evidence(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    """从证据中提取同口径产值数值并计算集中度（明确标注为代理指标）。"""
    keywords = _str_list(arguments.get("keywords")) or ["产值"]
    items = context.evidence.search(keywords, limit=_int_arg(arguments, "limit", 20, maximum=40))
    values: list[tuple[str, float, str]] = []
    for item in items:
        match = _VALUE_RE.search(item.claim)
        if match:
            value = float(match.group(1))
            if match.group(2) == "万元":
                value /= 10000
            values.append((item.id, value, item.claim[:80]))
    if len(values) < 2:
        return ToolObservation(
            tool="quant_from_evidence",
            ok=False,
            summary="可用于定量计算的同口径产值证据不足（至少需要 2 条）",
            error="insufficient_numeric_evidence",
            evidence_ids=[v[0] for v in values],
        )
    metric = context.quant.hhi([v[1] for v in values])
    return ToolObservation(
        tool="quant_from_evidence",
        ok=True,
        summary=(
            f"从 {len(values)} 条产值证据计算 HHI={metric.value:.4f}；"
            "注意：这些数值可能来自不同主体/口径，仅作结构代理指标。"
        ),
        data={
            "metric": metric.to_dict(),
            "values": [{"evidence_id": v[0], "value_yi": v[1], "claim": v[2]} for v in values],
            "caveat": "证据数值可能并非同一统计口径，需人工复核后再作为正式结论。",
        },
        evidence_ids=[v[0] for v in values],
    )


# ===== 产业链缺口雷达（Star A） =====

def _gap_radar_scan(arguments: dict[str, Any], context: AgentContext) -> ToolObservation:
    service = context.gap_radar
    if service is None and context.graph_store is not None:
        from ..services.opportunity_service import GapRadarService

        service = GapRadarService(context.graph_store, context.evidence, context.quant)
    if service is None:
        return ToolObservation(
            tool="gap_radar_scan", ok=False, error="graph_store_unavailable"
        )
    county = str(arguments.get("county") or context.county)
    industry = str(arguments.get("industry") or context.focus or "").strip()
    if not industry:
        return ToolObservation(tool="gap_radar_scan", ok=False, error="industry required")
    report = service.scan(county, industry)
    data = report.model_dump(mode="json")
    return ToolObservation(
        tool="gap_radar_scan",
        ok=True,
        summary=(
            f"缺口雷达识别 {len(report.opportunities)} 个机会、"
            f"{len(report.missing_segments)} 个缺失环节、"
            f"{len(report.external_dependencies)} 项外部依赖"
        ),
        data=data,
        evidence_ids=report.evidence_ids[:40],
    )


# ===== 注册表 =====

def build_default_tools() -> ToolRegistry:
    tools = [
        AgentTool("search_web", "执行单条网络检索，并把结果写入证据库",
                  {"query": {"type": "string"}, "limit": {"type": "integer"}}, _search_web),
        AgentTool("search_industry", "按县域+产业方向执行多角度定向采集",
                  {"county": {"type": "string"}, "focus": {"type": "string"},
                   "limit": {"type": "integer"}}, _search_industry),
        AgentTool("search_supplemental", "针对证据缺口执行多条补充检索",
                  {"queries": {"type": "array", "items": {"type": "string"}},
                   "limit": {"type": "integer"}}, _search_supplemental),
        AgentTool("evidence_search", "在运行期证据库中按关键词检索",
                  {"keywords": {"type": "array"}, "topic": {"type": "string"},
                   "limit": {"type": "integer"}}, _evidence_search),
        AgentTool("evidence_summary", "读取证据库摘要（带 Evidence ID）",
                  {"limit": {"type": "integer"}, "max_chars": {"type": "integer"}},
                  _evidence_summary),
        AgentTool("graph_query", "用自然语言查询产业知识图谱（GraphRAG）",
                  {"question": {"type": "string"}}, _graph_query),
        AgentTool("graph_enterprise_relations", "查询企业关系网络",
                  {"enterprise": {"type": "string"}}, _graph_enterprise_relations),
        AgentTool("graph_supply_chain", "查询产业链上下游与环节",
                  {"industry": {"type": "string"}, "direction": {"type": "string"},
                   "depth": {"type": "integer"}}, _graph_supply_chain),
        AgentTool("graph_chain_paths", "查询两个实体间的产业链路径",
                  {"source": {"type": "string"}, "target": {"type": "string"}},
                  _graph_chain_paths),
        AgentTool("graph_clusters", "查询县域产业集群/园区集聚",
                  {"county": {"type": "string"}, "industry": {"type": "string"}},
                  _graph_clusters),
        AgentTool("graph_park_enterprises", "查询园区入驻企业",
                  {"park": {"type": "string"}}, _graph_park_enterprises),
        AgentTool("graph_policy_links", "查询政策与产业的关联",
                  {"industry": {"type": "string"}}, _graph_policy_links),
        AgentTool("graph_evidence_trace", "按实体或关系反向追溯证据",
                  {"entity_id": {"type": "string"}, "relation_id": {"type": "string"}},
                  _graph_evidence_trace),
        AgentTool("graph_multi_hop", "多跳关系检索",
                  {"entity": {"type": "string"}, "depth": {"type": "integer"}},
                  _graph_multi_hop),
        AgentTool("quant_location_quotient", "计算区位熵 LQ（确定性）",
                  {"local_industry": {"type": "number"}, "local_total": {"type": "number"},
                   "reference_industry": {"type": "number"},
                   "reference_total": {"type": "number"},
                   "industry_name": {"type": "string"}, "region_name": {"type": "string"},
                   "evidence_ids": {"type": "array"}}, _quant_lq),
        AgentTool("quant_shift_share", "计算 Shift-Share 三因素分解（确定性）",
                  {"local_start": {"type": "number"}, "local_end": {"type": "number"},
                   "reference_start": {"type": "number"},
                   "reference_end": {"type": "number"},
                   "reference_industry_start": {"type": "number"},
                   "reference_industry_end": {"type": "number"},
                   "industry_name": {"type": "string"},
                   "evidence_ids": {"type": "array"}}, _quant_shift_share),
        AgentTool("quant_hhi", "计算 HHI 市场集中度（确定性）",
                  {"shares": {"type": "array", "items": {"type": "number"}},
                   "normalize": {"type": "boolean"}, "evidence_ids": {"type": "array"}},
                  _quant_hhi),
        AgentTool("quant_cr_n", "计算 CRn 集中度（确定性）",
                  {"shares": {"type": "array", "items": {"type": "number"}},
                   "n": {"type": "integer"}, "evidence_ids": {"type": "array"}},
                  _quant_cr_n),
        AgentTool("quant_from_evidence", "从证据库提取产值并计算结构代理指标",
                  {"keywords": {"type": "array"}, "limit": {"type": "integer"}},
                  _quant_from_evidence),
        AgentTool("gap_radar_scan", "运行产业链缺口雷达（缺失环节/弱配套/外部依赖）",
                  {"county": {"type": "string"}, "industry": {"type": "string"}},
                  _gap_radar_scan),
    ]
    return ToolRegistry(tools)


def tool_catalog() -> list[dict[str, Any]]:
    """供文档/调试使用的工具清单。"""
    return build_default_tools().specs()


__all__ = ["AgentTool", "ToolRegistry", "build_default_tools", "tool_catalog", "VerificationStatus"]
