"""多智能体深度研究系统单元与集成测试。"""
from __future__ import annotations

from county_research_ai.agent.models import AgentState, ToolStatus
from county_research_ai.agent.tools import (
    DeepMultiAgentAnalysisTool,
    PlanResearchTreeTool,
    ReflectAndSupplementTool,
)
from county_research_ai.evidence.store import EvidenceStore
from county_research_ai.models import CountyInfo, RawDoc, ResearchRequest
from county_research_ai.research_agent.coordinator import DeepResearchCoordinator
from county_research_ai.research_agent.critic import ResearchCritic
from county_research_ai.research_agent.specialized import (
    EconomicResearchAgent,
    IndustryResearchAgent,
    PolicyResearchAgent,
    ResearchSynthesizer,
)
from county_research_ai.research_agent.tree import build_question_tree
from county_research_ai.search.collector import SearchCollector


def test_question_tree_construction_for_all_modes():
    t1 = build_question_tree("安吉县", "竹产业", "snapshot")
    assert len(t1.questions) >= 5
    categories = {q.category for q in t1.questions}
    assert "economic" in categories
    assert "policy" in categories
    assert "industry" in categories

    t2 = build_question_tree("鹤岗市", "产业转型", "rise-fall")
    assert any("黄金" in q.title or "鼎盛" in q.title for q in t2.questions)
    assert any("拐点" in q.title or "衰落" in q.title for q in t2.questions)

    t3 = build_question_tree("信丰县", None, "long-history")
    assert any("建县" in q.title for q in t3.questions)
    assert any("计划经济" in q.title for q in t3.questions)


def test_research_critic_reflects_and_identifies_gaps():
    store = EvidenceStore()
    doc = RawDoc(
        title="安吉县竹林介绍",
        url="https://anji.gov.cn/intro",
        snippet="安吉县拥有丰富竹林资源，竹林面积达101万亩。",
        domain_type="government",
        credibility_score=0.9,
    )
    store.ingest_documents([doc], county="安吉县")
    qtree = build_question_tree("安吉县", "竹产业", "snapshot")

    critic = ResearchCritic(max_turns=2)
    reflection = critic.reflect(store, qtree, current_turn=1)

    assert reflection.is_sufficient is False
    assert len(reflection.gaps) >= 1
    assert len(reflection.followup_queries) >= 1
    assert any("产值" in q or "统计" in q for q in reflection.followup_queries)


def test_specialized_agents_and_synthesizer():
    store = EvidenceStore()
    docs = [
        RawDoc(
            title="2023年安吉县国民经济统计公报",
            url="https://anji.gov.cn/tjgb2023",
            snippet="安吉县竹产业全产业链产值超过280亿元，竹林面积达101.1万亩。",
            content="2023年安吉县竹产业全产业链产值超过280亿元，全县规上工业总产值较快增长。",
            domain_type="government",
            credibility_score=0.95,
        ),
        RawDoc(
            title="加快以竹代塑发展三年行动计划",
            url="https://ndrc.gov.cn/yzds",
            snippet="国家发展改革委等部门印发《加快“以竹代塑”发展三年行动计划》。",
            content="出台政策规划文件《加快“以竹代塑”发展三年行动计划》。",
            domain_type="government",
            credibility_score=0.95,
        ),
        RawDoc(
            title="安吉竹产业龙头企业概况",
            url="https://anji.gov.cn/company",
            snippet="浙江大庄实业集团有限公司等龙头企业深耕竹地板与竹集成材领域。",
            content="大庄实业集团有限公司、永裕家居等链主企业集聚发展。",
            domain_type="company",
            credibility_score=0.75,
        ),
    ]
    store.ingest_documents(docs, county="安吉县", focus="竹产业")

    econ = EconomicResearchAgent().analyze("安吉县", "竹产业", store)
    pol = PolicyResearchAgent().analyze("安吉县", "竹产业", store)
    ind = IndustryResearchAgent().analyze("安吉县", "竹产业", store)

    assert "280亿元" in "".join(econ.output_values) or "280" in "".join(econ.output_values)
    assert len(pol.policy_documents) >= 1
    assert len(ind.bottlenecks_and_risks) >= 1

    synth = ResearchSynthesizer()
    c_info = CountyInfo.from_name("安吉县")
    analyses = synth.synthesize(
        county=c_info,
        focus="竹产业",
        economic_out=econ,
        policy_out=pol,
        industry_out=ind,
        evidence_store=store,
    )

    assert len(analyses) == 4
    tasks = {a.task for a in analyses}
    assert tasks == {"industry_status", "advantages", "shortcomings", "recommendations"}

    # 检查审计附录与来源溯源表
    last_content = analyses[-1].content
    assert "附录：研究证据链与可信度审计记录" in last_content
    assert "核心参考文献与证据溯源表" in last_content


def test_deep_research_coordinator_workflow(tmp_settings):
    from county_research_ai.mocks.search import MockSearchProvider

    collector = SearchCollector(
        web_provider=MockSearchProvider(),
        settings=tmp_settings,
    )
    coord = DeepResearchCoordinator(search_collector=collector, max_turns=2)
    result = coord.run_deep_research("安吉县", focus="竹产业", mode="snapshot")

    assert result.county.name == "安吉县"
    assert len(result.analyses) == 4
    assert len(result.question_tree.questions) >= 5
    assert result.total_turns >= 1
    assert result.executive_summary


def test_agent_tools_support_deep_research_lifecycle(tool_context):
    state = AgentState.from_request(
        ResearchRequest(
            county="安吉县",
            focus="竹产业",
            mode="snapshot",
            options={"deep_research": True},
        )
    )

    # 1. 计划问题树
    plan_tool = PlanResearchTreeTool(tool_context)
    res_plan = plan_tool.execute(state, {})
    assert res_plan.status == ToolStatus.SUCCESS
    state.apply_patch(res_plan.state_patch)
    assert state.question_tree is not None

    # 2. 模拟已有文档后反思
    state.raw_docs = [
        RawDoc(
            title="安吉公报",
            url="https://anji.gov.cn/a",
            snippet="安吉竹林面积101万亩，产值280亿元",
            domain_type="government",
            credibility_score=0.9,
        )
    ]
    ref_tool = ReflectAndSupplementTool(tool_context)
    res_ref = ref_tool.execute(state, {})
    assert res_ref.status == ToolStatus.SUCCESS
    state.apply_patch(res_ref.state_patch)
    assert len(state.reflection_results) == 1

    # 3. 深度多智能体分析
    ana_tool = DeepMultiAgentAnalysisTool(tool_context)
    res_ana = ana_tool.execute(state, {})
    assert res_ana.status == ToolStatus.SUCCESS
    state.apply_patch(res_ana.state_patch)
    assert len(state.snapshot_analyses) == 4
