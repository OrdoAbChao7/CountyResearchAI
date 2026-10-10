"""命令行入口。

基于 Click 框架,提供 `county-research` 命令组。

注册方式:pyproject.toml 中 [project.scripts]
    county-research = "county_research_ai.cli:main"

调用方式:

1. 固定流程 Workflow(显式或兼容旧入口):
    county-research workflow --county 安吉县 --focus 竹产业
    county-research --county 安吉县 --focus 竹产业
    county-research -c 鹤岗市 --mode rise-fall

2. 可解释、可追踪的 Agent:
    county-research agent -c 安吉县 -f 竹产业 --mode snapshot

MVP 阶段使用 create_default_pipeline() 构造带 Mock 的 pipeline,
保证不填 API Key 也能完整跑通输入→报告链路。
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import click

from .agent.factory import create_default_agent
from .config import reset_settings
from .exceptions import CountyResearchAIError
from .models import ResearchRequest
from .pipeline import create_default_pipeline, setup_logging


def _print_banner() -> None:
    banner = r"""
╔══════════════════════════════════════════════════╗
║       AI 县域产业研究助手 v0.1.0 (MVP)             ║
║   自动化采集 · 智能分析 · 一键生成产业研究报告       ║
╚══════════════════════════════════════════════════╝
"""
    click.echo(banner)


@click.group(
    "county-research",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--county", "-c",
    required=False,
    type=str,
    default=None,
    help="县名,如 '安吉县' 或 '浙江省湖州市安吉县'(研究模式必填)",
)
@click.option(
    "--focus", "-f",
    required=False,
    type=str,
    default=None,
    help="研究方向,如 '竹产业' / '乡村旅游' / '装备制造'。留空则自动识别该县重点产业",
)
@click.option(
    "--mode", "-m",
    type=click.Choice(
        ["snapshot", "industry", "rise-fall", "long-history"],
        case_sensitive=False,
    ),
    default="snapshot",
    help=(
        "研究模式:"
        " snapshot/industry(产业现状快照,默认)"
        " / rise-fall(产业兴衰规律研究)"
        " / long-history(县域长周期兴衰史分析)"
    ),
)
@click.option(
    "--historical",
    is_flag=True,
    default=False,
    help="rise-fall 模式快捷开关(等价于 --mode rise-fall)",
)
@click.option(
    "--long-history",
    is_flag=True,
    default=False,
    help="long-history 模式快捷开关(等价于 --mode long-history)",
)
@click.option(
    "--log-level", "-l",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default=None,
    help="覆盖日志级别(默认读取 settings.yaml/.env)",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="跳过缓存,强制重新采集与分析",
)
@click.option(
    "--deep",
    is_flag=True,
    default=False,
    help="启动多智能体深度研究模式(动态问题树、反思补充检索与事实核验)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="仅打印请求参数,不实际执行 pipeline",
)
@click.pass_context
def main(
    ctx: click.Context,
    county: str | None,
    focus: str | None,
    mode: str,
    historical: bool,
    long_history: bool,
    log_level: str | None,
    no_cache: bool,
    deep: bool,
    dry_run: bool,
) -> None:
    """AI 县域产业研究助手 — 县域产业研究。

    \b
    子命令:
      workflow  按固定顺序执行搜索、处理、分析和报告
      agent     由 Agent 动态规划研究步骤并保存执行轨迹

    \b
    不指定子命令时,默认执行产业研究:
      county-research --county 安吉县 --focus 竹产业
      county-research workflow --county 安吉县 --focus 竹产业
      county-research -c 鹤岗市 --mode rise-fall
      county-research -c 信丰县 --long-history

    """
    # 全局环境初始化
    reset_settings()
    if log_level:
        import os
        os.environ["LOG_LEVEL"] = log_level
    setup_logging()

    # 仅在未指定子命令时执行产业研究
    if ctx.invoked_subcommand is None:
        _run_research(
            county=county, focus=focus, mode=mode,
            historical=historical, long_history=long_history,
            no_cache=no_cache, deep=deep, dry_run=dry_run,
        )


@main.command("workflow")
@click.option("--county", "-c", required=True, type=str, help="县名,如 '安吉县'")
@click.option("--focus", "-f", required=False, type=str, default=None, help="研究方向,留空则自动发现")
@click.option(
    "--mode",
    type=click.Choice(["snapshot", "industry", "rise-fall", "long-history"], case_sensitive=False),
    default="snapshot",
    show_default=True,
    help="Workflow 研究模式",
)
@click.option("--historical", is_flag=True, default=False, help="等价于 --mode rise-fall")
@click.option("--long-history", is_flag=True, default=False, help="等价于 --mode long-history")
@click.option("--no-cache", is_flag=True, default=False, help="跳过缓存,强制重新采集与分析")
@click.option("--deep", is_flag=True, default=False, help="启动多智能体深度研究模式")
@click.option("--dry-run", is_flag=True, default=False, help="只校验参数,不实际执行 Workflow")
def workflow_command(
    county: str,
    focus: str | None,
    mode: str,
    historical: bool,
    long_history: bool,
    no_cache: bool,
    deep: bool,
    dry_run: bool,
) -> None:
    """运行固定顺序的研究 Workflow。"""
    click.echo("Workflow 执行方式")
    _run_research(
        county=county,
        focus=focus,
        mode=mode,
        historical=historical,
        long_history=long_history,
        no_cache=no_cache,
        deep=deep,
        dry_run=dry_run,
    )


@main.command("agent")
@click.option("--county", "-c", required=True, type=str, help="县名,如 '安吉县'")
@click.option("--focus", "-f", required=False, type=str, default=None, help="研究方向,留空则自动发现")
@click.option(
    "--mode",
    type=click.Choice(["snapshot", "rise-fall", "long-history"], case_sensitive=False),
    default="snapshot",
    show_default=True,
    help="Agent 研究模式",
)
@click.option("--max-steps", type=click.IntRange(min=1), default=8, show_default=True, help="单次运行最大步骤数")
@click.option("--deep", is_flag=True, default=False, help="启动多智能体深度研究模式(包含动态规划、反思补充与事实核验)")
@click.option("--no-trace", is_flag=True, default=False, help="不保存 Agent 执行轨迹")
@click.option("--dry-run", is_flag=True, default=False, help="只校验参数,不构造或运行 Agent")
def agent_command(
    county: str,
    focus: str | None,
    mode: str,
    max_steps: int,
    deep: bool,
    no_trace: bool,
    dry_run: bool,
) -> None:
    """运行可解释、可追踪的研究 Agent。"""
    mode = mode.lower()
    click.echo(f"Agent 县名   : {county}")
    click.echo(f"Agent 方向   : {focus or '(自动发现)'}")
    click.echo(f"Agent 模式   : {mode}")
    click.echo(f"最大步骤数   : {max_steps}")
    click.echo(f"深度研究模式 : {'已开启' if deep else '标准模式'}")
    if dry_run:
        click.echo("[dry-run] Agent 参数校验通过,未构造或运行 Agent。")
        return

    options = {"deep_research": True} if deep else {}
    request = ResearchRequest(county=county, focus=focus, mode=mode, options=options)
    runtime = create_default_agent(max_steps=max_steps, save_trace=not no_trace)
    result = runtime.run(request)
    if result.state.status != result.trace.status or result.state.status.value != "completed":
        click.echo(
            f"❌ Agent 运行失败: {result.trace.failure_code or 'agent_failed'}",
            err=True,
        )
        if result.trace_path:
            click.echo(f"   Trace: {result.trace_path}", err=True)
        raise click.exceptions.Exit(1)

    click.echo("✅ Agent 运行成功")
    click.echo(f"   报告路径: {result.report_path or '(未生成)'}")
    if result.trace_path:
        click.echo(f"   Trace 路径: {result.trace_path}")


def _run_research(
    *,
    county: str | None,
    focus: str | None,
    mode: str,
    historical: bool,
    long_history: bool,
    no_cache: bool,
    deep: bool = False,
    dry_run: bool,
) -> None:
    """执行产业研究(原 county-research 单命令逻辑)。"""
    # 校验 county(研究模式必填)
    if not county:
        click.echo("❌ 研究模式必须指定 --county / -c", err=True)
        click.echo("   示例: county-research --county 安吉县 --focus 竹产业", err=True)
        sys.exit(2)

    _print_banner()

    # 快捷开关:--historical → rise-fall; --long-history → long-history
    if historical:
        mode = "rise-fall"
    if long_history:
        mode = "long-history"
    # 别名归一:snapshot / industry 均为现状快照模式
    if mode == "industry":
        mode = "snapshot"

    from .config import get_settings
    settings = get_settings()

    click.echo(f"县名       : {county}")
    if focus:
        click.echo(f"研究方向   : {focus}")
    else:
        click.echo("研究方向   : 自动识别 (--focus 未指定)")
    click.echo(f"研究模式   : {mode}")
    click.echo(f"深度模式   : {'多智能体深度研究模式(反思+事实核验)' if deep else '标准模式'}")
    click.echo(f"缓存策略   : {'跳过缓存(强制刷新)' if no_cache else '启用缓存 TTL=' + str(settings.cache.ttl_hours) + 'h'}")
    click.echo(f"日志级别   : {settings.logging.level}")
    click.echo(f"数据目录   : {settings.data_dir}")
    click.echo(f"报告目录   : {settings.reports_dir}")
    click.echo()

    # dry-run:仅打印参数
    if dry_run:
        if mode == "rise-fall":
            focus_display = focus or "兴衰规律"
        elif mode == "long-history":
            focus_display = focus or "长周期兴衰史"
        else:
            focus_display = focus or "(自动识别)"
        click.echo("[dry-run] 请求参数校验通过,未实际执行 pipeline。")
        click.echo(f"[dry-run] 预期输出: {settings.reports_dir / f'{county}_{focus_display}_YYYYMMDD.md'}")
        sys.exit(0)

    # 构造请求 + pipeline(路径A Mock 兜底)
    options: dict[str, object] = {}
    if no_cache:
        options["no_cache"] = True
    if deep:
        options["deep_research"] = True
    request = ResearchRequest(county=county, focus=focus, mode=mode, options=options)

    pipeline = create_default_pipeline()

    try:
        report, report_path = pipeline.run(request)
    except CountyResearchAIError as e:
        click.echo(f"❌ Pipeline 失败: {e}", err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\n⚠  已被用户中断。", err=True)
        sys.exit(130)
    except Exception as e:  # noqa: BLE001
        click.echo(f"❌ 未预期错误: {e}", err=True)
        sys.exit(2)

    # 成功输出
    click.echo()
    click.echo("=" * 56)
    click.echo("✅ 研究报告生成成功!")
    click.echo(f"   章节数: {report.section_count}")
    click.echo(f"   报告路径: {report_path}")
    click.echo("=" * 56)
    click.echo()

    # 打印报告预览(首 8 行)
    try:
        preview_lines = Path(report_path).read_text(encoding="utf-8").splitlines()[:8]
        click.echo("📄 报告预览(前8行):")
        click.echo("---")
        for ln in preview_lines:
            click.echo(ln)
        click.echo("---")
    except Exception as e:  # noqa: BLE001
        click.echo(f"(预览失败: {e})")


if __name__ == "__main__":
    main()
