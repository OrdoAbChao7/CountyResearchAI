"""V2 Agent 层测试：有界工具循环、证据约束、Supervisor、Critic、报告。"""
from __future__ import annotations

import json

from county_research_ai.agents import (
    AgentContext,
    CriticAgent,
    ReportAgent,
    ToolObservation,
    agent_catalog,
    build_specialist,
    specialist_kinds,
)
from county_research_ai.agents.report.agent import AGENT_TITLES
from county_research_ai.domain.intelligence import (
    AgentKind,
    AgentResult,
    Claim,
    CritiqueReport,
    ResearchTask,
)
from county_research_ai.orchestration.supervisor import Supervisor
from county_research_ai.services.evidence_service import EvidenceService


def _context(services, sample_docs) -> tuple[AgentContext, EvidenceService]:
    evidence = EvidenceService()
    evidence.ingest(sample_docs, county="安吉县", focus="竹产业")
    context = AgentContext(
        run_id="run-test",
        county="安吉县",
        focus="竹产业",
        evidence=evidence,
        search=services.search,
        documents=services.documents,
        graph=services.graph,
        quant=services.quant,
        analytics=services.analytics,
        graph_store=services.graph_store,
    )
    return context, evidence


def _task(kind: AgentKind = AgentKind.INDUSTRY, task_id: str = "r1-test-1") -> ResearchTask:
    return ResearchTask(
        task_id=task_id,
        agent=kind,
        objective="分析安吉县竹产业链环节与龙头企业",
        queries=["安吉县 竹产业 产业链 龙头"],
    )


class TestSpecialistAgent:
    def test_fallback_claims_are_bound_to_real_evidence(self, v2_container, sample_docs):
        context, evidence = _context(v2_container.services, sample_docs)
        agent = build_specialist(
            AgentKind.INDUSTRY, None, v2_container.services.tools, max_steps=4, max_llm_calls=2
        )
        result = agent.run(_task(), context)

        assert isinstance(result, AgentResult)
        assert result.agent == AgentKind.INDUSTRY
        assert result.degraded is True
        assert result.error == "llm_unavailable"
        assert result.claims
        for claim in result.claims:
            assert claim.evidence_ids
            assert all(evidence.get(i) is not None for i in claim.evidence_ids)

    def test_scripted_llm_calls_tool_then_finishes(self, v2_container, sample_docs, scripted_llm):
        context, evidence = _context(v2_container.services, sample_docs)
        evidence_id = evidence.all()[0].id
        llm = scripted_llm(
            [
                json.dumps(
                    {
                        "action": "tool",
                        "tool": "evidence_search",
                        "arguments": {"keywords": ["产值"]},
                        "reason": "查找产值证据",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "action": "finish",
                        "output": {
                            "summary": "竹产业已有产值证据支撑。",
                            "claims": [
                                {
                                    "text": "安吉县竹产业具备规上企业基础。",
                                    "evidence_ids": [evidence_id],
                                    "confidence": 0.8,
                                }
                            ],
                            "segments": ["加工"],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        agent = build_specialist(
            AgentKind.INDUSTRY, llm, v2_container.services.tools, max_steps=4, max_llm_calls=4
        )
        result = agent.run(_task(), context)

        assert result.degraded is False
        assert result.llm_calls == 2
        assert result.tool_calls == 1
        assert result.claims[0].evidence_ids == [evidence_id]
        assert result.claims[0].verification_status.value == "verified"
        assert result.findings["segments"] == ["加工"]

    def test_tool_not_in_whitelist_is_rejected(self, v2_container, sample_docs, scripted_llm):
        context, evidence = _context(v2_container.services, sample_docs)
        evidence_id = evidence.all()[0].id
        llm = scripted_llm(
            [
                json.dumps(
                    {"action": "tool", "tool": "gap_radar_scan", "arguments": {}},
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "action": "finish",
                        "output": {
                            "summary": "完成",
                            "claims": [
                                {"text": "有证据的结论", "evidence_ids": [evidence_id]}
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        agent = build_specialist(
            AgentKind.INDUSTRY, llm, v2_container.services.tools, max_steps=4, max_llm_calls=4
        )
        result = agent.run(_task(), context)

        assert any("tool_not_allowed" in gap for gap in result.gaps)
        assert result.tool_calls == 0
        assert result.claims

    def test_budget_exhaustion_degrades_with_partial_result(
        self, v2_container, sample_docs, scripted_llm
    ):
        context, _ = _context(v2_container.services, sample_docs)
        llm = scripted_llm(
            [
                json.dumps(
                    {
                        "action": "tool",
                        "tool": "evidence_search",
                        "arguments": {"keywords": ["产值"]},
                    },
                    ensure_ascii=False,
                )
            ]
        )
        agent = build_specialist(
            AgentKind.INDUSTRY, llm, v2_container.services.tools, max_steps=2, max_llm_calls=6
        )
        result = agent.run(_task(), context)

        assert result.degraded is True
        assert result.tool_calls == 2
        assert "tool_step_budget_exceeded" in result.error
        assert result.summary

    def test_unknown_evidence_id_becomes_gap_and_unverified(
        self, v2_container, sample_docs, scripted_llm
    ):
        context, _ = _context(v2_container.services, sample_docs)
        llm = scripted_llm(
            [
                json.dumps(
                    {
                        "action": "finish",
                        "output": {
                            "summary": "含未经验证引用的结论",
                            "claims": [
                                {"text": "引用不存在证据的结论", "evidence_ids": ["ev-missing"]}
                            ],
                        },
                    },
                    ensure_ascii=False,
                )
            ]
        )
        agent = build_specialist(
            AgentKind.INDUSTRY, llm, v2_container.services.tools, max_steps=2, max_llm_calls=2
        )
        result = agent.run(_task(), context)

        claim = result.claims[0]
        assert claim.evidence_ids == []
        assert claim.verification_status.value == "unverified"
        assert any("unknown evidence" in gap for gap in result.gaps)

    def test_all_specialist_kinds_build_with_unique_specs(self, v2_container):
        kinds = specialist_kinds()
        assert len(kinds) == 8
        for kind in kinds:
            agent = build_specialist(kind, None, v2_container.services.tools)
            assert agent.spec.kind == kind
            assert agent.spec.system_prompt
            assert agent.spec.tools
            assert isinstance(agent.spec.output_model, type)

        catalog = agent_catalog()
        assert {item["kind"] for item in catalog} == {k.value for k in kinds}
        kinds_in_industry = set(
            build_specialist(AgentKind.INDUSTRY, None, v2_container.services.tools).spec.tools
        )
        assert "gap_radar_scan" not in kinds_in_industry


class TestSupervisor:
    def test_deterministic_first_round_uses_question_tree(self):
        supervisor = Supervisor(None, max_specialists=4, max_rounds=2)
        plan = supervisor.plan(county="安吉县", focus="竹产业")

        assert plan.planner_source == "deterministic"
        assert len(plan.tasks) == 4
        assert plan.research_question
        assert any("安吉县" in query for task in plan.tasks for query in task.queries)
        assert len({task.agent for task in plan.tasks}) == len(plan.tasks)

    def test_followup_round_routes_queries_to_matching_agents(self):
        supervisor = Supervisor(None, max_specialists=6, max_rounds=2)
        plan = supervisor.plan(
            county="安吉县",
            focus="竹产业",
            round_no=2,
            followup_queries=[
                "安吉县竹产业 补贴政策 实施方案",
                "安吉县竹产业 专利 研发 技术",
            ],
        )

        assert plan.round == 2
        assert {task.agent for task in plan.tasks} == {
            AgentKind.POLICY,
            AgentKind.INNOVATION,
        }
        assert all(task.parent_gap for task in plan.tasks)

    def test_llm_plan_is_validated_and_deduplicated(self, scripted_llm):
        llm = scripted_llm(
            [
                json.dumps(
                    {
                        "research_question": "安吉县竹产业升级路径",
                        "objectives": ["识别补链环节"],
                        "rationale": "需要产业与政策证据",
                        "tasks": [
                            {
                                "agent": "industry",
                                "objective": "分析产业链环节",
                                "queries": ["安吉县 竹产业 产业链"],
                            },
                            {
                                "agent": "industry",
                                "objective": "重复任务",
                                "queries": ["安吉县 竹产业"],
                            },
                            {
                                "agent": "critic",
                                "objective": "不应由 Supervisor 调度",
                                "queries": ["安吉县"],
                            },
                            {
                                "agent": "policy",
                                "objective": "梳理扶持政策",
                                "queries": ["安吉县 竹产业 政策"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
            ]
        )
        supervisor = Supervisor(llm, max_specialists=4, max_rounds=2)
        plan = supervisor.plan(county="安吉县", focus="竹产业")

        assert plan.planner_source == "llm"
        assert [task.agent for task in plan.tasks] == [
            AgentKind.INDUSTRY,
            AgentKind.POLICY,
        ]

    def test_invalid_llm_output_falls_back_to_deterministic(self, scripted_llm):
        llm = scripted_llm(["这不是 JSON"])
        plan = Supervisor(llm, max_specialists=3).plan(county="安吉县", focus="竹产业")
        assert plan.planner_source == "deterministic"
        assert len(plan.tasks) == 3


def _agent_result(kind: AgentKind, text: str, evidence_ids: list[str], **kwargs) -> AgentResult:
    return AgentResult(
        task_id=f"{kind.value}-task",
        agent=kind,
        summary=f"{kind.value} summary",
        claims=[
            Claim(
                text=text,
                evidence_ids=evidence_ids,
                confidence=0.8,
                verification_status="verified" if evidence_ids else "unverified",
                source_agent=kind.value,
            )
        ],
        evidence_ids=list(evidence_ids),
        **kwargs,
    )


class TestCritic:
    def test_sufficient_when_all_claims_have_valid_evidence(self, v2_container, sample_docs):
        context, evidence = _context(v2_container.services, sample_docs)
        ids = [item.id for item in evidence.all()]
        assert len(ids) >= 5
        results = [
            _agent_result(AgentKind.MACRO, evidence.get(ids[0]).claim, ids[:1]),
            _agent_result(AgentKind.INDUSTRY, evidence.get(ids[2]).claim, ids[2:3]),
            _agent_result(AgentKind.ENTERPRISE, evidence.get(ids[4]).claim, ids[4:5]),
        ]
        critic = CriticAgent(None, v2_container.services.tools)
        report = critic.review(context, results, round_no=1)

        assert report.coverage == 1.0
        assert report.unsupported_claims == 0
        assert report.audited_claims == 3
        assert report.is_sufficient is True

    def test_unsupported_claim_blocks_sufficiency(self, v2_container, sample_docs):
        context, evidence = _context(v2_container.services, sample_docs)
        ids = [item.id for item in evidence.all()]
        results = [
            _agent_result(AgentKind.MACRO, evidence.get(ids[0]).claim, ids[:1]),
            _agent_result(AgentKind.INDUSTRY, "无证据结论", []),
            _agent_result(AgentKind.ENTERPRISE, evidence.get(ids[2]).claim, ids[2:3]),
        ]
        critic = CriticAgent(None, v2_container.services.tools)
        report = critic.review(context, results, round_no=1)

        assert report.unsupported_claims == 1
        assert report.is_sufficient is False
        assert any(f.kind == "unsupported_claim" for f in report.findings)
        assert report.followup_queries

    def test_missing_required_dimensions_reported(self, v2_container, sample_docs):
        context, evidence = _context(v2_container.services, sample_docs)
        ids = [item.id for item in evidence.all()]
        results = [
            _agent_result(AgentKind.INDUSTRY, evidence.get(ids[0]).claim, ids[:1])
        ]
        critic = CriticAgent(None, v2_container.services.tools)
        report = critic.review(context, results, round_no=1)

        coverage_gaps = [f for f in report.findings if f.kind == "coverage_gap"]
        assert coverage_gaps
        assert "macro" in coverage_gaps[0].description
        assert report.is_sufficient is False

    def test_invalid_evidence_reference_flagged(self, v2_container, sample_docs):
        context, evidence = _context(v2_container.services, sample_docs)
        ids = [item.id for item in evidence.all()]
        results = [
            _agent_result(
                AgentKind.INDUSTRY,
                evidence.get(ids[0]).claim,
                [ids[0], "ev-does-not-exist"],
            ),
            _agent_result(AgentKind.MACRO, evidence.get(ids[1]).claim, ids[1:2]),
            _agent_result(AgentKind.ENTERPRISE, evidence.get(ids[2]).claim, ids[2:3]),
        ]
        critic = CriticAgent(None, v2_container.services.tools)
        report = critic.review(context, results, round_no=1)
        assert any(f.kind == "invalid_evidence_ref" for f in report.findings)
        assert report.is_sufficient is False

    def test_llm_cannot_ignore_deterministic_unsupported_claims(self, scripted_llm, v2_container, sample_docs):
        context, evidence = _context(v2_container.services, sample_docs)
        ids = [item.id for item in evidence.all()]
        results = [
            _agent_result(AgentKind.MACRO, evidence.get(ids[0]).claim, ids[:1]),
            _agent_result(AgentKind.INDUSTRY, "无证据", []),
            _agent_result(AgentKind.ENTERPRISE, evidence.get(ids[2]).claim, ids[2:3]),
        ]
        llm = scripted_llm(
            [
                json.dumps(
                    {
                        "is_sufficient": True,
                        "coverage": 1.0,
                        "findings": [],
                        "followup_queries": [],
                        "reasoning": "看起来完整",
                    },
                    ensure_ascii=False,
                )
            ]
        )
        critic = CriticAgent(llm, v2_container.services.tools)
        report = critic.review(context, results, round_no=1)
        assert report.is_sufficient is False
        assert report.unsupported_claims == 1


class TestReportAgent:
    def test_deterministic_compose_uses_agent_results(self, v2_container, sample_docs):
        context, evidence = _context(v2_container.services, sample_docs)
        ids = [item.id for item in evidence.all()]
        results = [
            _agent_result(AgentKind.MACRO, "竹产业产值 120 亿元", ids[:1]),
            _agent_result(AgentKind.INDUSTRY, "形成完整产业链", ids[1:2]),
        ]
        critique = CritiqueReport(
            is_sufficient=True, coverage=1.0, audited_claims=2, round=1
        )
        agent = ReportAgent(None)
        summary, sections, top, gaps, degraded = agent.compose(
            context,
            results,
            research_question="安吉县竹产业如何升级？",
            critique=critique,
            opportunities=[],
        )

        assert "2 个专业 Agent" in summary
        titles = [section.title for section in sections]
        assert AGENT_TITLES[AgentKind.MACRO] in titles
        assert AGENT_TITLES[AgentKind.INDUSTRY] in titles
        assert any(section.title == "证据审计与不确定性" for section in sections)
        assert top == []
        assert gaps == []
        assert degraded is False
        industry_section = next(
            s for s in sections if s.title == AGENT_TITLES[AgentKind.INDUSTRY]
        )
        assert ids[1] in industry_section.evidence_ids

    def test_deterministic_compose_marks_degraded_results(self, v2_container, sample_docs):
        context, evidence = _context(v2_container.services, sample_docs)
        ids = [item.id for item in evidence.all()]
        result = _agent_result(AgentKind.INDUSTRY, "降级结论", ids[:1], degraded=True)
        summary, sections, _, _, degraded = ReportAgent(None).compose(
            context, [result], research_question="测试", critique=None, opportunities=[]
        )
        assert degraded is True
        assert any("降级模式" in section.content for section in sections)

    def test_invalid_llm_report_falls_back(self, scripted_llm, v2_container, sample_docs):
        context, evidence = _context(v2_container.services, sample_docs)
        ids = [item.id for item in evidence.all()]
        results = [_agent_result(AgentKind.INDUSTRY, "结论", ids[:1])]
        llm = scripted_llm(["not json"])
        summary, sections, _, _, _ = ReportAgent(llm).compose(
            context, results, research_question="测试", critique=None, opportunities=[]
        )
        assert sections
        assert "专业 Agent" in summary


def test_tool_observation_defaults():
    observation = ToolObservation(tool="x")
    assert observation.ok is True
    assert observation.evidence_ids == []
