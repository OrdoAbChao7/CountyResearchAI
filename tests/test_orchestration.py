"""LangGraph 编排测试：并行分发、路由、检查点恢复与完整研究运行。"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from county_research_ai.domain.events import EventType
from county_research_ai.domain.intelligence import (
    CritiqueReport,
    ResearchRunRequest,
    ResearchTask,
    RunStatus,
)
from county_research_ai.orchestration.artifacts import RunArtifacts
from county_research_ai.orchestration.checkpoint import run_config
from county_research_ai.orchestration.events import RunEventStore
from county_research_ai.orchestration.graph import build_research_graph
from county_research_ai.orchestration.routing import after_critic, dispatch_specialists
from county_research_ai.orchestration.runner import RunNotFound
from county_research_ai.orchestration.state import initial_state


class TestRouting:
    def test_dispatch_builds_one_send_per_agent(self):
        state = initial_state(run_id="r", county="安吉县", focus="竹产业")
        state["tasks"] = [
            ResearchTask(task_id="t1", agent="industry", objective="a").model_dump(mode="json"),
            ResearchTask(task_id="t2", agent="policy", objective="b").model_dump(mode="json"),
            ResearchTask(task_id="t2b", agent="policy", objective="dup").model_dump(mode="json"),
            ResearchTask(task_id="t3", agent="critic", objective="invalid").model_dump(mode="json"),
        ]
        sends = dispatch_specialists(state)
        assert isinstance(sends, list)
        assert [send.node for send in sends] == ["agent_industry", "agent_policy"]
        assert all(send.arg["task"]["task_id"] for send in sends)

    def test_dispatch_without_tasks_falls_through_to_aggregate(self):
        state = initial_state(run_id="r", county="安吉县")
        assert dispatch_specialists(state) == "aggregate"

    def test_after_critic_supplements_when_round_budget_remains(self):
        state = initial_state(run_id="r", county="安吉县", max_rounds=2)
        state["round"] = 1
        state["critique"] = CritiqueReport(is_sufficient=False).model_dump()
        state["followup_queries"] = ["安吉县竹产业 政策"]
        assert after_critic(state) == "supplement"

    def test_after_critic_stops_at_budget_or_sufficiency(self):
        state = initial_state(run_id="r", county="安吉县", max_rounds=2)
        state["round"] = 2
        state["critique"] = CritiqueReport(is_sufficient=False).model_dump()
        state["followup_queries"] = ["安吉县竹产业 政策"]
        assert after_critic(state) == "build_graph"

        state["round"] = 1
        state["critique"] = CritiqueReport(is_sufficient=True).model_dump()
        assert after_critic(state) == "build_graph"


class TestEventsAndArtifacts:
    def test_event_store_sequence_and_replay(self, tmp_path):
        store = RunEventStore("run-x", tmp_path)
        first = store.emit(EventType.NODE_STARTED, node="intake", message="start")
        second = store.emit(EventType.NODE_COMPLETED, node="intake", message="done")
        assert (first.seq, second.seq) == (1, 2)
        assert [e.seq for e in store.after(1)] == [2]
        assert store.last_seq == 2

        reloaded = RunEventStore("run-x", tmp_path)
        assert [e.message for e in reloaded.all()] == ["start", "done"]
        assert reloaded.last_seq == 2

    def test_artifacts_roundtrip(self, tmp_path, sample_docs):
        from county_research_ai.services.evidence_service import EvidenceService

        artifacts = RunArtifacts("run-x", tmp_path / "run-x")
        evidence = EvidenceService()
        evidence.ingest(sample_docs, county="安吉县", focus="竹产业")
        artifacts.save_evidence(evidence)
        artifacts.save_docs(sample_docs)
        artifacts.write_text("report.md", "# 报告")

        restored = EvidenceService()
        assert artifacts.load_evidence(restored) == len(evidence.all())
        assert len(artifacts.load_docs()) == len(sample_docs)
        assert artifacts.read_text("report.md") == "# 报告"


def _direct_graph_context(services, tmp_settings, run_id: str):
    from county_research_ai.agents.base import AgentContext

    run_dir = tmp_settings.runs_dir / run_id
    artifacts = RunArtifacts(run_id, run_dir)
    store = RunEventStore(run_id, run_dir)
    evidence = services.new_evidence()
    context = AgentContext(
        run_id=run_id,
        county="安吉县",
        focus="竹产业",
        evidence=evidence,
        search=services.search,
        documents=services.documents,
        graph=services.graph,
        quant=services.quant,
        analytics=services.analytics,
        graph_store=services.graph_store,
        gap_radar=services.new_gap_radar(evidence),
        emitter=store.callback,
    )
    config = run_config(
        run_id,
        services=services,
        context=context,
        artifacts=artifacts,
        emitter=store.callback,
        recursion_limit=tmp_settings.agents.recursion_limit,
    )
    return context, artifacts, store, config


class TestCheckpointResume:
    def test_run_stops_before_report_and_resumes_from_checkpoint(
        self, v2_container, tmp_settings
    ):
        run_id = "run-checkpoint"
        _, artifacts, store, config = _direct_graph_context(
            v2_container.services, tmp_settings, run_id
        )
        graph = build_research_graph(
            checkpointer=InMemorySaver(), interrupt_before=["report"]
        )
        state = initial_state(
            run_id=run_id, county="安吉县", focus="竹产业", max_rounds=2
        )

        interrupted = graph.invoke(state, config)
        snapshot = graph.get_state(config)
        assert tuple(snapshot.next) == ("report",)
        assert interrupted["results"]
        assert not interrupted.get("report")
        assert interrupted["opportunities"] is not None
        assert artifacts.read_json("evidence.json", default=[])

        resumed = graph.invoke(None, config)
        assert resumed["status"] == "completed"
        assert resumed["report"]["report_path"]
        assert resumed["evidence_count"] >= 1
        assert graph.get_state(config).next == ()
        assert (tmp_settings.runs_dir / run_id / "report.md").exists()
        assert store.last_seq > 0


class TestResearchRunService:
    def test_full_run_completes_with_agents_report_and_events(self, v2_container):
        runs = v2_container.runs
        record = runs.start(
            ResearchRunRequest(county="安吉县", focus="竹产业")
        )
        assert record.status in {RunStatus.QUEUED, RunStatus.RUNNING}
        record = runs.wait(record.run_id, timeout=120)

        assert record.status == RunStatus.COMPLETED, record.error
        assert record.report_path
        assert record.evidence_count >= 1
        assert record.plan is not None
        assert len(record.agent_results) >= 5
        assert record.critique is not None
        assert runs.checkpoint_backend in {"sqlite", "memory"}

        agents = {result.agent.value for result in record.agent_results}
        assert {"industry", "macro"} <= agents

        markdown = runs.report_markdown(record.run_id)
        assert "执行摘要" in markdown
        assert "证据索引" in markdown

        evidence = runs.evidence_snapshot(record.run_id)
        assert evidence
        assert all(item.get("id") for item in evidence)

        events = runs.events(record.run_id)
        types = {event.type for event in events}
        assert EventType.RUN_STARTED in types
        assert EventType.AGENT_COMPLETED in types
        assert EventType.REPORT_READY in types
        assert EventType.RUN_COMPLETED in types
        assert [e.seq for e in events] == sorted(e.seq for e in events)

        state = runs.state(record.run_id)
        assert state.get("status") == "completed"

    def test_resume_completed_run_is_noop(self, v2_container):
        runs = v2_container.runs
        record = runs.wait(
            runs.start(ResearchRunRequest(county="安吉县", focus="竹产业")).run_id,
            timeout=120,
        )
        again = runs.resume(record.run_id)
        assert again.status == RunStatus.COMPLETED

    def test_unknown_run_raises(self, v2_container):
        with pytest.raises(RunNotFound):
            v2_container.runs.get("run-does-not-exist")

    def test_list_runs_includes_completed(self, v2_container):
        record = v2_container.runs.wait(
            v2_container.runs.start(
                ResearchRunRequest(county="安吉县", focus="竹产业")
            ).run_id,
            timeout=120,
        )
        listed = v2_container.runs.list_runs()
        assert record.run_id in {item.run_id for item in listed}
