"""LocalFSStorage 专项验证。

使用临时目录隔离,不污染项目 data/ 与 reports/。
覆盖:
    1. save_raw + load_raw 往返一致性
    2. save_processed + load_processed 往返一致性
    3. load_processed 缓存时效(max_age_hours)
    4. save_report 写入 + 路径穿越防护
    5. load_raw 不存在时返回空列表
    6. load_processed 不存在时返回 None
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

# 让 src 在 PYTHONPATH 中
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from county_research_ai.config import Settings, StorageConfig, CacheConfig
from county_research_ai.exceptions import StorageError
from county_research_ai.models import CountyInfo, ProcessedData, RawDoc
from county_research_ai.storage.local_fs import LocalFSStorage


def make_settings(tmp: Path) -> Settings:
    """构造使用临时目录的 Settings。"""
    return Settings(
        storage=StorageConfig(
            data_dir=str(tmp / "data"),
            reports_dir=str(tmp / "reports"),
            raw_subdir="raw",
            processed_subdir="processed",
            archive_layout="{county}/{date}",
        ),
        cache=CacheConfig(enabled=True, ttl_hours=24),
    )


def make_docs(n: int = 2) -> list[RawDoc]:
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


def main() -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="cra_test_") as td:
        tmp = Path(td)
        settings = make_settings(tmp)
        storage = LocalFSStorage(settings=settings)

        # ---- 测试 1: save_raw + load_raw 往返 ----
        try:
            county = "安吉县"
            docs = make_docs(3)
            archive_dir = storage.save_raw(county, docs)
            assert archive_dir.exists(), f"归档目录未创建: {archive_dir}"
            assert (archive_dir / "raw_docs.json").exists(), "raw_docs.json 未创建"
            loaded = storage.load_raw(county)
            assert len(loaded) == 3, f"加载条数错误: {len(loaded)}"
            assert loaded[0].title == "标题0", f"标题错误: {loaded[0].title}"
            print(f"[OK] 1. save_raw/load_raw 往返一致 | docs={len(loaded)} | dir={archive_dir.name}")
        except Exception as e:
            failures.append(f"save_raw/load_raw: {type(e).__name__}: {e}")
            print(f"[FAIL] 1. save_raw/load_raw: {type(e).__name__}: {e}")

        # ---- 测试 2: load_raw 不存在返回空列表 ----
        try:
            result = storage.load_raw("不存在的县")
            assert result == [], f"应返回空列表, 实际: {result}"
            print(f"[OK] 2. load_raw 不存在 → 空列表")
        except Exception as e:
            failures.append(f"load_raw missing: {type(e).__name__}: {e}")
            print(f"[FAIL] 2. load_raw missing: {type(e).__name__}: {e}")

        # ---- 测试 3: save_processed + load_processed 往返 ----
        try:
            county = "安吉县"
            focus = "竹产业"
            ci = CountyInfo.from_name(county)
            pd = ProcessedData(
                county=ci, focus=focus, docs=make_docs(2), total_chars=200,
            )
            file_path = storage.save_processed(county, focus, pd)
            assert file_path.exists(), f"processed 文件未创建: {file_path}"
            loaded = storage.load_processed(county, focus, max_age_hours=0)
            assert loaded is not None, "load_processed 返回 None"
            assert loaded.focus == focus, f"focus 不匹配: {loaded.focus}"
            assert loaded.county.name == county, f"county 不匹配: {loaded.county.name}"
            assert len(loaded.docs) == 2, f"docs 数量错误: {len(loaded.docs)}"
            print(f"[OK] 3. save_processed/load_processed 往返一致 | docs={len(loaded.docs)}")
        except Exception as e:
            failures.append(f"save_processed/load_processed: {type(e).__name__}: {e}")
            print(f"[FAIL] 3. save_processed/load_processed: {type(e).__name__}: {e}")

        # ---- 测试 4: load_processed 缓存时效 ----
        try:
            county = "时效县"
            focus = "测试"
            ci = CountyInfo.from_name(county)
            pd = ProcessedData(county=ci, focus=focus, docs=[], total_chars=0)
            storage.save_processed(county, focus, pd)

            # 刚写入,24h 阈值应命中
            hit = storage.load_processed(county, focus, max_age_hours=24)
            assert hit is not None, "刚写入应命中缓存"
            print(f"[OK] 4a. 缓存命中(刚写入,阈值24h)")

            # 把 mtime 改到 48 小时前,24h 阈值应过期
            import os
            target_file = storage._processed_root / storage._safe_name(county) / f"{storage._safe_name(focus)}.json"
            old_mtime = target_file.stat().st_mtime
            os.utime(target_file, (old_mtime - 48 * 3600, old_mtime - 48 * 3600))
            miss = storage.load_processed(county, focus, max_age_hours=24)
            assert miss is None, f"48h前写入应过期, 实际: {miss}"
            print(f"[OK] 4b. 缓存过期(48h前写入,阈值24h)")

            # max_age_hours=0 应不检查时效,即使旧文件也返回
            no_check = storage.load_processed(county, focus, max_age_hours=0)
            assert no_check is not None, "max_age_hours=0 应跳过时效检查"
            print(f"[OK] 4c. max_age_hours=0 跳过时效检查")
        except Exception as e:
            failures.append(f"cache TTL: {type(e).__name__}: {e}")
            print(f"[FAIL] 4. cache TTL: {type(e).__name__}: {e}")

        # ---- 测试 5: load_processed 不存在返回 None ----
        try:
            result = storage.load_processed("不存在的县", "无方向", max_age_hours=0)
            assert result is None, f"应返回 None, 实际: {result}"
            print(f"[OK] 5. load_processed 不存在 → None")
        except Exception as e:
            failures.append(f"load_processed missing: {type(e).__name__}: {e}")
            print(f"[FAIL] 5. load_processed missing: {type(e).__name__}: {e}")

        # ---- 测试 6: save_report 写入 + 路径穿越防护 ----
        try:
            content = "# 测试报告\n\n正文内容"
            path = storage.save_report("test_report.md", content)
            assert path.exists(), f"报告未创建: {path}"
            assert path.read_text(encoding="utf-8") == content, "内容不一致"
            print(f"[OK] 6a. save_report 正常写入 | path={path.name}")

            # 路径穿越防护:../../etc/passwd 应被清洗为文件名
            evil_path = storage.save_report("../../evil.md", "evil")
            assert evil_path.parent == storage._reports_root, f"路径穿越未防护: {evil_path}"
            assert evil_path.name == "evil.md", f"文件名清洗错误: {evil_path.name}"
            print(f"[OK] 6b. 路径穿越防护生效 | 实际路径={evil_path.name}")
        except Exception as e:
            failures.append(f"save_report: {type(e).__name__}: {e}")
            print(f"[FAIL] 6. save_report: {type(e).__name__}: {e}")

        # ---- 测试 7: 非法字符清洗 ----
        try:
            # 含 Windows 非法字符的县名
            county = "测试:县*名?"
            docs = make_docs(1)
            archive_dir = storage.save_raw(county, docs)
            # 检查清洗后的县名段(取 raw_root 下的第一级子目录名)
            rel = archive_dir.relative_to(storage._raw_root)
            county_part = rel.parts[0]  # 第一段是县名
            assert ":" not in county_part, f"冒号未清洗: {county_part}"
            assert "*" not in county_part, f"星号未清洗: {county_part}"
            assert "?" not in county_part, f"问号未清洗: {county_part}"
            assert county_part == "测试_县_名", f"清洗结果不符预期: {county_part}"
            loaded = storage.load_raw(county)
            assert len(loaded) == 1, f"加载非法字符县名失败: {len(loaded)}"
            print(f"[OK] 7. 非法字符清洗 | 清洗后={county_part}")
        except Exception as e:
            failures.append(f"sanitize: {type(e).__name__}: {e}")
            print(f"[FAIL] 7. sanitize: {type(e).__name__}: {e}")

    # ---- 总结 ----
    print()
    if failures:
        print(f"❌ {len(failures)} 项失败:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("✅ LocalFSStorage 全部 7 项测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
