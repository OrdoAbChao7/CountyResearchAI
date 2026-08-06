"""CLI 端到端测试(Mock 降级路径)。

用 click.testing.CliRunner 调用 CLI,不依赖真实 API。
用 monkeypatch 设置临时目录,不污染项目。
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from county_research_ai.cli import main
from county_research_ai.config import reset_settings


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    """隔离 CLI 运行环境。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    reset_settings()
    yield tmp_path
    reset_settings()


class TestCLIDryRun:
    def test_dry_run_exits_zero(self, cli_env):
        runner = CliRunner()
        result = runner.invoke(main, [
            "--county", "安吉县", "--focus", "竹产业", "--dry-run",
        ])
        assert result.exit_code == 0
        assert "dry-run" in result.output

    def test_dry_run_no_report_generated(self, cli_env):
        runner = CliRunner()
        runner.invoke(main, [
            "--county", "安吉县", "--focus", "竹产业", "--dry-run",
        ])
        # dry-run 不应生成报告文件
        reports = list((cli_env / "reports").glob("*.md"))
        assert reports == []


class TestCLIFullRun:
    def test_full_run_exits_zero(self, cli_env):
        runner = CliRunner()
        result = runner.invoke(main, [
            "--county", "安吉县", "--focus", "竹产业",
        ])
        assert result.exit_code == 0
        assert "成功" in result.output

    def test_full_run_generates_report(self, cli_env):
        runner = CliRunner()
        result = runner.invoke(main, [
            "--county", "安吉县", "--focus", "竹产业",
        ])
        assert result.exit_code == 0
        reports = list((cli_env / "reports").glob("安吉县_竹产业_*.md"))
        assert len(reports) == 1

    def test_report_preview_in_output(self, cli_env):
        runner = CliRunner()
        result = runner.invoke(main, [
            "--county", "安吉县", "--focus", "竹产业",
        ])
        assert "报告预览" in result.output
        assert "安吉县" in result.output

    def test_no_cache_flag(self, cli_env):
        runner = CliRunner()
        result = runner.invoke(main, [
            "--county", "安吉县", "--focus", "竹产业", "--no-cache",
        ])
        assert result.exit_code == 0
        assert "跳过缓存" in result.output

    def test_short_options(self, cli_env):
        runner = CliRunner()
        result = runner.invoke(main, [
            "-c", "安吉县", "-f", "竹产业", "--dry-run",
        ])
        assert result.exit_code == 0


class TestCLINoFocus:
    def test_no_flag_shows_auto_discover(self, cli_env):
        """不传 --focus 时，应显示自动识别提示。"""
        runner = CliRunner()
        result = runner.invoke(main, [
            "-c", "安吉县", "--dry-run",
        ])
        assert result.exit_code == 0
        assert "自动识别" in result.output

    def test_no_flag_full_run(self, cli_env):
        """不传 --focus 时，应自动发现产业方向并生成报告。"""
        runner = CliRunner()
        result = runner.invoke(main, [
            "-c", "安吉县",
        ])
        assert result.exit_code == 0
        assert "成功" in result.output
        # 报告应使用自动发现的方向
        reports = list((cli_env / "reports").glob("安吉县_特色农业_*.md"))
        assert len(reports) == 1

    def test_no_flag_report_contains_discovered_focus(self, cli_env):
        """自动发现的报告应包含发现的产业方向内容。"""
        runner = CliRunner()
        result = runner.invoke(main, [
            "-c", "安吉县",
        ])
        report_path = list((cli_env / "reports").glob("安吉县_特色农业_*.md"))[0]
        content = report_path.read_text(encoding="utf-8")
        assert "特色农业" in content
