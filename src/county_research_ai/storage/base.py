"""存储层抽象接口。

定义 Storage 抽象基类,所有存储实现(本地文件系统 / 未来数据库)实现此接口。
pipeline 通过统一接口读写数据,实现存储后端可替换:
切换存储后端只需替换 Storage 实现,不动 pipeline。

实现方参考:
    - local_fs.py  本地文件系统实现
    - cache.py     缓存逻辑(load_processed 的 max_age_hours 已内置时效检查)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import ProcessedData, RawDoc


class Storage(ABC):
    """存储抽象基类。

    覆盖数据全生命周期:
        - 原始数据:save_raw / load_raw(采集层 → 存储)
        - 处理数据:save_processed / load_processed(存储 → LLM,含时效缓存)
        - 报告:save_report(报告输出)

    约定:
        - 文件读写异常抛出 StorageError(见 exceptions.py)
        - load_* 在数据不存在时返回 None / 空列表,不抛异常
        - load_processed 的 max_age_hours > 0 时,过期视为缓存未命中返回 None
          (实现方根据文件 mtime 判断时效,无需独立缓存组件)
    """

    @abstractmethod
    def save_raw(self, county: str, docs: list[RawDoc]) -> Path:
        """保存原始采集文档。

        按 settings.storage.archive_layout 归档,通常为 data/raw/{county}/{date}/。

        Args:
            county: 县名(用作归档子目录)
            docs: 原始文档列表

        Returns:
            归档目录路径

        Raises:
            StorageError: 写入失败
        """
        ...

    @abstractmethod
    def load_raw(self, county: str) -> list[RawDoc]:
        """加载某县最近一次的原始文档。

        Args:
            county: 县名

        Returns:
            RawDoc 列表(不存在则返回空列表)
        """
        ...

    @abstractmethod
    def save_processed(self, county: str, focus: str, data: ProcessedData) -> Path:
        """保存清洗后数据。

        通常存为 data/processed/{county}/{focus}.json。

        Args:
            county: 县名
            focus: 研究方向
            data: 处理后数据

        Returns:
            保存文件路径

        Raises:
            StorageError: 写入失败
        """
        ...

    @abstractmethod
    def load_processed(
        self, county: str, focus: str, max_age_hours: int = 0
    ) -> ProcessedData | None:
        """加载清洗后数据(支持时效检查)。

        作为缓存的实现:若 max_age_hours > 0 且文件 mtime 超过该时长,
        视为缓存过期返回 None,触发 pipeline 重新采集。

        Args:
            county: 县名
            focus: 研究方向
            max_age_hours: 时效阈值(小时);0 表示不检查时效

        Returns:
            ProcessedData 或 None(不存在 / 已过期)
        """
        ...

    @abstractmethod
    def save_report(self, filename: str, content: str) -> Path:
        """保存报告文件。

        存储到 settings.reports_dir(默认 reports/)。

        Args:
            filename: 文件名(不含路径,如 "安吉县_竹产业_20260805.md")
            content: Markdown 内容

        Returns:
            报告文件完整路径

        Raises:
            StorageError: 写入失败
        """
        ...
