"""LocalFSStorage 测试(基于 scripts/_verify_local_fs.py 规范化)。

使用 tmp_path 隔离,不污染项目 data/ 与 reports/。
覆盖: 保存/加载往返、缓存时效、路径穿越防护、非法字符清洗。
"""
from __future__ import annotations

import os
import time

import pytest

from county_research_ai.exceptions import StorageError
from county_research_ai.models import ProcessedData, RawDoc
from county_research_ai.storage.local_fs import LocalFSStorage

# ===== fixtures =====


@pytest.fixture
def storage(tmp_settings) -> LocalFSStorage:
    return LocalFSStorage(settings=tmp_settings)


def _make_docs(n: int = 2) -> list[RawDoc]:
    return [
        RawDoc(
            title=f"标题{i}",
            url=f"https://example.com/{i}",
            snippet=f"摘要{i}",
            content=f"正文内容{i}" * 10,
            source="mock",
        )
        for i in range(n)
    ]


# ===== save_raw / load_raw =====


class TestSaveLoadRaw:
    def test_save_raw_creates_archive_dir(self, storage):
        docs = _make_docs(3)
        archive_dir = storage.save_raw("安吉县", docs)
        assert archive_dir.exists()
        assert (archive_dir / "raw_docs.json").exists()

    def test_load_raw_roundtrip(self, storage):
        docs = _make_docs(3)
        storage.save_raw("安吉县", docs)
        loaded = storage.load_raw("安吉县")
        assert len(loaded) == 3
        assert loaded[0].title == "标题0"
        assert loaded[0].url == "https://example.com/0"
        assert loaded[0].source == "mock"

    def test_load_raw_missing_county_returns_empty(self, storage):
        result = storage.load_raw("不存在的县")
        assert result == []

    def test_load_raw_picks_latest_date(self, storage):
        """多次 save_raw 后 load_raw 应取最新日期目录。"""
        docs = _make_docs(1)
        storage.save_raw("安吉县", docs)
        time.sleep(0.01)
        storage.save_raw("安吉县", _make_docs(2))
        loaded = storage.load_raw("安吉县")
        assert len(loaded) == 2


# ===== save_processed / load_processed =====


class TestSaveLoadProcessed:
    def test_save_processed_creates_file(self, storage, sample_county):
        pd = ProcessedData(county=sample_county, focus="竹产业", docs=_make_docs(2), total_chars=200)
        path = storage.save_processed("安吉县", "竹产业", pd)
        assert path.exists()

    def test_load_processed_roundtrip(self, storage, sample_county):
        pd = ProcessedData(county=sample_county, focus="竹产业", docs=_make_docs(2), total_chars=200)
        storage.save_processed("安吉县", "竹产业", pd)
        loaded = storage.load_processed("安吉县", "竹产业", max_age_hours=0)
        assert loaded is not None
        assert loaded.focus == "竹产业"
        assert loaded.county.name == "安吉县"
        assert len(loaded.docs) == 2

    def test_load_processed_missing_returns_none(self, storage):
        result = storage.load_processed("不存在", "无方向", max_age_hours=0)
        assert result is None


# ===== 缓存时效 =====


class TestCacheTTL:
    def test_cache_hit_when_fresh(self, storage, sample_county):
        pd = ProcessedData(county=sample_county, focus="测试", docs=[], total_chars=0)
        storage.save_processed("时效县", "测试", pd)
        hit = storage.load_processed("时效县", "测试", max_age_hours=24)
        assert hit is not None

    def test_cache_expired_when_old(self, storage, sample_county):
        pd = ProcessedData(county=sample_county, focus="测试", docs=[], total_chars=0)
        storage.save_processed("时效县", "测试", pd)

        # 把 mtime 改到 48 小时前
        target = storage._processed_root / storage._safe_name("时效县") / f"{storage._safe_name('测试')}.json"
        old_mtime = target.stat().st_mtime
        os.utime(target, (old_mtime - 48 * 3600, old_mtime - 48 * 3600))

        miss = storage.load_processed("时效县", "测试", max_age_hours=24)
        assert miss is None

    def test_max_age_zero_skips_check(self, storage, sample_county):
        pd = ProcessedData(county=sample_county, focus="测试", docs=[], total_chars=0)
        storage.save_processed("时效县", "测试", pd)

        target = storage._processed_root / storage._safe_name("时效县") / f"{storage._safe_name('测试')}.json"
        old_mtime = target.stat().st_mtime
        os.utime(target, (old_mtime - 48 * 3600, old_mtime - 48 * 3600))

        # max_age_hours=0 不检查时效
        result = storage.load_processed("时效县", "测试", max_age_hours=0)
        assert result is not None


# ===== save_report =====


class TestSaveReport:
    def test_save_report_normal(self, storage):
        content = "# 测试报告\n\n正文内容"
        path = storage.save_report("test_report.md", content)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == content

    def test_save_report_path_traversal_protection(self, storage):
        """../../etc/passwd 应被清洗为纯文件名。"""
        path = storage.save_report("../../evil.md", "evil")
        assert path.parent == storage._reports_root
        assert path.name == "evil.md"

    def test_save_report_empty_filename_raises(self, storage):
        with pytest.raises(StorageError):
            storage.save_report("", "content")


# ===== 非法字符清洗 =====


class TestSanitizeName:
    def test_windows_illegal_chars_replaced(self, storage):
        county = "测试:县*名?"
        docs = _make_docs(1)
        archive_dir = storage.save_raw(county, docs)

        rel = archive_dir.relative_to(storage._raw_root)
        county_part = rel.parts[0]
        assert ":" not in county_part
        assert "*" not in county_part
        assert "?" not in county_part
        assert county_part == "测试_县_名"

    def test_load_raw_with_sanitized_name(self, storage):
        """保存时清洗了非法字符,加载时也应能找到。"""
        docs = _make_docs(1)
        storage.save_raw("测试:县", docs)
        loaded = storage.load_raw("测试:县")
        assert len(loaded) == 1

    def test_safe_name_static_method(self):
        assert LocalFSStorage._safe_name("正常名") == "正常名"
        assert LocalFSStorage._safe_name("a/b\\c") == "a_b_c"
        assert LocalFSStorage._safe_name("a**b") == "a_b"
        assert LocalFSStorage._safe_name("") == "unnamed"
        assert LocalFSStorage._safe_name("///") == "unnamed"
