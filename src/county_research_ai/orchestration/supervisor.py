"""Chief Research Agent（Supervisor）。

职责：理解研究问题 → 动态拆解 → 选择专业 Agent → 生成并行任务。
它不执行具体检索，也不替专业 Agent 写结论。

LLM 规划失败时使用确定性问题树规划（标记 planner_source=deterministic），
不会伪装成模型决策。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..agents.registry import agent_catalog, specialist_kinds
from ..domain.intelligence import (
    AgentKind,
    CritiqueReport,
    ResearchPlan,
    ResearchTask,
)
from ..llm.structured import StructuredOutputError, parse_json_object
from .question_tree import build_question_tree

logger = logging.getLogger(__name__)

_ALLOWED = set(specialist_kinds())

SYSTEM_PROMPT = """你是县域产业研究平台的首席研究 Agent（Supervisor）。

你的职责不是自己写报告，而是：
1. 理解用户的研究问题，拆解为若干可独立执行的研究任务；
2. 根据问题需要动态选择专业 Agent（不是固定顺序、不是每个都选）；
3. 为每个任务写清楚目标与可直接用于搜索的查询词；
4. 只选择确实能贡献答案的 Agent，避免重复劳动。

可用专业 Agent：
{catalog}

规则：
- 不得选择 critic / report / supervisor / opportunity（这些由系统在后续阶段调度）。
- 单轮最多 {max_specialists} 个任务，每个 Agent 最多 1 个任务。
- 每个任务必须包含 agent / objective / queries（1-3 条）。
- objective 要具体到"研究什么、判断什么"，不要写"研究一下 XX"。
- queries 必须包含县域名与产业关键词，避免泛泛的"产业现状"。
- 如果是补充轮次（round > 1），只针对 Critic 指出的缺口，不要重复已完成的全面研究。
- 不得在计划中编造事实或结论。

只输出 JSON：
{{
  "research_question": "...",
  "objectives": ["..."],
  "rationale": "为什么选择这些 Agent",
  "tasks": [
    {{"agent": "industry", "objective": "...", "queries": ["..."], "priority": 1}}
  ]
}}"""


class Supervisor:
    def __init__(
        self,
        llm: Any,
        *,
        max_specialists: int = 6,
        max_rounds: int = 2,
        max_followup_queries: int = 4,
    ) -> None:
        self._llm = llm
        self.max_specialists = max_specialists
        self.max_rounds = max_rounds
        self.max_followup_queries = max_followup_queries

    def plan(
        self,
        *,
        county: str,
        focus: str,
        research_question: str = "",
        objectives: list[str] | None = None,
        round_no: int = 1,
        followup_queries: list[str] | None = None,
        prior_results: list[dict[str, Any]] | None = None,
        critique: CritiqueReport | None = None,
    ) -> ResearchPlan:
        objectives = objectives or []
        tree = build_question_tree(county, focus, objectives)
        question = research_question or tree.root
        followups = (followup_queries or [])[: self.max_followup_queries]

        if self._llm is not None:
            try:
                plan = self._llm_plan(
                    county=county,
                    focus=focus,
                    question=question,
                    objectives=objectives,
                    round_no=round_no,
                    followups=followups,
                    prior_results=prior_results or [],
                    critique=critique,
                    tree=tree,
                )
                if plan is not None and plan.tasks:
                    return plan
            except Exception as exc:  # noqa: BLE001
                logger.warning("Supervisor LLM 规划失败，使用确定性规划 | err=%s", exc)

        return self._deterministic_plan(
            county=county,
            focus=focus,
            question=question,
            objectives=objectives,
            round_no=round_no,
            followups=followups,
            tree=tree,
        )

    # ---- LLM 规划 ----

    def _llm_plan(
        self,
        *,
        county: str,
        focus: str,
        question: str,
        objectives: list[str],
        round_no: int,
        followups: list[str],
        prior_results: list[dict[str, Any]],
        critique: CritiqueReport | None,
        tree: Any,
    ) -> ResearchPlan | None:
        catalog_lines = "\n".join(
            f"- {item['kind']}: {item['name']} —— {item['description']}"
            for item in agent_catalog()
        )
        system = SYSTEM_PROMPT.format(
            catalog=catalog_lines, max_specialists=self.max_specialists
        )
        prior_text = ""
        for result in prior_results[-10:]:
            prior_text += (
                f"\n## {result.get('agent')}（置信度 {result.get('confidence')}）\n"
                f"{str(result.get('summary', ''))[:500]}\n"
                f"gaps: {'；'.join(map(str, result.get('gaps', [])[:3]))[:400]}"
            )
        critique_text = critique.model_dump_json()[:2500] if critique else "（无）"
        user = (
            f"县域：{county}\n产业方向：{focus or '待发现'}\n"
            f"研究问题：{question}\n轮次：{round_no} / {self.max_rounds}\n"
            f"用户指定目标：{json.dumps(objectives, ensure_ascii=False)}\n\n"
            f"问题树建议（可裁剪、可重组）：\n"
            + "\n".join(f"- [{b.agent.value}] {b.question}" for b in tree.branches)
            + f"\n\n上一轮 Agent 结果（摘要）：{prior_text or '（无）'}"
            + f"\n\nCritic 审计：{critique_text}"
            + f"\n\nCritic 补充检索建议：{json.dumps(followups, ensure_ascii=False)}"
            + "\n\n请输出本轮研究计划 JSON。"
        )
        assert self._llm is not None
        response = self._llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            max_tokens=2000,
        )
        try:
            data = parse_json_object(response.content)
        except StructuredOutputError as exc:
            logger.info("Supervisor JSON 解析失败：%s", exc)
            return None
        tasks = self._parse_tasks(data.get("tasks"), round_no=round_no)
        if not tasks:
            return None
        return ResearchPlan(
            research_question=str(data.get("research_question") or question)[:400],
            objectives=[str(o)[:300] for o in data.get("objectives", []) or objectives][:10],
            tasks=tasks,
            rationale=str(data.get("rationale", ""))[:1000],
            round=round_no,
            planner_source="llm",
        )

    def _parse_tasks(self, raw: Any, *, round_no: int) -> list[ResearchTask]:
        if not isinstance(raw, list):
            return []
        tasks: list[ResearchTask] = []
        seen: set[AgentKind] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                kind = AgentKind(str(item.get("agent", "")).strip().lower())
            except ValueError:
                continue
            if kind not in _ALLOWED or kind in seen:
                continue
            objective = str(item.get("objective", "")).strip()
            if not objective:
                continue
            queries = [
                str(q).strip()
                for q in item.get("queries", []) or []
                if str(q).strip()
            ][:4]
            try:
                priority = int(item.get("priority", 3))
            except (TypeError, ValueError):
                priority = 3
            seen.add(kind)
            tasks.append(
                ResearchTask(
                    task_id=f"r{round_no}-{kind.value}-{len(tasks) + 1}",
                    agent=kind,
                    objective=objective[:500],
                    queries=queries,
                    priority=max(1, min(priority, 5)),
                    round=round_no,
                    parent_gap=str(item.get("parent_gap", ""))[:200],
                )
            )
            if len(tasks) >= self.max_specialists:
                break
        return tasks

    # ---- 确定性规划 ----

    def _deterministic_plan(
        self,
        *,
        county: str,
        focus: str,
        question: str,
        objectives: list[str],
        round_no: int,
        followups: list[str],
        tree: Any,
    ) -> ResearchPlan:
        if round_no <= 1:
            tasks = tree.default_tasks(round_no=round_no, limit=self.max_specialists)
            rationale = (
                "确定性规划：首轮按问题树覆盖产业、宏观、企业、政策、载体、创新与定量维度，"
                f"最多 {self.max_specialists} 个并行任务。"
            )
        else:
            tasks = _tasks_from_followups(
                followups, county=county, focus=focus, round_no=round_no,
                limit=self.max_specialists,
            )
            rationale = (
                "确定性规划：根据 Critic 的补充检索建议，把查询分配给对应专业 Agent，"
                "只补齐缺口，不重复全面研究。"
            )
        return ResearchPlan(
            research_question=question,
            objectives=objectives or tree.objectives(),
            tasks=tasks,
            rationale=rationale,
            round=round_no,
            planner_source="deterministic",
        )


_HINTS: dict[AgentKind, tuple[str, ...]] = {
    AgentKind.POLICY: ("政策", "规划", "补贴", "扶持", "税收", "人才", "实施方案", "意见"),
    AgentKind.INNOVATION: ("专利", "研发", "技术", "创新", "实验室", "科研", "产学研"),
    AgentKind.ENTERPRISE: ("企业", "公司", "龙头", "规上", "专精特新", "供应链", "配套"),
    AgentKind.GEO: ("园区", "开发区", "基地", "交通", "区位", "土地", "港口"),
    AgentKind.MACRO: ("GDP", "生产总值", "统计", "人口", "财政", "增长", "收入"),
    AgentKind.QUANTITATIVE: ("区位熵", "集中度", "HHI", "CR", "产值", "增加值", "营收"),
    AgentKind.INDUSTRY: ("产业链", "集群", "环节", "上下游", "产业结构"),
}


def _agent_for_query(query: str) -> AgentKind:
    best = AgentKind.INDUSTRY
    best_score = 0
    for kind, hints in _HINTS.items():
        score = sum(1 for hint in hints if hint in query)
        if score > best_score:
            best = kind
            best_score = score
    return best


def _tasks_from_followups(
    queries: list[str],
    *,
    county: str,
    focus: str,
    round_no: int,
    limit: int,
) -> list[ResearchTask]:
    grouped: dict[AgentKind, list[str]] = {}
    for query in queries:
        if not query.strip():
            continue
        kind = _agent_for_query(query)
        grouped.setdefault(kind, []).append(query.strip())
    tasks: list[ResearchTask] = []
    for kind, items in grouped.items():
        objective = (
            f"针对上一轮证据缺口补充研究：{items[0][:120]}"
            if items
            else f"补充研究{county}{focus or '产业'}的证据缺口"
        )
        tasks.append(
            ResearchTask(
                task_id=f"r{round_no}-{kind.value}-{len(tasks) + 1}",
                agent=kind,
                objective=objective,
                queries=items[:4],
                priority=1,
                round=round_no,
                parent_gap=items[0][:200] if items else "",
            )
        )
        if len(tasks) >= limit:
            break
    return tasks


__all__ = ["SYSTEM_PROMPT", "Supervisor", "_agent_for_query"]
