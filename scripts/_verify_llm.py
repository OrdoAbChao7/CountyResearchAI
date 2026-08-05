"""LLM 层验证:prompt_loader + analyzer(用 MockLLMClient 注入,不依赖真实 API)。

覆盖:
    1. PromptLoader 加载真实 prompts/ 模板
    2. PromptLoader.render 渲染变量
    3. PromptLoader.has_template 预检
    4. PromptLoader.render_string fallback
    5. LLMAnalyzer.analyze 全流程(4 个 task)
    6. LLMAnalyzer.generate_summary
    7. task → 模板映射(industry_status/recommendations 用模板,advantages/shortcomings 用 fallback)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from county_research_ai.config import get_settings, reset_settings
from county_research_ai.llm.analyzer import LLMAnalyzer, TaskConfig
from county_research_ai.llm.base import LLMClient, LLMResponse
from county_research_ai.llm.prompt_loader import PromptLoader
from county_research_ai.models import (
    AnalysisResult, CountyInfo, ProcessedData, RawDoc,
)
from typing import Any


class TestMockLLM(LLMClient):
    """记录调用次数的 Mock LLM,用于验证 analyzer 调用链。"""

    name = "test-mock-llm"

    def __init__(self) -> None:
        self.call_count = 0
        self.calls: list[str] = []  # 记录每次调用的 prompt 前 80 字符

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1
        user_msg = messages[-1].get("content", "") if messages else ""
        self.calls.append(user_msg)  # 存完整 prompt 便于断言
        # 根据 prompt 内容返回不同分析文本
        if "优势" in user_msg:
            content = "## 核心优势\n1. 资源禀赋突出\n2. 产业基础扎实"
        elif "短板" in user_msg or "风险" in user_msg:
            content = "## 主要短板\n1. 精深加工不足\n2. 品牌辨识度弱"
        elif "建议" in user_msg or "对策" in user_msg:
            content = "## 建议\n短期:技改补贴\n中期:品牌建设"
        elif "摘要" in user_msg or "执行摘要" in user_msg or "关键发现" in user_msg:
            content = "该县该产业已形成完整链条,处于成长期后期,建议补强精深加工。"
        else:
            content = "## 产业概况\n该县该产业产值120亿,规上企业82家。"
        return LLMResponse(
            content=content,
            model="test-mock-v1",
            prompt_tokens=500,
            completion_tokens=800,
            total_tokens=1300,
        )


def main() -> int:
    failures: list[str] = []
    reset_settings()
    settings = get_settings()

    # ---- 1. PromptLoader 加载模板 ----
    try:
        loader = PromptLoader(settings=settings)
        assert loader.prompts_dir == settings.prompts_dir, "prompts_dir 不匹配"
        # 项目里已有 3 个模板
        assert loader.has_template("industry_analysis"), "industry_analysis.md 应存在"
        assert loader.has_template("summary"), "summary.md 应存在"
        assert loader.has_template("recommendations"), "recommendations.md 应存在"
        # 不存在的模板
        assert not loader.has_template("nonexistent_xyz"), "不存在的模板应返回 False"
        print(f"[OK] 1. PromptLoader 模板检测 | dir={loader.prompts_dir.name}")
    except Exception as e:
        failures.append(f"loader has_template: {type(e).__name__}: {e}")
        print(f"[FAIL] 1. {type(e).__name__}: {e}")

    # ---- 2. PromptLoader.render 渲染变量 ----
    try:
        rendered = loader.render(
            "industry_analysis",
            county="安吉县",
            focus="竹产业",
            date="2026-08-05",
            processed_data="这里是清洗后的数据...",
        )
        assert "安吉县" in rendered, "县名未渲染"
        assert "竹产业" in rendered, "方向未渲染"
        assert "2026-08-05" in rendered, "日期未渲染"
        assert "这里是清洗后的数据" in rendered, "数据未渲染"
        assert len(rendered) > 200, f"渲染结果过短: {len(rendered)}"
        print(f"[OK] 2. render 模板渲染 | len={len(rendered)} | 含安吉县={('安吉县' in rendered)}")
    except Exception as e:
        failures.append(f"loader render: {type(e).__name__}: {e}")
        print(f"[FAIL] 2. {type(e).__name__}: {e}")

    # ---- 3. PromptLoader.render_string fallback ----
    try:
        result = loader.render_string(
            "分析 {{ county }} 的 {{ focus }} 产业",
            county="安吉县",
            focus="竹产业",
        )
        assert result == "分析 安吉县 的 竹产业 产业", f"渲染结果不符: {result}"
        print(f"[OK] 3. render_string fallback | result={result}")
    except Exception as e:
        failures.append(f"render_string: {type(e).__name__}: {e}")
        print(f"[FAIL] 3. {type(e).__name__}: {e}")

    # ---- 4. PromptLoader 不存在模板抛 LLMError ----
    try:
        from county_research_ai.exceptions import LLMError
        try:
            loader.get_template("nonexistent_xyz")
            failures.append("get_template 不应成功的模板未抛异常")
            print(f"[FAIL] 4. 应抛 LLMError 但未抛")
        except LLMError as e:
            assert "nonexistent_xyz" in str(e), f"错误信息应含模板名: {e}"
            print(f"[OK] 4. 不存在模板抛 LLMError | msg={e.message[:50]}")
    except Exception as e:
        failures.append(f"get_template error: {type(e).__name__}: {e}")
        print(f"[FAIL] 4. {type(e).__name__}: {e}")

    # ---- 5. LLMAnalyzer.analyze 全流程 ----
    try:
        mock_llm = TestMockLLM()
        analyzer = LLMAnalyzer(llm=mock_llm, prompt_loader=loader, settings=settings)

        county = CountyInfo.from_name("安吉县")
        docs = [
            RawDoc(title="doc1", url="u1", content="竹产业产值120亿" * 5),
            RawDoc(title="doc2", url="u2", content="龙头企业XX股份" * 5),
        ]
        pd = ProcessedData(county=county, focus="竹产业", docs=docs, total_chars=200)

        results = analyzer.analyze(county=county, focus="竹产业", data=pd)

        # 应有 4 个结果(对应 settings.llm.tasks)
        assert len(results) == 4, f"应返回 4 个分析结果, 实际 {len(results)}"
        assert all(r.task for r in results), "每个结果应有 task"
        assert all(r.content for r in results), "每个结果应有 content"
        assert all(r.model == "test-mock-v1" for r in results), "model 应为 test-mock-v1"
        assert all(r.tokens_used == 1300 for r in results), "tokens_used 应为 1300"

        # LLM 应被调用 4 次
        assert mock_llm.call_count == 4, f"LLM 应被调用 4 次, 实际 {mock_llm.call_count}"

        # task 顺序应与 settings.llm.tasks 一致
        expected_tasks = settings.llm.tasks
        actual_tasks = [r.task for r in results]
        assert actual_tasks == expected_tasks, f"task 顺序错误: {actual_tasks} vs {expected_tasks}"

        print(f"[OK] 5. analyzer.analyze | tasks={actual_tasks} | calls={mock_llm.call_count}")
    except Exception as e:
        import traceback; traceback.print_exc()
        failures.append(f"analyzer.analyze: {type(e).__name__}: {e}")
        print(f"[FAIL] 5. {type(e).__name__}: {e}")

    # ---- 6. analyzer 用模板 vs fallback 验证 ----
    try:
        # industry_status 有模板,render 出来的 prompt 应含模板特征(如"产业概况")
        # advantages 无模板,用 fallback,应含"核心优势"
        # 验证方式:检查 mock_llm.calls 里的 prompt 内容
        assert any("产业概况" in c or "产业链结构" in c for c in mock_llm.calls), \
            f"industry_status 应使用模板(含'产业概况'), calls={mock_llm.calls[:1]}"
        assert any("核心优势" in c for c in mock_llm.calls), \
            f"advantages 应使用 fallback(含'核心优势'), calls={mock_llm.calls}"
        print(f"[OK] 6. task→模板映射 | industry_status用模板, advantages用fallback")
    except Exception as e:
        failures.append(f"task mapping: {type(e).__name__}: {e}")
        print(f"[FAIL] 6. {type(e).__name__}: {e}")

    # ---- 7. LLMAnalyzer.generate_summary ----
    try:
        mock_llm2 = TestMockLLM()
        analyzer2 = LLMAnalyzer(llm=mock_llm2, prompt_loader=loader, settings=settings)

        analyses = [
            AnalysisResult(task="industry_status", content="产业现状内容...", model="m", tokens_used=100),
            AnalysisResult(task="advantages", content="优势内容...", model="m", tokens_used=100),
        ]
        summary = analyzer2.generate_summary(
            county=CountyInfo.from_name("安吉县"),
            focus="竹产业",
            analyses=analyses,
        )
        # summary.md 模板存在,应使用模板渲染后调用 LLM
        assert len(summary) > 0, "摘要不应为空"
        assert mock_llm2.call_count == 1, f"摘要应调用 LLM 1 次, 实际 {mock_llm2.call_count}"
        # 检查 LLM 收到的 prompt 含 analysis_content
        assert "产业现状内容" in mock_llm2.calls[0], \
            f"摘要 prompt 应含 analysis_content, call={mock_llm2.calls[0][:80]}"
        print(f"[OK] 7. generate_summary | len={len(summary)} | 含模板渲染")
    except Exception as e:
        import traceback; traceback.print_exc()
        failures.append(f"generate_summary: {type(e).__name__}: {e}")
        print(f"[FAIL] 7. {type(e).__name__}: {e}")

    # ---- 总结 ----
    print()
    if failures:
        print(f"❌ {len(failures)} 项失败:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("✅ LLM 层(prompt_loader + analyzer)全部 7 项测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
