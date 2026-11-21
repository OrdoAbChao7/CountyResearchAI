"""LangGraph 节点实现。

每个节点只做一件事；业务能力来自 services 与专业 Agent，
Supervisor 节点不承载检索/分析/写作逻辑。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from ..agents.base import AgentContext
from ..agents.critic.agent import CriticAgent
from ..agents.registry import build_specialist
from ..agents.report.agent import ReportAgent
from ..domain.events import EventType
from ..domain.intelligence import (
    AgentKind,
    AgentResult,
    CritiqueReport,
    IntelligenceReport,
    OpportunityCandidate,
    ResearchTask,
    VerificationStatus,
)
from ..models import CountyInfo, RawDoc
from ..services.graph_builder import seed_core_graph
from .artifacts import RunArtifacts
from .question_tree import build_question_tree
from .services import OrchestrationServices
from .state import ResearchState, SpecialistState
from .supervisor import Supervisor

logger = logging.getLogger(__name__)


# ===== 配置访问 =====

def _configurable(config: RunnableConfig | None) -> dict[str, Any]:
    if not config:
        return {}
    return dict(config.get("configurable") or {})


def _services(config: RunnableConfig) -> OrchestrationServices:
    services = _configurable(config).get("services")
    if services is None:
        raise RuntimeError("orchestration services missing from runnable config")
    return services


def _context(config: RunnableConfig) -> AgentContext:
    context = _configurable(config).get("context")
    if context is None:
        raise RuntimeError("agent context missing from runnable config")
    return context


def _artifacts(config: RunnableConfig) -> RunArtifacts | None:
    return _configurable(config).get("artifacts")


def _sync_artifacts(config: RunnableConfig) -> None:
    artifacts = _artifacts(config)
    if artifacts is None:
        return
    context = _context(config)
    try:
        artifacts.save_docs(context.raw_docs)
        artifacts.save_evidence(context.evidence)
    except Exception as exc:  # noqa: BLE001
        logger.warning("运行产物持久化失败（不影响研究） | err=%s", exc)


# ===== 启动采集 =====

def intake_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    services = _services(config)
    context = _context(config)
    context.emit(EventType.NODE_STARTED, "开始初始资料采集与证据抽取", node="intake")
    county = str(state.get("county", "")).strip()
    focus = str(state.get("focus", "")).strip()
    mode = str(state.get("mode", "snapshot"))
    degraded = bool(state.get("degraded", False))
    if not county:
        return {
            "status": "failed",
            "error": "county is required",
            "degraded": True,
            "progress": 0.05,
        }

    outcome = services.search.collect(
        county,
        focus,
        mode=mode,
        limit=max(1, min(services.settings.search.max_results, 20)),
    )
    docs = list(outcome.docs)
    if outcome.degraded:
        degraded = True
        context.emit(
            EventType.NOTICE,
            f"搜索服务降级：{outcome.error or 'provider unavailable'}",
            node="intake",
            degraded=True,
        )

    county_info = CountyInfo.from_name(county)
    if not focus and docs:
        try:
            discovery = services.discovery.discover(county_info, docs)
            if discovery.selected_focus:
                focus = discovery.selected_focus
                context.focus = focus
                context.emit(
                    EventType.NODE_COMPLETED,
                    f"自动发现产业方向：{focus}",
                    node="intake",
                    focus=focus,
                    candidates=[c.name for c in discovery.candidates[:5]],
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("产业方向发现失败 | err=%s", exc)

    usable: list[RawDoc] = docs
    if docs:
        try:
            processed = services.documents.process(
                docs,
                county=county_info,
                focus=focus,
                use_cache=services.settings.cache.enabled,
            )
            if processed.docs:
                usable = processed.docs
        except Exception as exc:  # noqa: BLE001
            logger.warning("文档清洗失败，使用原始资料 | err=%s", exc)
            degraded = True
        services.documents.archive_raw(county, docs)
        context.add_docs(usable)
        context.evidence.ingest(usable, county=county, focus=focus)
        _sync_artifacts(config)

    evidence_count = len(context.evidence.all())
    tree = build_question_tree(county, focus, state.get("objectives") or [])
    context.round = 1
    context.emit(
        EventType.NODE_COMPLETED,
        f"初始采集完成：{len(usable)} 篇资料、{evidence_count} 条证据"
        + (f"；产业方向：{focus}" if focus else ""),
        node="intake",
        documents=len(usable),
        evidence=evidence_count,
        degraded=degraded,
    )
    return {
        "focus": focus,
        "research_question": state.get("research_question") or tree.root,
        "evidence_count": evidence_count,
        "degraded": degraded,
        "progress": 0.1,
    }


# ===== Supervisor =====

def supervise_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    services = _services(config)
    context = _context(config)
    round_no = int(state.get("round", 0) or 0) + 1
    critique_raw = state.get("critique")
    critique = None
    if critique_raw:
        try:
            critique = CritiqueReport.model_validate(critique_raw)
        except Exception:  # noqa: BLE001
            critique = None
    supervisor = Supervisor(
        services.agents_llm,
        max_specialists=services.settings.agents.max_specialists,
        max_rounds=services.settings.agents.max_rounds,
        max_followup_queries=services.settings.agents.max_followup_queries,
    )
    plan = supervisor.plan(
        county=state.get("county", ""),
        focus=state.get("focus", ""),
        research_question=state.get("research_question", ""),
        objectives=state.get("objectives") or [],
        round_no=round_no,
        followup_queries=state.get("followup_queries") or [],
        prior_results=state.get("results") or [],
        critique=critique,
    )
    context.round = round_no
    context.emit(
        EventType.PLAN_CREATED,
        f"第 {round_no} 轮计划：{len(plan.tasks)} 个专业任务（{plan.planner_source}）",
        node="supervise",
        round=round_no,
        agents=[t.agent.value for t in plan.tasks],
        rationale=plan.rationale[:500],
        planner_source=plan.planner_source,
    )
    return {
        "round": round_no,
        "plan": plan.model_dump(mode="json"),
        "tasks": [task.model_dump(mode="json") for task in plan.tasks],
        "research_question": plan.research_question or state.get("research_question", ""),
        "progress": min(0.2 + (round_no - 1) * 0.2, 0.5),
    }


# ===== 专业 Agent 子图节点 =====

def make_agent_node(kind: AgentKind) -> Callable[[SpecialistState, RunnableConfig], dict[str, Any]]:
    def agent_node(state: SpecialistState, config: RunnableConfig) -> dict[str, Any]:
        services = _services(config)
        context = _context(config)
        try:
            task = ResearchTask.model_validate(state["task"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("无效任务被跳过 | err=%s", exc)
            return {"results": []}
        context.round = task.round
        services.graph_evidence.bind(context.evidence)
        try:
            agent = build_specialist(
                kind,
                services.agents_llm,
                services.tools,
                max_steps=services.settings.agents.max_steps,
                max_llm_calls=services.settings.agents.max_llm_calls,
            )
            result = agent.run(task, context)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s Agent 执行失败", kind.value)
            now = datetime.now(timezone.utc)
            result = AgentResult(
                task_id=task.task_id,
                agent=kind,
                summary=f"{kind.value} Agent 执行失败：{exc}",
                confidence=0.0,
                gaps=[str(exc)],
                degraded=True,
                error=str(exc),
                started_at=now,
                finished_at=now,
            )
            context.emit(
                EventType.AGENT_FAILED,
                f"{kind.value} 执行失败：{exc}",
                agent=kind.value,
                task_id=task.task_id,
            )
        _sync_artifacts(config)
        return {"results": [result.model_dump(mode="json")]}

    return agent_node


# ===== 聚合 =====

def aggregate_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    context = _context(config)
    results = _validated_results(state.get("results") or [])
    claims = [claim for result in results for claim in result.claims]
    evidence_ids = list(
        dict.fromkeys(i for result in results for i in result.all_evidence_ids())
    )
    gaps = list(dict.fromkeys(g for result in results for g in result.gaps))
    degraded = any(result.degraded for result in results)
    aggregated = {
        "agents": [result.agent.value for result in results],
        "agent_count": len(results),
        "claim_count": len(claims),
        "evidence_refs": len(evidence_ids),
        "unsupported_claims": sum(1 for c in claims if not c.has_evidence),
        "gaps": gaps[:20],
        "degraded": degraded,
        "rounds": sorted({result.task_id.split("-")[0] for result in results if result.task_id}),
    }
    context.emit(
        EventType.NODE_COMPLETED,
        f"聚合完成：{len(results)} 个 Agent、{len(claims)} 条结论、"
        f"{len(context.evidence.all())} 条证据",
        node="aggregate",
        **aggregated,
    )
    return {
        "aggregated": aggregated,
        "evidence_count": len(context.evidence.all()),
        "degraded": bool(state.get("degraded")) or degraded,
        "progress": min(0.6, 0.25 + 0.1 * len(results)),
    }


# ===== Critic =====

def critic_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    services = _services(config)
    context = _context(config)
    context.round = int(state.get("round", 1) or 1)
    results = _validated_results(state.get("results") or [])
    critic = CriticAgent(services.agents_llm, services.tools)
    report = critic.review(
        context,
        results,
        round_no=context.round,
        max_followups=services.settings.agents.max_followup_queries,
    )
    context.emit(
        EventType.CRITIQUE,
        f"Critic 审计：覆盖率 {report.coverage:.0%}，"
        f"{len(report.findings)} 项发现，"
        + ("结论充分" if report.is_sufficient else "需要补充"),
        node="critic",
        coverage=report.coverage,
        is_sufficient=report.is_sufficient,
        findings=len(report.findings),
        followups=report.followup_queries,
        reasoning=report.reasoning[:500],
    )
    return {
        "critique": report.model_dump(mode="json"),
        "followup_queries": report.followup_queries,
        "progress": min(0.7, float(state.get("progress", 0.5)) + 0.05),
    }


# ===== 补充检索 =====

def supplement_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    services = _services(config)
    context = _context(config)
    queries = [q for q in state.get("followup_queries") or [] if q]
    context.emit(
        EventType.SUPPLEMENT,
        f"执行 {len(queries)} 条补充检索",
        node="supplement",
        queries=queries,
    )
    if not queries:
        return {"supplements": [], "progress": 0.7}
    outcome = services.search.supplemental(
        queries, limit=max(3, min(services.settings.search.max_results, 12))
    )
    docs = list(outcome.docs)
    added = 0
    evidence_added = 0
    if docs:
        try:
            processed = services.documents.process(
                docs,
                county=CountyInfo.from_name(state.get("county", "")),
                focus=state.get("focus", ""),
                use_cache=False,
            )
            docs = processed.docs or docs
        except Exception as exc:  # noqa: BLE001
            logger.warning("补充资料清洗失败 | err=%s", exc)
        added = context.add_docs(docs)
        items = context.evidence.ingest(
            docs, county=state.get("county", ""), focus=state.get("focus", "")
        )
        evidence_added = len(items)
        _sync_artifacts(config)
    context.emit(
        EventType.SUPPLEMENT,
        f"补充检索完成：新增 {added} 篇资料、{evidence_added} 条证据",
        node="supplement",
        documents=added,
        evidence=evidence_added,
        degraded=outcome.degraded,
    )
    return {
        "supplements": [
            {
                "queries": queries,
                "documents": added,
                "evidence": evidence_added,
                "degraded": outcome.degraded,
            }
        ],
        "evidence_count": len(context.evidence.all()),
        "degraded": bool(state.get("degraded")) or outcome.degraded,
        "progress": 0.7,
    }


# ===== 知识图谱 =====

def graph_build_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    services = _services(config)
    context = _context(config)
    context.emit(EventType.NODE_STARTED, "构建产业知识图谱", node="graph_build")
    stats: dict[str, Any] = {}
    try:
        builder = services.new_graph_builder()
        build_stats = builder.build(
            context.raw_docs,
            county=state.get("county", ""),
            focus=state.get("focus", ""),
            evidence_service=context.evidence,
        )
        stats = build_stats.to_dict()
        evidence_ids = context.evidence.evidence_ids(limit=20)
        if evidence_ids:
            seed_core_graph(
                services.graph_store,
                county=state.get("county", ""),
                focus=state.get("focus", ""),
                evidence_ids=evidence_ids,
                evidence_service=context.evidence,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("知识图谱构建失败（研究继续）")
        stats = {"error": str(exc)}
    graph_stats = {**services.graph.stats(), **stats}
    context.emit(
        EventType.GRAPH_BUILT,
        f"知识图谱：{graph_stats.get('entities', 0)} 个实体、"
        f"{graph_stats.get('relations', 0)} 条关系",
        node="graph_build",
        **{k: v for k, v in graph_stats.items() if isinstance(v, (int, float, str))},
    )
    return {
        "graph_stats": graph_stats,
        "progress": min(0.8, float(state.get("progress", 0.7)) + 0.05),
    }


# ===== 机会（Star A Agent 层） =====

def opportunity_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    services = _services(config)
    context = _context(config)
    county = state.get("county", "")
    focus = state.get("focus", "")
    round_no = int(state.get("round", 1) or 1)
    if not focus:
        context.emit(
            EventType.OPPORTUNITIES,
            "未确定产业方向，跳过产业链缺口分析",
            node="opportunity",
        )
        return {
            "opportunities": [],
            "opportunity_notes": ["未确定产业方向，无法执行产业链缺口分析。"],
            "progress": 0.85,
        }

    context.emit(EventType.NODE_STARTED, "分析产业链缺口与机会", node="opportunity")
    services.graph_evidence.bind(context.evidence)
    task = ResearchTask(
        task_id=f"r{round_no}-opportunity-1",
        agent=AgentKind.OPPORTUNITY,
        objective=f"基于{focus}产业链结构与本地企业分布，识别缺失环节、弱配套与外部依赖，提出可执行机会。",
        queries=[f"{county}{focus} 产业链 配套 招商"],
        priority=1,
        round=round_no,
    )
    try:
        agent = build_specialist(
            AgentKind.OPPORTUNITY,
            services.agents_llm,
            services.tools,
            max_steps=services.settings.agents.max_steps,
            max_llm_calls=services.settings.agents.max_llm_calls,
        )
        result = agent.run(task, context)
    except Exception as exc:  # noqa: BLE001
        logger.exception("机会 Agent 执行失败，使用缺口雷达基线")
        now = datetime.now(timezone.utc)
        result = AgentResult(
            task_id=task.task_id,
            agent=AgentKind.OPPORTUNITY,
            summary=f"机会 Agent 执行失败：{exc}",
            confidence=0.0,
            gaps=[str(exc)],
            degraded=True,
            error=str(exc),
            started_at=now,
            finished_at=now,
        )

    radar = None
    try:
        radar = services.new_gap_radar(context.evidence).scan(county, focus)
    except Exception as exc:  # noqa: BLE001
        logger.warning("缺口雷达执行失败 | err=%s", exc)

    opportunities = _parse_opportunities(result.findings.get("opportunities", []))
    if radar is not None:
        existing = {(op.title, op.segment) for op in opportunities}
        for candidate in radar.opportunities:
            if (candidate.title, candidate.segment) not in existing:
                opportunities.append(candidate)
        notes = list(radar.notes)
    else:
        notes = ["缺口雷达不可用，机会仅来自 Agent 文本分析。"]
    if result.degraded:
        notes.append("机会 Agent 降级运行，机会主要来自确定性缺口雷达。")
    opportunities.sort(key=lambda op: op.score, reverse=True)
    opportunities = opportunities[:8]
    for idx, opportunity in enumerate(opportunities, start=1):
        if not opportunity.opportunity_id:
            opportunity.opportunity_id = f"{county}-{focus}-op{idx}"
        if opportunity.verification_status == VerificationStatus.VERIFIED:
            # 机会是推断，不允许标记为已验证事实
            opportunity.verification_status = VerificationStatus.PENDING
    _sync_artifacts(config)
    context.emit(
        EventType.OPPORTUNITIES,
        f"识别 {len(opportunities)} 个产业机会",
        node="opportunity",
        count=len(opportunities),
        missing_segments=(radar.missing_segments if radar else []),
        external_dependencies=(radar.external_dependencies if radar else []),
    )
    return {
        "opportunities": [op.model_dump(mode="json") for op in opportunities],
        "opportunity_notes": notes,
        "results": [result.model_dump(mode="json")],
        "progress": 0.85,
    }


# ===== 报告 =====

def report_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    services = _services(config)
    context = _context(config)
    context.emit(EventType.NODE_STARTED, "综合撰写研究报告", node="report")
    results = _validated_results(state.get("results") or [])
    critique = None
    if state.get("critique"):
        try:
            critique = CritiqueReport.model_validate(state["critique"])
        except Exception:  # noqa: BLE001
            critique = None
    opportunities = _parse_opportunities(state.get("opportunities") or [])
    report_agent = ReportAgent(services.agents_llm)
    try:
        summary, sections, top_opportunities, gaps, degraded = report_agent.compose(
            context,
            results,
            research_question=state.get("research_question", ""),
            critique=critique,
            opportunities=opportunities,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("报告生成失败，使用最小报告")
        summary = f"报告综合失败：{exc}"
        sections = []
        top_opportunities = []
        gaps = [str(exc)]
        degraded = True

    report = IntelligenceReport(
        run_id=state.get("run_id", ""),
        county=state.get("county", ""),
        focus=state.get("focus", ""),
        research_question=state.get("research_question", ""),
        executive_summary=summary,
        sections=sections,
        opportunities=opportunities,
        evidence_index=context.evidence.snapshot()[:80],
        gaps=list(dict.fromkeys([*gaps, *(state.get("opportunity_notes") or [])]))[:20],
        agent_summaries={result.agent.value: result.summary for result in results},
        degraded=bool(state.get("degraded")) or degraded,
        model_used=str(getattr(services.settings.llm, "model", "")),
    )
    markdown = services.reports.render_platform(report)
    artifacts = _artifacts(config)
    if artifacts is not None:
        path = artifacts.write_text("report.md", markdown)
        report.report_path = str(path)
        artifacts.write_json("report.json", report.model_dump(mode="json"))
        artifact_opportunities = top_opportunities or [
            op.model_dump(mode="json") for op in opportunities
        ]
        artifacts.write_json("opportunities.json", artifact_opportunities)
    context.emit(
        EventType.REPORT_READY,
        f"报告完成：{len(sections)} 个章节，{len(markdown)} 字符",
        node="report",
        sections=len(sections),
        opportunities=len(opportunities),
        report_path=report.report_path,
        degraded=report.degraded,
    )
    return {
        "report": report.model_dump(mode="json"),
        "progress": 0.95,
    }


def finalize_node(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    context = _context(config)
    failed = state.get("status") == "failed"
    status = "failed" if failed else "completed"
    context.emit(
        EventType.RUN_FAILED if failed else EventType.RUN_COMPLETED,
        "研究运行失败" if failed else "研究运行完成",
        node="finalize",
        status=status,
        evidence=len(context.evidence.all()),
        graph=state.get("graph_stats", {}),
    )
    return {
        "status": status,
        "progress": 1.0,
        "evidence_count": len(context.evidence.all()),
    }


# ===== 辅助 =====

def _validated_results(raw_results: list[dict[str, Any]]) -> list[AgentResult]:
    results: list[AgentResult] = []
    for raw in raw_results:
        try:
            results.append(AgentResult.model_validate(raw))
        except Exception:  # noqa: BLE001
            continue
    return results


def _parse_opportunities(raw_items: Any) -> list[OpportunityCandidate]:
    opportunities: list[OpportunityCandidate] = []
    seen: set[tuple[str, str]] = set()
    if not isinstance(raw_items, list):
        return opportunities
    for raw in raw_items:
        if isinstance(raw, OpportunityCandidate):
            opportunities.append(raw)
            continue
        if not isinstance(raw, dict):
            continue
        try:
            candidate = OpportunityCandidate.model_validate(raw)
        except Exception:  # noqa: BLE001
            continue
        key = (candidate.title, candidate.segment)
        if key in seen:
            continue
        seen.add(key)
        opportunities.append(candidate)
    return opportunities


def report_path_from_state(state: ResearchState) -> Path | None:
    report = state.get("report") or {}
    path = report.get("report_path")
    return Path(path) if path else None


__all__ = [
    "aggregate_node",
    "critic_node",
    "finalize_node",
    "graph_build_node",
    "intake_node",
    "make_agent_node",
    "opportunity_node",
    "report_node",
    "report_path_from_state",
    "supervise_node",
    "supplement_node",
]
