"""本地文件系统存储实现。

将 Storage 抽象接口落地为基于本地磁盘的 JSON 文件存储:
    - 原始数据:data/raw/{county}/{date}/raw_docs.json
    - 处理数据:data/processed/{county}/{focus}.json(可被 load_processed 用作缓存)
    - 报告文件:reports/{filename}

设计要点:
    1. 与 settings.storage 配置联动(raw_subdir / processed_subdir / archive_layout)
    2. 所有 I/O 错误统一抛 StorageError,携带 context 便于排错
    3. 目录创建幂等(parents=True, exist_ok=True)
    4. JSON 读写统一 UTF-8 编码,中文不转义
    5. load_processed 的 max_age_hours > 0 时,基于 mtime 检查时效

缓存策略:
    不引入独立缓存组件,直接以 processed 文件的 mtime 作为缓存时效判断依据。
    pipeline 在 settings.cache.enabled 时传入 ttl_hours 即可复用近期数据。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Settings, get_settings
from ..exceptions import StorageError
from ..models import ProcessedData, RawDoc
from .base import Storage

logger = logging.getLogger(__name__)


class LocalFSStorage(Storage):
    """本地文件系统存储实现。

    所有路径基于 settings.storage 与 settings.data_dir / settings.reports_dir 计算:
        - raw_root     = {data_dir}/{raw_subdir}
        - processed_root = {data_dir}/{processed_subdir}
        - reports_root = {reports_dir}
    """

    name = "local_fs"

    def __init__(self, settings: Settings | None = None) -> None:
        # 显式接收 settings 便于测试注入;默认读全局单例
        self._settings = settings or get_settings()
        s = self._settings.storage
        # 优先使用 storage.data_dir / storage.reports_dir(支持测试注入与配置覆盖),
        # 否则回退到 settings.data_dir / settings.reports_dir(由 config._resolve_paths 计算)
        data_root = Path(s.data_dir) if s.data_dir else self._settings.data_dir
        reports_root = Path(s.reports_dir) if s.reports_dir else self._settings.reports_dir
        self._raw_root = data_root / s.raw_subdir
        self._processed_root = data_root / s.processed_subdir
        self._reports_root = reports_root
        self._archive_layout = s.archive_layout

        # 启动时确保根目录存在(幂等)
        self._ensure_dirs()

    # ---- 公共接口实现 ----

    def save_raw(self, county: str, docs: list[RawDoc]) -> Path:
        """保存原始采集文档到 data/raw/{county}/{date}/raw_docs.json。"""
        try:
            target_dir = self._raw_archive_dir(county)
            target_dir.mkdir(parents=True, exist_ok=True)
            file_path = target_dir / "raw_docs.json"

            # 单独包装每个 RawDoc,使用 model_dump(mode="json") 确保 datetime 可序列化
            payload = [doc.model_dump(mode="json") for doc in docs]
            self._write_json(file_path, payload)
            logger.info(
                "原始数据已保存 | 县=%s | 文档数=%d | 路径=%s",
                county, len(docs), file_path,
            )
            return target_dir
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(
                f"保存原始数据失败: 县={county}",
                context={"county": county, "docs_count": len(docs), "error": str(e)},
            ) from e

    def load_raw(self, county: str) -> list[RawDoc]:
        """加载某县最近一次的原始文档(按日期目录排序取最新)。"""
        county_dir = self._raw_root / self._safe_name(county)
        if not county_dir.exists():
            logger.debug("原始数据目录不存在 | 县=%s | 路径=%s", county, county_dir)
            return []

        # 按 {date}/raw_docs.json 模式找最新
        candidates = sorted(
            county_dir.glob("*/raw_docs.json"),
            reverse=True,  # 按名称降序(日期字符串可 lex 排序)
        )
        if not candidates:
            return []

        latest = candidates[0]
        try:
            payload = self._read_json(latest)
            docs = [RawDoc(**item) for item in payload]
            logger.debug(
                "原始数据已加载 | 县=%s | 文档数=%d | 文件=%s",
                county, len(docs), latest.name,
            )
            return docs
        except Exception as e:
            raise StorageError(
                f"加载原始数据失败: 县={county} 文件={latest}",
                context={"county": county, "file": str(latest), "error": str(e)},
            ) from e

    def save_processed(self, county: str, focus: str, data: ProcessedData) -> Path:
        """保存清洗后数据到 data/processed/{county}/{focus}.json。"""
        try:
            county_dir = self._processed_root / self._safe_name(county)
            county_dir.mkdir(parents=True, exist_ok=True)
            file_path = county_dir / f"{self._safe_name(focus)}.json"

            # ProcessedData 内嵌 datetime 与 RawDoc,model_dump_json 已处理
            file_path.write_text(
                data.model_dump_json(indent=2),
                encoding="utf-8",
            )
            logger.info(
                "处理数据已保存 | 县=%s | 方向=%s | 字符数=%d | 路径=%s",
                county, focus, data.total_chars, file_path,
            )
            return file_path
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(
                f"保存处理数据失败: 县={county} 方向={focus}",
                context={"county": county, "focus": focus, "error": str(e)},
            ) from e

    def load_processed(
        self, county: str, focus: str, max_age_hours: int = 0
    ) -> ProcessedData | None:
        """加载清洗后数据(支持时效缓存检查)。

        Args:
            county: 县名
            focus: 研究方向
            max_age_hours: 时效阈值(小时);0 表示不检查时效

        Returns:
            ProcessedData 或 None(文件不存在或已过期)
        """
        file_path = self._processed_root / self._safe_name(county) / f"{self._safe_name(focus)}.json"
        if not file_path.exists():
            logger.debug(
                "处理数据不存在 | 县=%s | 方向=%s",
                county, focus,
            )
            return None

        # 时效检查
        if max_age_hours > 0:
            age_hours = self._file_age_hours(file_path)
            if age_hours > max_age_hours:
                logger.info(
                    "处理数据缓存已过期 | 县=%s | 方向=%s | 年龄=%.2fh | 阈值=%dh",
                    county, focus, age_hours, max_age_hours,
                )
                return None
            logger.debug(
                "处理数据缓存命中 | 县=%s | 方向=%s | 年龄=%.2fh",
                county, focus, age_hours,
            )

        try:
            payload = self._read_json(file_path)
            data = ProcessedData(**payload)
            return data
        except Exception as e:
            raise StorageError(
                f"加载处理数据失败: 县={county} 方向={focus} 文件={file_path}",
                context={"county": county, "focus": focus, "file": str(file_path), "error": str(e)},
            ) from e

    def save_report(self, filename: str, content: str) -> Path:
        """保存报告到 reports/{filename}。"""
        try:
            # 防止路径穿越:仅取文件名部分
            safe_name = Path(filename).name
            if not safe_name:
                raise StorageError(
                    "报告文件名为空",
                    context={"filename": filename},
                )
            file_path = self._reports_root / safe_name
            file_path.write_text(content, encoding="utf-8")
            logger.info("报告已写入: %s", file_path)
            return file_path
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(
                f"保存报告失败: filename={filename}",
                context={"filename": filename, "error": str(e)},
            ) from e

    # ---- 内部辅助 ----

    def _ensure_dirs(self) -> None:
        """启动时创建根目录(幂等)。"""
        try:
            self._raw_root.mkdir(parents=True, exist_ok=True)
            self._processed_root.mkdir(parents=True, exist_ok=True)
            self._reports_root.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise StorageError(
                "初始化存储目录失败",
                context={
                    "raw_root": str(self._raw_root),
                    "processed_root": str(self._processed_root),
                    "reports_root": str(self._reports_root),
                    "error": str(e),
                },
            ) from e

    def _raw_archive_dir(self, county: str) -> Path:
        """按 archive_layout 渲染归档子目录。

        默认 layout = "{county}/{date}",渲染为 data/raw/{county}/{YYYYMMDD}/
        """
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        try:
            sub = self._archive_layout.format(
                county=self._safe_name(county),
                date=date_str,
            )
        except KeyError as e:
            # layout 含未知占位符
            raise StorageError(
                f"archive_layout 模板渲染失败: 缺少字段 {e}",
                context={
                    "archive_layout": self._archive_layout,
                    "county": county,
                    "missing_field": str(e),
                },
            ) from e
        return self._raw_root / sub

    @staticmethod
    def _safe_name(name: str) -> str:
        """清洗路径组件,防止目录穿越与非法字符。

        Windows 禁用字符: \\ / : * ? " < > |
        替换为下划线;空字符串兜底为 'unnamed'。
        """
        if not name:
            return "unnamed"
        cleaned = name.strip().replace("/", "_").replace("\\", "_")
        for ch in (':', '*', '?', '"', '<', '>', '|'):
            cleaned = cleaned.replace(ch, "_")
        # 折叠连续下划线
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_") or "unnamed"

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        """写 JSON(UTF-8, 中文不转义, 缩进2)。"""
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> Any:
        """读 JSON(UTF-8)。"""
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _file_age_hours(path: Path) -> float:
        """基于 mtime 计算文件年龄(小时)。"""
        mtime = path.stat().st_mtime
        return (time.time() - mtime) / 3600
