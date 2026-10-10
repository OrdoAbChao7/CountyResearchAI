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


def test_deep_research_coordinator_rise_fall_and_long_history(tmp_settings):
    from county_research_ai.mocks.search import MockSearchProvider

    collector = SearchCollector(
        web_provider=MockSearchProvider(),
        settings=tmp_settings,
    )
    coord = DeepResearchCoordinator(search_collector=collector, max_turns=2)

    # 1. rise-fall 模式
    res_rf = coord.run_deep_research("鹤岗市", focus="产业转型", mode="rise-fall")
    assert res_rf.mode == "rise-fall"
    assert res_rf.rise_fall_analysis is not None
    assert res_rf.rise_fall_analysis.county.name == "鹤岗市"

    # 2. long-history 模式
    res_lh = coord.run_deep_research("信丰县", focus="长周期兴衰史", mode="long-history")
    assert res_lh.mode == "long-history"
    assert res_lh.long_history_analysis is not None
    assert res_lh.long_history_analysis.county.name == "信丰县"


def test_pipeline_executes_deep_research_all_modes(tmp_settings, mock_llm, sample_docs):
    from county_research_ai.mocks.search import MockSearchProvider
    from county_research_ai.pipeline import ResearchPipeline
    from county_research_ai.storage.local_fs import LocalFSStorage

    pipeline = ResearchPipeline(
        search=MockSearchProvider(),
        storage=LocalFSStorage(settings=tmp_settings),
        llm=mock_llm,
    )

    # 1. snapshot deep
    req_snap = ResearchRequest(
        county="安吉县", focus="竹产业", mode="snapshot", options={"deep_research": True}
    )
    rep_snap, path_snap = pipeline.run(req_snap)
    assert path_snap.is_file()
    snap_text = path_snap.read_text(encoding="utf-8")
    assert "安吉县" in snap_text
    assert "竹产业" in snap_text

    # 2. rise-fall deep
    req_rf = ResearchRequest(
        county="鹤岗市", mode="rise-fall", options={"deep_research": True}
    )
    rep_rf, path_rf = pipeline.run(req_rf)
    assert path_rf.is_file()
    rf_text = path_rf.read_text(encoding="utf-8")
    assert "鹤岗市" in rf_text
    assert "附录：研究证据链与可信度审计记录" in rf_text

    # 3. long-history deep
    req_lh = ResearchRequest(
        county="信丰县", mode="long-history", options={"deep_research": True}
    )
    rep_lh, path_lh = pipeline.run(req_lh)
    assert path_lh.is_file()
    lh_text = path_lh.read_text(encoding="utf-8")
    assert "信丰县" in lh_text
    assert "附录：研究证据链与可信度审计记录" in lh_text


def test_agent_tools_deep_research_for_rise_fall(tool_context):
    from county_research_ai.agent.tools import ReportTool
    from county_research_ai.agent.verifier import AgentVerifier

    state = AgentState.from_request(
        ResearchRequest(
            county="鹤岗市",
            mode="rise-fall",
            options={"deep_research": True},
        )
    )
    state.raw_docs = [
        RawDoc(
            title="鹤岗百年煤城史志",
            url="https://hegang.gov.cn/history",
            snippet="1917年发现煤田，2011年列入资源枯竭型城市",
            content="1917年发现煤田，2011年列入第三批资源枯竭型城市名单，常住人口89.1万人",
            domain_type="government",
            credibility_score=0.95,
        )
    ]
    ana_tool = DeepMultiAgentAnalysisTool(tool_context)
    res_ana = ana_tool.execute(state, {})
    assert res_ana.status == ToolStatus.SUCCESS
    state.apply_patch(res_ana.state_patch)
    assert state.rise_fall_analysis is not None

    rep_tool = ReportTool(tool_context)
    res_rep = rep_tool.execute(state, {})
    assert res_rep.status == ToolStatus.SUCCESS
    state.apply_patch(res_rep.state_patch)
    assert state.report_path is not None

    verifier = AgentVerifier()
    vf = verifier.verify_final(state)
    assert vf.ok is True

