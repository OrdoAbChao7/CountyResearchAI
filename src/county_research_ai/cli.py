"""命令行入口。

基于 Click 框架,提供 `county-research` 命令组。

注册方式:pyproject.toml 中 [project.scripts]
    county-research = "county_research_ai.cli:main"

调用方式(两种):

1. 产业研究(不指定子命令,等价于原 county-research 单命令行为):
    county-research --county 安吉县 --focus 竹产业
    county-research -c 鹤岗市 --mode rise-fall
    python -m county_research_ai --county 安吉县

2. 短视频内容生产(基于已有研究报告):
    county-research content -c 安吉县 -r reports/安吉县_竹产业_20260806.md
    county-research content -c 安吉县 -r <报告路径> --type short-video --dry-run

MVP 阶段使用 create_default_pipeline() 构造带 Mock 的 pipeline,
保证不填 API Key 也能完整跑通输入→报告链路。
"""
from __future__ import annotations

import sys
from pathlib import Path

import click

from .config import reset_settings
from .exceptions import CountyResearchAIError
from .models import ResearchRequest
from .agent.factory import create_default_agent
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
    dry_run: bool,
) -> None:
    """AI 县域产业研究助手 — 产业研究 + 短视频内容生产。

    \b
    子命令:
      content   基于研究报告生成短视频脚本内容包

    \b
    不指定子命令时,默认执行产业研究:
      county-research --county 安吉县 --focus 竹产业
      county-research -c 鹤岗市 --mode rise-fall
      county-research -c 信丰县 --long-history

    \b
    生成短视频脚本:
      county-research content -c 安吉县 -r reports/安吉县_竹产业_20260806.md
    """
    # 全局环境初始化(研究模式与 content 子命令共用)
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
            no_cache=no_cache, dry_run=dry_run,
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
@click.option("--no-trace", is_flag=True, default=False, help="不保存 Agent 执行轨迹")
@click.option("--dry-run", is_flag=True, default=False, help="只校验参数,不构造或运行 Agent")
def agent_command(
    county: str,
    focus: str | None,
    mode: str,
    max_steps: int,
    no_trace: bool,
    dry_run: bool,
) -> None:
    """运行可解释、可追踪的研究 Agent。"""
    mode = mode.lower()
    click.echo(f"Agent 县名   : {county}")
    click.echo(f"Agent 方向   : {focus or '(自动发现)'}")
    click.echo(f"Agent 模式   : {mode}")
    click.echo(f"最大步骤数   : {max_steps}")
    if dry_run:
        click.echo("[dry-run] Agent 参数校验通过,未构造或运行 Agent。")
        return

    request = ResearchRequest(county=county, focus=focus, mode=mode)
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


@main.command("content")
@click.option(
    "--county", "-c",
    required=True,
    type=str,
    help="县名,如 '安吉县'",
)
@click.option(
    "--report", "-r",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="研究报告路径(Markdown)",
)
@click.option(
    "--type", "content_type",
    type=click.Choice(["short-video"], case_sensitive=False),
    default="short-video",
    help="内容类型(第一阶段仅支持 short-video)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="仅打印参数,不实际执行内容流水线",
)
def content(
    county: str,
    report: str,
    content_type: str,
    dry_run: bool,
) -> None:
    """基于研究报告生成短视频脚本内容包。

    \b
    流程: 选题角度 → 60 秒脚本 → 事实核查 → 内容包(落盘)
    \b
    输出: content_outputs/{县名}/{日期}/{angle.json, script.md, fact_check.json, package.json}

    \b
    示例:
      county-research content -c 安吉县 -r reports/安吉县_竹产业_20260806.md
      county-research content -c 鹤岗市 -r reports/鹤岗市_兴衰规律_20260806.md --dry-run
    """
    _print_banner()
    click.echo("内容模式   : 短视频脚本生成")
    click.echo(f"县名       : {county}")
    click.echo(f"研究报告   : {report}")
    click.echo(f"内容类型   : {content_type}")
    click.echo()

    if dry_run:
        click.echo("[dry-run] 请求参数校验通过,未实际执行内容流水线。")
        click.echo(
            f"[dry-run] 预期输出: content_outputs/{county}/YYYYMMDD/"
            f"{{angle.json, script.md, fact_check.json, package.json}}"
        )
        return

    from .content import ContentPipeline

    pipe = ContentPipeline()
    try:
        package = pipe.produce(county=county, report_path=report)
    except FileNotFoundError as e:
        click.echo(f"❌ 研究报告不存在: {e}", err=True)
        sys.exit(1)
    except CountyResearchAIError as e:
        click.echo(f"❌ 内容生产失败: {e}", err=True)
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
    click.echo("✅ 短视频内容包生成成功!")
    click.echo(f"   角度 ID  : {package.angle.angle_id}")
    click.echo(f"   视频标题 : {package.script.title}")
    click.echo(f"   脚本段数 : {len(package.script.segments)}")
    click.echo(f"   旁白字数 : {package.script.total_word_count}")
    click.echo(f"   核查状态 : {package.fact_check.overall_status}")
    click.echo(f"   输出根目录: {pipe.output_root}")
    click.echo("=" * 56)
    click.echo()

    # 打印脚本预览(首 8 行)
    try:
        out_dir = pipe.output_root / package.county
        # 取最新日期目录
        date_dirs = sorted([d for d in out_dir.iterdir() if d.is_dir()], reverse=True)
        if date_dirs:
            script_path = date_dirs[0] / "script.md"
            if script_path.exists():
                preview_lines = script_path.read_text(encoding="utf-8").splitlines()[:8]
                click.echo("📄 脚本预览(前8行):")
                click.echo("---")
                for ln in preview_lines:
                    click.echo(ln)
                click.echo("---")
    except Exception as e:  # noqa: BLE001
        click.echo(f"(预览失败: {e})")


@main.command("story")
@click.option(
    "--county", "-c",
    required=True,
    type=str,
    help="县名,如 '信丰县'",
)
@click.option(
    "--report", "-r",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="研究报告路径(Markdown)",
)
def story(county: str, report: str) -> None:
    """从研究报告提炼故事线。

    \b
    流程: 研究报告 → StoryMiner → StoryLine(故事线)
    \b
    要求: 严禁编造人物、企业、年份、数据,所有内容必须来源于报告。

    \b
    示例:
      county-research story -c 信丰县 -r reports/信丰县_兴衰规律_20260806.md
    """
    _print_banner()
    click.echo("故事线提取模式")
    click.echo(f"县名       : {county}")
    click.echo(f"研究报告   : {report}")
    click.echo()

    from .content.story_miner import StoryMiner
    from pathlib import Path

    miner = StoryMiner()
    try:
        # 读取报告
        report_content = Path(report).read_text(encoding="utf-8")
        # 提取故事线
        story_line = miner.mine(county=county, report_content=report_content)
    except FileNotFoundError as e:
        click.echo(f"❌ 研究报告不存在: {e}", err=True)
        sys.exit(1)
    except CountyResearchAIError as e:
        click.echo(f"❌ 故事线提取失败: {e}", err=True)
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
    click.echo("✅ 故事线提取成功!")
    click.echo(f"   主线故事   : {story_line.main_story[:100]}...")
    click.echo(f"   时间跨度   : {story_line.time_span}")
    click.echo(f"   冲突类型   : {story_line.conflict_type}")
    click.echo(f"   关键人物   : {len(story_line.characters)} 个")
    click.echo(f"   关键企业   : {len(story_line.enterprises)} 个")
    click.echo(f"   关键事件   : {len(story_line.events)} 个")
    click.echo(f"   关键数据   : {len(story_line.data_points)} 个")
    click.echo("=" * 56)
    click.echo()

    # 输出 JSON(便于保存)
    click.echo("📄 StoryLine JSON:")
    click.echo("---")
    click.echo(story_line.model_dump_json(indent=2))
    click.echo("---")


@main.command("topic")
@click.option(
    "--top", "top_n",
    default=10,
    type=int,
    help="返回前 N 个选题候选(默认 10)",
)
def topic(top_n: int) -> None:
    """从本地研究数据库发现选题候选。

    \b
    流程: 扫描 reports/ → TopicAgent → Top N 候选
    \b
    要求: 第一版不联网,仅基于已有研究报告数据库。

    \b
    示例:
      county-research topic --top 10
    """
    _print_banner()
    click.echo("选题发现模式")
    click.echo(f"Top N      : {top_n}")
    click.echo()

    from .content.topic_agent import TopicAgent

    agent = TopicAgent()
    try:
        candidates = agent.discover(top_n=top_n)
    except CountyResearchAIError as e:
        click.echo(f"❌ 选题发现失败: {e}", err=True)
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
    click.echo(f"✅ 发现 {len(candidates)} 个选题候选!")
    click.echo("=" * 56)
    click.echo()

    # 打印候选列表
    for i, candidate in enumerate(candidates, 1):
        click.echo(f"{i}. {candidate.county} - {candidate.core_industry}")
        click.echo(f"   评分: {candidate.score:.1f}")
        click.echo(f"   历史反差: {candidate.historical_contrast}")
        click.echo(f"   兴衰模式: {candidate.rise_fall_pattern}")
        click.echo(f"   推荐理由: {candidate.reason}")
        click.echo(f"   报告路径: {candidate.report_path}")
        click.echo()


def _run_research(
    *,
    county: str | None,
    focus: str | None,
    mode: str,
    historical: bool,
    long_history: bool,
    no_cache: bool,
    dry_run: bool,
) -> None:
    """执行产业研究(原 county-research 单命令逻辑)。"""
    # 校验 county(研究模式必填)
    if not county:
        click.echo("❌ 研究模式必须指定 --county / -c", err=True)
        click.echo("   示例: county-research --county 安吉县 --focus 竹产业", err=True)
        click.echo("   或生成短视频: county-research content -c 安吉县 -r <报告路径>", err=True)
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
