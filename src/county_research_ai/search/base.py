"""数据采集层抽象接口。

定义 SearchProvider 抽象基类,所有数据源(Tavily / Serper / Bing / gov)实现此接口。
collector.py 通过统一接口协调多个 provider,实现数据源可插拔:
新增数据源只需实现 SearchProvider,无需改动 collector 与上层。

实现方参考:
    - web_search.py  通用网络搜索(Tavily/Serper/Bing)
    - gov_data.py    政府公开数据(白名单域名抓取)
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import RawDoc


class SearchProvider(ABC):
    """数据采集 provider 抽象基类。

    实现方需提供:
        - name: provider 标识(用于日志、去重、缓存键)
        - search(): 执行搜索,返回 RawDoc 列表

    约定:
        - 网络/鉴权/超时错误应抛出 SearchError(见 exceptions.py)
        - 无匹配结果返回空列表,不抛异常
        - 实现方自行处理重试(参考 settings.search.retry)
        - 是否抓取详情页由实现方根据 settings.search.fetch_detail 决定
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """provider 标识,如 'tavily' / 'serper' / 'gov'。"""
        ...

    @abstractmethod
    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        """执行搜索查询。

        Args:
            query: 搜索关键词(已由 collector 填充县名/方向)
            max_results: 最大返回条数

        Returns:
            RawDoc 列表(可能为空)

        Raises:
            SearchError: 网络/鉴权/超时等错误
        """
        ...
