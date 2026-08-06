"""命令行入口。

基于 Click 框架,提供 county-research 命令。

注册方式:pyproject.toml 中 [project.scripts]
    county-research = "county_research_ai.cli:main"

调用方式:
    county-research --county 安吉县 --focus 竹产业
    python -m county_research_ai --county 安吉县 --focus 竹产业

MVP 阶段使用 create_default_pipeline() 构造带 Mock 的 pipeline,
保证不填 API Key 也能完整跑通输入→报告链路。
后续真实实现完成后,通过 --mode 参数(或默认真实模式)切换即可。
"""
from __future__ import annotations

import sys
from pathlib import Path

import click

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


@click.command(
    "county-research",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--county", "-c",
    required=True,
    type=str,
    help="县名,如 '安吉县' 或 '浙江省湖州市安吉县'",
)
@click.option(
    "--focus", "-f",
    required=False,
    type=str,
    default=None,
    help="研究方向,如 '竹产业' / '乡村旅游' / '装备制造'。留空则自动识别该县重点产业",
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
def main(
    county: str,
    focus: str,
    log_level: str | None,
    no_cache: bool,
    dry_run: bool,
) -> None:
    """生成指定县 + 研究方向的产业研究报告(Markdown)。

    \b
    示例:
      county-research --county 安吉县 --focus 竹产业
      county-research -c 安吉县 -f 竹产业 --no-cache
      county-research -c 安吉县 --dry-run
      county-research -c 安吉县    # 自动识别该县重点产业方向
    """
    _print_banner()

    # 强制重载配置(让 --log-level 覆盖生效)
    reset_settings()
    if log_level:
        import os
        os.environ["LOG_LEVEL"] = log_level

    # 日志初始化(必须在 get_settings 之前: setup_logging 内部读 settings)
    setup_logging()

    # 再次读取配置(含 --no-cache 对 options 的注入等)
    from .config import get_settings
    settings = get_settings()

    click.echo(f"县名       : {county}")
    if focus:
        click.echo(f"研究方向   : {focus}")
    else:
        click.echo("研究方向   : 自动识别 (--focus 未指定)")
    click.echo(f"缓存策略   : {'跳过缓存(强制刷新)' if no_cache else '启用缓存 TTL=' + str(settings.cache.ttl_hours) + 'h'}")
    click.echo(f"日志级别   : {settings.logging.level}")
    click.echo(f"数据目录   : {settings.data_dir}")
    click.echo(f"报告目录   : {settings.reports_dir}")
    click.echo()

    # dry-run:仅打印参数
    if dry_run:
        focus_display = focus or "(自动识别)"
        click.echo("[dry-run] 请求参数校验通过,未实际执行 pipeline。")
        click.echo(f"[dry-run] 预期输出: {settings.reports_dir / f'{county}_{focus_display}_YYYYMMDD.md'}")
        sys.exit(0)

    # 构造请求 + pipeline(路径A Mock 兜底)
    options: dict[str, object] = {}
    if no_cache:
        options["no_cache"] = True
    request = ResearchRequest(county=county, focus=focus, options=options)

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
