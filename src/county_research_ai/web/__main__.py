"""``county-research-web`` 启动入口。"""
from __future__ import annotations

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="county-research-web",
        description="启动 CountyResearchAI Web 服务",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="监听地址（默认取 COUNTY_WEB_HOST 或 127.0.0.1）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="监听端口（默认取 COUNTY_WEB_PORT 或 8000）",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="开发模式：代码变更时自动重载",
    )
    args = parser.parse_args(argv)

    # 延迟导入：未安装 web extra 时，仅 --help 不应报 ImportError。
    from .settings import WebSettings

    web_settings = WebSettings.from_env()

    import uvicorn

    # P0/P1 必须单进程：运行注册表与线程池都在进程内。
    uvicorn.run(
        "county_research_ai.web.app:create_app",
        factory=True,
        host=args.host or web_settings.host,
        port=args.port or web_settings.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
