from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from county_research_ai.agent.models import AgentRunResult, AgentState, AgentStatus, AgentTrace
from county_research_ai.cli import main
from county_research_ai.models import ResearchRequest


def _result(tmp_path: Path, *, status: AgentStatus = AgentStatus.COMPLETED) -> AgentRunResult:
    report_path = tmp_path / "report.md"
    trace_path = tmp_path / "trace.json"
    report_path.write_text("# 安吉县\n## 竹产业\n", encoding="utf-8")
    trace_path.write_text("{}", encoding="utf-8")
    request = ResearchRequest(county="安吉县", focus="竹产业")
    state = AgentState.from_request(request)
    state.status = status
    state.report_path = str(report_path) if status == AgentStatus.COMPLETED else ""
    trace = AgentTrace(request=request, status=status, report_path=state.report_path)
    return AgentRunResult(
        state=state,
        trace=trace,
        report_path=report_path if state.report_path else None,
        trace_path=trace_path,
    )


def test_agent_dry_run_does_not_construct_runtime(monkeypatch):
    calls = []
    monkeypatch.setattr("county_research_ai.cli.create_default_agent", lambda **kwargs: calls.append(kwargs))

    result = CliRunner().invoke(
        main,
        ["agent", "-c", "安吉县", "-f", "竹产业", "--mode", "snapshot", "--dry-run"],
    )

    assert result.exit_code == 0
    assert "dry-run" in result.output
    assert calls == []


def test_agent_command_forwards_options_and_prints_outputs(monkeypatch, tmp_path):
    calls = []

    class FakeAgent:
        def run(self, request):
            calls.append(request)
            return _result(tmp_path)

    def fake_factory(**kwargs):
        calls.append(kwargs)
        return FakeAgent()

    monkeypatch.setattr("county_research_ai.cli.create_default_agent", fake_factory)

    result = CliRunner().invoke(
        main,
        [
            "agent", "-c", "安吉县", "-f", "竹产业", "--mode", "rise-fall",
            "--max-steps", "5", "--no-trace",
        ],
    )

    assert result.exit_code == 0
    assert calls[0] == {"max_steps": 5, "save_trace": False}
    assert calls[1].mode == "rise-fall"
    assert "Agent 运行成功" in result.output
    assert "report.md" in result.output


def test_agent_command_returns_nonzero_on_failed_run(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "county_research_ai.cli.create_default_agent",
        lambda **kwargs: type("FakeAgent", (), {"run": lambda self, request: _result(tmp_path, status=AgentStatus.FAILED)})(),
    )

    result = CliRunner().invoke(main, ["agent", "-c", "安吉县"])

    assert result.exit_code == 1
    assert "Agent 运行失败" in result.output
