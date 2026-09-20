"""内容生产流水线验证:director + script_generator + fact_checker + pipeline。

用注入的 MockLLMClient(返回 content 相关 JSON)跑通完整链路,不依赖真实 API。

覆盖:
    1. PromptLoader 加载 3 个新模板(content_director/short_video_script/fact_check)
    2. ContentDirector.generate_angle 生成选题角度
    3. ScriptGenerator.generate_script 生成 5 段脚本
    4. FactChecker.check 事实核查(含 supported/needs_revision 推断)
    5. ContentPipeline.produce 全流程 + 落盘 4 文件
    6. 落盘文件可读回(JSON / Markdown)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from county_research_ai.config import get_settings, reset_settings
from county_research_ai.content import (
    ContentDirector,
    ContentPipeline,
    FactChecker,
    ScriptGenerator,
)
from county_research_ai.llm.base import LLMClient, LLMResponse
from county_research_ai.llm.prompt_loader import PromptLoader


# 一份假的研究报告(供 director/fact_checker 使用)
fake_REPORT = """# 安吉县竹产业兴衰规律研究报告

## 起家产业
安吉县 1980 年代起依托竹林资源起家,全县竹林面积 100 万亩。

## 兴起因子
- 资源禀赋:竹林面积全国前列
- 政策支持:1990 年代列入省级林业重点县

## 衰落因子
- 同质化竞争加剧,竹制品利润率从 15% 降至 5%
- 2015 年后部分竹加工企业外迁

## 兴衰模型
pattern_type: market_cycle
summary: 安吉竹产业经历资源起家、规模扩张、利润压缩三阶段,属市场周期型。

## 关键数据
- 竹林面积:100 万亩
- 1990 年代竹制品产值占工业 35%
- 2015 年后利润率从 15% 降至 5%
"""


class ContentMockLLM(LLMClient):
    """内容流水线 Mock:根据 prompt 内容返回对应 JSON。"""

    name = "content-mock-llm"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        user_msg = messages[-1].get("content", "") if messages else ""
        if "策划" in user_msg and "选题角度" in user_msg:
            content = json.dumps({
                "angle_id": "market-cycle-bamboo",
                "title": "安吉竹产业:从100万亩到利润5%",
                "hook": "一座县靠竹子起家,30 年后利润率只剩三分之一。",
                "perspective": "从市场周期模型切入,对比 1990 年代扩张期与 2015 年后利润压缩期。",
                "target_audience": "关注下沉市场与农业产业的创业者",
                "key_points": [
                    "竹林面积 100 万亩",
                    "1990 年代产值占工业 35%",
                    "2015 年后利润率从 15% 降至 5%",
                    "属市场周期型兴衰模型",
                ],
                "tone": "冷静叙事",
                "source_refs": ["研究报告 · 兴起因子", "研究报告 · 衰落因子"],
            }, ensure_ascii=False)
        elif "60 秒短视频脚本" in user_msg or "撰写 60 秒" in user_msg:
            content = json.dumps({
                "angle_id": "market-cycle-bamboo",
                "title": "安吉竹产业:从100万亩到利润5%",
                "duration_seconds": 60,
                "segments": [
                    {
                        "segment_id": "hook", "time_range": "0-5s",
                        "narration": "一座县靠竹子起家,30 年后利润率只剩三分之一。",
                        "on_screen": "安吉 · 竹产业",
                        "visual_hint": "竹林航拍切到加工厂关闭画面",
                        "source_refs": ["研究报告 · 兴衰模型"],
                    },
                    {
                        "segment_id": "origin", "time_range": "5-20s",
                        "narration": "1980 年代安吉依托 100 万亩竹林起家,1990 年代竹制品产值占到全县工业的 35%。",
                        "on_screen": "竹林 100 万亩 / 产值占工业 35%",
                        "visual_hint": "老照片:80 年代竹林与加工厂",
                        "source_refs": ["研究报告 · 起家产业", "研究报告 · 兴起因子"],
                    },
                    {
                        "segment_id": "growth", "time_range": "20-40s",
                        "narration": "1990 年代列入省级林业重点县,政策与资源双重加持,竹制品产业链从原竹扩展到地板、家具、造纸,形成完整链条。",
                        "on_screen": "1990 年代 省级林业重点县",
                        "visual_hint": "竹制品产业链扩张时间线",
                        "source_refs": ["研究报告 · 兴起因子"],
                    },
                    {
                        "segment_id": "decline", "time_range": "40-55s",
                        "narration": "2015 年后,同质化竞争加剧,竹制品利润率从 15% 降到 5%,部分加工企业外迁。",
                        "on_screen": "2015 年后 利润率 15% → 5%",
                        "visual_hint": "利润率曲线下滑 + 外迁企业新闻",
                        "source_refs": ["研究报告 · 衰落因子"],
                    },
                    {
                        "segment_id": "takeaway", "time_range": "55-60s",
                        "narration": "资源起家、规模扩张、利润压缩——这是市场周期型县域的典型轨迹。",
                        "on_screen": "market_cycle · 市场周期型",
                        "visual_hint": "安吉在地图上标注 + 周期模型图",
                        "source_refs": ["研究报告 · 兴衰模型"],
                    },
                ],
            }, ensure_ascii=False)
        elif "事实核查" in user_msg or "核查" in user_msg:
            content = json.dumps({
                "angle_id": "market-cycle-bamboo",
                "items": [
                    {
                        "claim": "竹林面积 100 万亩",
                        "segment_id": "origin",
                        "evidence": "研究报告 · 起家产业:全县竹林面积 100 万亩",
                        "verdict": "supported",
                        "note": "",
                    },
                    {
                        "claim": "1990 年代竹制品产值占工业 35%",
                        "segment_id": "origin",
                        "evidence": "研究报告 · 关键数据:1990 年代竹制品产值占工业 35%",
                        "verdict": "supported",
                        "note": "",
                    },
                    {
                        "claim": "2015 年后利润率从 15% 降至 5%",
                        "segment_id": "decline",
                        "evidence": "研究报告 · 衰落因子:2015 年后利润率从 15% 降至 5%",
                        "verdict": "supported",
                        "note": "",
                    },
                    {
                        "claim": "列入省级林业重点县",
                        "segment_id": "growth",
                        "evidence": "研究报告 · 兴起因子:1990 年代列入省级林业重点县",
                        "verdict": "supported",
                        "note": "",
                    },
                ],
                "overall_status": "ok",
            }, ensure_ascii=False)
        else:
            content = "{}"
        return LLMResponse(
            content=content, model="content-mock-v1",
            prompt_tokens=600, completion_tokens=900, total_tokens=1500,
        )


def main() -> int:
    failures: list[str] = []
    reset_settings()
    settings = get_settings()

    # 用临时目录承接 content_outputs,不污染项目
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        report_path = tmp_dir / "安吉县_竹产业_20260806.md"
        report_path.write_text(fake_REPORT, encoding="utf-8")

        # ---- 1. 3 个新模板存在 ----
        try:
            loader = PromptLoader(settings=settings)
            assert loader.has_template("content_director"), "content_director.md 应存在"
            assert loader.has_template("short_video_script"), "short_video_script.md 应存在"
            assert loader.has_template("fact_check"), "fact_check.md 应存在"
            # 渲染验证
            r = loader.render("content_director", county="安吉县", report_content="xxx")
            assert "安吉县" in r and "选题角度" in r
            print("[OK] 1. 3 个新模板存在 + 可渲染")
        except Exception as e:
            failures.append(f"templates: {type(e).__name__}: {e}")
            print(f"[FAIL] 1. {type(e).__name__}: {e}")

        # ---- 2. ContentDirector.generate_angle ----
        try:
            mock = ContentMockLLM()
            director = ContentDirector(llm=mock, prompt_loader=loader, settings=settings)
            angle = director.generate_angle(county="安吉县", report_content=fake_REPORT)
            assert angle.angle_id == "market-cycle-bamboo"
            assert "安吉" in angle.title
            assert len(angle.key_points) == 4
            assert angle.source_refs
            print(f"[OK] 2. director | angle_id={angle.angle_id} | points={len(angle.key_points)}")
        except Exception as e:
            import traceback; traceback.print_exc()
            failures.append(f"director: {type(e).__name__}: {e}")
            print(f"[FAIL] 2. {type(e).__name__}: {e}")

        # ---- 3. ScriptGenerator.generate_script ----
        try:
            mock2 = ContentMockLLM()
            gen = ScriptGenerator(llm=mock2, prompt_loader=loader, settings=settings)
            script = gen.generate_script(county="安吉县", angle=angle)
            assert len(script.segments) == 5, f"应有 5 段, 实际 {len(script.segments)}"
            ids = [s.segment_id for s in script.segments]
            assert ids == ["hook", "origin", "growth", "decline", "takeaway"], \
                f"段位顺序错误: {ids}"
            assert script.total_word_count > 0
            assert all(s.narration for s in script.segments)
            print(f"[OK] 3. script_generator | segments={len(script.segments)} | words={script.total_word_count}")
        except Exception as e:
            import traceback; traceback.print_exc()
            failures.append(f"script_generator: {type(e).__name__}: {e}")
            print(f"[FAIL] 3. {type(e).__name__}: {e}")

        # ---- 4. FactChecker.check ----
        try:
            mock3 = ContentMockLLM()
            checker = FactChecker(llm=mock3, prompt_loader=loader, settings=settings)
            result = checker.check(
                county="安吉县", script=script, report_content=fake_REPORT,
            )
            assert len(result.items) == 4
            assert all(it.verdict == "supported" for it in result.items)
            assert result.overall_status == "ok", f"overall 应为 ok, 实际 {result.overall_status}"
            print(f"[OK] 4. fact_checker | items={len(result.items)} | status={result.overall_status}")
        except Exception as e:
            import traceback; traceback.print_exc()
            failures.append(f"fact_checker: {type(e).__name__}: {e}")
            print(f"[FAIL] 4. {type(e).__name__}: {e}")

        # ---- 5. ContentPipeline.produce + 落盘 ----
        try:
            # 重定向输出根目录到临时目录,不污染项目
            pipe = ContentPipeline(
                director=ContentDirector(llm=ContentMockLLM(), prompt_loader=loader, settings=settings),
                script_generator=ScriptGenerator(llm=ContentMockLLM(), prompt_loader=loader, settings=settings),
                fact_checker=FactChecker(llm=ContentMockLLM(), prompt_loader=loader, settings=settings),
                settings=settings,
            )
            pipe._output_root = tmp_dir / "content_outputs"  # type: ignore[attr-defined]
            pkg = pipe.produce(county="安吉县", report_path=str(report_path))
            assert pkg.angle.angle_id == "market-cycle-bamboo"
            assert pkg.fact_check.overall_status == "ok"

            # 验证 4 个落盘文件
            date_dirs = list((tmp_dir / "content_outputs" / "安吉县").iterdir())
            assert len(date_dirs) == 1, f"应有 1 个日期目录, 实际 {len(date_dirs)}"
            out_dir = date_dirs[0]
            for fname in ("angle.json", "script.md", "fact_check.json", "package.json"):
                assert (out_dir / fname).exists(), f"{fname} 应存在"
            print(f"[OK] 5. pipeline.produce + 落盘 | dir={out_dir.name} | files=4")

            # ---- 6. 落盘文件可读回 ----
            angle_data = json.loads((out_dir / "angle.json").read_text(encoding="utf-8"))
            assert angle_data["angle_id"] == "market-cycle-bamboo"
            fc_data = json.loads((out_dir / "fact_check.json").read_text(encoding="utf-8"))
            assert fc_data["overall_status"] == "ok"
            pkg_data = json.loads((out_dir / "package.json").read_text(encoding="utf-8"))
            assert pkg_data["county"] == "安吉县"
            assert len(pkg_data["script"]["segments"]) == 5
            script_md = (out_dir / "script.md").read_text(encoding="utf-8")
            assert "安吉竹产业" in script_md
            assert "0-5s" in script_md and "55-60s" in script_md
            print(f"[OK] 6. 落盘文件可读回 | angle_id={angle_data['angle_id']} | md_len={len(script_md)}")
        except Exception as e:
            import traceback; traceback.print_exc()
            failures.append(f"pipeline: {type(e).__name__}: {e}")
            print(f"[FAIL] 5/6. {type(e).__name__}: {e}")

    # ---- 总结 ----
    print()
    if failures:
        print(f"❌ {len(failures)} 项失败:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("✅ 内容生产流水线全部 6 项测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
