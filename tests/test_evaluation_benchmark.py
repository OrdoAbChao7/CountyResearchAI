from __future__ import annotations

from county_research_ai.evaluation.benchmark import BenchmarkEvaluator
from county_research_ai.evaluation.datasets import (
    BENCHMARK_CASES,
    get_benchmark_case,
)
from county_research_ai.evaluation.runner import (
    BenchmarkRunner,
    ComparisonReport,
    DeterministicBenchmarkSearchProvider,
)
from county_research_ai.models import CountyInfo, RawDoc, ReportSection, ResearchReport


def test_benchmark_datasets_integrity():
    assert len(BENCHMARK_CASES) == 3
    for case_id in ["case_a_anji", "case_b_xinfeng", "case_c_hegang"]:
        case = get_benchmark_case(case_id)
        assert case.county != ""
        assert len(case.ground_truth_facts) >= 3
        assert len(case.reference_sources) >= 2


def test_benchmark_evaluator_retrieval():
    case = get_benchmark_case("case_a_anji")
    evaluator = BenchmarkEvaluator(case, k=5)

    docs = [
        RawDoc(
            title="2023年安吉县国民经济和社会发展统计公报",
            url="https://www.anji.gov.cn/tjgb/2023.html",
            snippet="安吉县竹产业产值突破280亿元，竹林面积101.1万亩。",
            content="竹林面积101.1万亩，竹产业总产值超过280亿元。",
            domain_type="government",
            credibility_score=0.98,
        ),
        RawDoc(
            title="国家发改委发布加快以竹代塑发展三年行动计划",
            url="https://www.ndrc.gov.cn/yzds.html",
            snippet="加快以竹代塑发展三年行动计划，支持浙江安吉先行先试。",
            content="推进以竹代塑示范区建设。",
            domain_type="government",
            credibility_score=0.95,
        ),
    ]

    metrics = evaluator.evaluate_retrieval(docs, queries_issued=2, elapsed_seconds=0.1)

    assert metrics.case_id == "case_a_anji"
    assert metrics.total_docs_retrieved == 2
    assert metrics.unique_urls == 2
    assert metrics.duplicate_ratio == 0.0
    assert metrics.official_source_ratio == 1.0  # both .gov.cn
    assert metrics.precision_at_k == 1.0  # both relevant to Anji / bamboo
    assert metrics.critical_facts_covered >= 2
    assert metrics.recall_at_k > 0.3
    assert metrics.total_queries_issued == 2

    data_dict = metrics.to_dict()
    assert "critical_facts_covered" in data_dict
    assert data_dict["official_source_ratio"] == 1.0


def test_benchmark_evaluator_report():
    case = get_benchmark_case("case_b_xinfeng")
    evaluator = BenchmarkEvaluator(case, k=5)

    report_content = "信丰县是赣南脐橙发源地，1971年由袁守根在郭磊庄引种试种成功。黄龙病综合防控是关键。"
    report = ResearchReport(
        county=CountyInfo(name="信丰县", province="江西省", city="赣州市"),
        focus="脐橙产业",
        sections=[
            ReportSection(
                title="发展历程",
                content=report_content,
                order=1,
                sources=["https://www.jxxf.gov.cn/orig_orange.html"],
            )
        ],
    )

    metrics = evaluator.evaluate_report(report, report_content)
    assert metrics.case_id == "case_b_xinfeng"
    assert metrics.evidence_support_rate == 1.0
    assert metrics.critical_facts_covered >= 1


def test_benchmark_runner_and_comparison():
    runner = BenchmarkRunner()
    report = runner.run_case_comparison("case_a_anji")

    assert isinstance(report, ComparisonReport)
    assert report.case_id == "case_a_anji"
    assert report.refactored_metrics.recall_at_k >= report.baseline_metrics.recall_at_k
    assert report.refactored_metrics.critical_facts_covered >= report.baseline_metrics.critical_facts_covered
    assert report.refactored_metrics.evidence_support_rate >= report.baseline_metrics.evidence_support_rate

    md = report.to_markdown()
    assert "### 案例评测对比：case_a_anji" in md
    assert "重构前 (Legacy Baseline)" in md
    assert "重构后 (Deep Multi-Agent)" in md


def test_benchmark_runner_all_cases():
    runner = BenchmarkRunner()
    all_reports = runner.run_all_cases()
    assert len(all_reports) == 3
    for cid in ["case_a_anji", "case_b_xinfeng", "case_c_hegang"]:
        assert cid in all_reports
        rep = all_reports[cid]
        assert rep.refactored_metrics.recall_at_k > rep.baseline_metrics.recall_at_k
        assert rep.refactored_metrics.critical_facts_covered >= rep.baseline_metrics.critical_facts_covered


def test_deterministic_benchmark_search_provider():
    provider = DeterministicBenchmarkSearchProvider("case_c_hegang")
    results = provider.search("鹤岗 煤炭转型")
    assert len(results) > 0
    assert any("煤" in d.title or "石墨" in d.title for d in results)
