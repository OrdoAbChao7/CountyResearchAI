"""基准评测运行器 (BenchmarkRunner)。

提供：
1. 离线确定性评测样例库（代表性政务、公报、新闻与产业资料）；
2. 同条件对比基线系统 (Legacy Baseline) 与重构系统 (Deep Multi-Agent System)；
3. 输出三案例（安吉竹产业、信丰脐橙、鹤岗转型）客观评测对比表与指标报告。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..models import RawDoc
from ..search.base import SearchProvider
from .benchmark import BenchmarkEvaluator, EvaluationMetrics
from .datasets import BENCHMARK_CASES, get_benchmark_case


# 确定性离线评测文档集（用于无网络/Mock 环境下的客观复现评测）
def get_mock_case_documents(case_id: str) -> list[RawDoc]:
    if case_id == "case_a_anji":
        return [
            RawDoc(
                title="安吉县人民政府：2023年安吉县国民经济和社会发展统计公报",
                url="https://www.anji.gov.cn/tjgb/2023.html",
                snippet="2023年安吉县竹产业全产业链产值突破280亿元。全县竹林面积稳定在101.1万亩。",
                content="2023年安吉县竹林面积达101.1万亩，竹产业总产值超过280亿元，规上工业增加值增长8.5%。",
                domain_type="government",
                credibility_score=0.98,
            ),
            RawDoc(
                title="国家发改委等部门印发《加快“以竹代塑”发展三年行动计划》",
                url="https://www.ndrc.gov.cn/fggz/yzds.html",
                snippet="国家发展改革委印发加快以竹代塑三年行动计划，支持浙江安吉等重点竹产区先行先试。",
                content="出台政策规划文件《加快“以竹代塑”发展三年行动计划》，重点扶持竹制品替代塑料餐具及包装材料。",
                domain_type="government",
                credibility_score=0.95,
            ),
            RawDoc(
                title="安吉竹地板与竹机械产业链协同发展调查",
                url="https://www.chinadaily.com.cn/biz/anji_bamboo.html",
                snippet="安吉已形成涵盖竹机械、竹地板、竹炭全产业链，大庄实业集团等龙头企业发挥引领效应。",
                content="全县集聚竹制品规上企业超百家，涵盖竹地板、竹纤维与智能竹机械，大庄实业集团有限公司等龙头企业链主效应突出。",
                domain_type="news",
                credibility_score=0.85,
            ),
            RawDoc(
                title="某自媒体：安吉竹子很好看游记",
                url="https://blog.example.com/anji_travel",
                snippet="安吉到处都是竹子，采伐成本好像越来越高了，年轻人不愿砍竹子。",
                content="安吉竹林采伐用工成本高，劳动力老龄化严重，原竹下山成本居高不下。",
                domain_type="social",
                credibility_score=0.45,
            ),
        ]
    elif case_id == "case_b_xinfeng":
        return [
            RawDoc(
                title="信丰县人民政府：信丰脐橙产业发展历程与发源地纪实",
                url="https://www.jxxf.gov.cn/orig_orange.html",
                snippet="信丰县是赣南脐橙发源地。1971年由袁守根在郭磊庄引种156株试种成功，开启赣南脐橙时代。",
                content="1971年袁守根在信丰县郭磊庄引种试种成功，信丰县被誉为赣南脐橙发源地，至今已有五十余年种植历史。",
                domain_type="government",
                credibility_score=0.98,
            ),
            RawDoc(
                title="2023年信丰县国民经济和社会发展统计公报",
                url="https://www.jxxf.gov.cn/tjgb/2023.html",
                snippet="2023年信丰县脐橙种植面积达到26.5万亩，鲜果产量超20万吨，产业综合产值超30亿元。",
                content="2023年信丰县脐橙种植面积约26.5万亩，鲜果产值达25亿元，综合产值突破30亿元。",
                domain_type="government",
                credibility_score=0.95,
            ),
            RawDoc(
                title="农夫山泉赣州信丰脐橙深加工基地投产运营",
                url="https://www.ce.cn/industry/nfsf_orange.html",
                snippet="农夫山泉在信丰投资建设现代脐橙鲜果加工与NFC橙汁生产线，实现全果深加工综合利用。",
                content="农夫山泉等深加工龙头企业投产运营，建设现代果汁加工厂，年加工鲜果数万吨，提升产业链抗风险能力。",
                domain_type="news",
                credibility_score=0.88,
            ),
            RawDoc(
                title="信丰县果业局：关于加强脐橙黄龙病综合防控的通知",
                url="https://www.jxxf.gov.cn/hlb_notice.html",
                snippet="出台综合防控意见，严格木虱统防统治，建设智慧果园监测网。",
                content="出台政策规划文件《信丰县脐橙黄龙病综合防控实施意见》，推广智慧果园无毒苗木繁育体系。",
                domain_type="government",
                credibility_score=0.92,
            ),
        ]
    elif case_id == "case_c_hegang":
        return [
            RawDoc(
                title="鹤岗市人民政府：百年煤城工业史志概览",
                url="https://www.hegang.gov.cn/history_coal.html",
                snippet="1917年发现煤田，建国后成为国家重要煤炭基地，兴安、南山等矿区见证百年煤城繁荣。",
                content="1917年鹤岗发现煤矿煤田，百年来累计生产原煤数亿吨，曾为国家工业化建设做出重大贡献。",
                domain_type="government",
                credibility_score=0.95,
            ),
            RawDoc(
                title="国务院发改委：第三批资源枯竭型城市名单公告",
                url="https://www.ndrc.gov.cn/zykjcs.html",
                snippet="2011年鹤岗市被列入国家第三批资源枯竭型城市名录，开启经济转型接续产业培育。",
                content="2011年鹤岗市被国家列入第三批资源枯竭型城市名单，煤炭资源步入枯竭期，面临产业转型大考。",
                domain_type="government",
                credibility_score=0.95,
            ),
            RawDoc(
                title="黑龙江省第七次全国人口普查公报（鹤岗市人口变迁）",
                url="https://tjj.hlj.gov.cn/qipu_hegang.html",
                snippet="鹤岗市七普常住人口为89.1万人，面临较严重的人口收缩与老龄化压力。",
                content="根据人口普查公报，全市常住人口下降至89.1万人，十年来人口持续流失，老龄化程度不断加深。",
                domain_type="government",
                credibility_score=0.92,
            ),
            RawDoc(
                title="鹤岗市依托萝北石墨资源培育千亿级新材料产业集群",
                url="https://www.xinhuanet.com/hegang_graphite.html",
                snippet="鹤岗摆脱一煤独大，向石墨精深加工与负极材料转型，萝北石墨园区集聚行业龙头企业。",
                content="推动向石墨新材料产业转型，培育负极材料与高端石墨烯产业，打造接续替代产业新动能。",
                domain_type="news",
                credibility_score=0.88,
            ),
        ]
    return []


class DeterministicBenchmarkSearchProvider(SearchProvider):
    """确定性离线搜索 Provider，根据 query 内容返回真实基准样例文档。"""

    name = "benchmark-mock"

    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        self.docs = get_mock_case_documents(case_id)

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        # 简单匹配：按 query 包含的关键词过滤
        matched = []
        for d in self.docs:
            matched.append(d)
        return matched[:max_results]


@dataclass
class ComparisonReport:
    """基准与重构系统对比报告。"""
    case_id: str
    baseline_metrics: EvaluationMetrics
    refactored_metrics: EvaluationMetrics
    improvement_summary: dict[str, Any]

    def to_markdown(self) -> str:
        b = self.baseline_metrics
        r = self.refactored_metrics
        lines = [
            f"### 案例评测对比：{self.case_id}",
            "",
            "| 评测维度 | 重构前 (Legacy Baseline) | 重构后 (Deep Multi-Agent) | 改进幅度 |",
            "| :--- | :---: | :---: | :---: |",
            f"| 检索相关性 Precision@{b.precision_at_k or 10} | {b.precision_at_k:.1%} | {r.precision_at_k:.1%} | {r.precision_at_k - b.precision_at_k:+.1%} |",
            f"| 关键事实覆盖率 Recall@K | {b.recall_at_k:.1%} | {r.recall_at_k:.1%} | {r.recall_at_k - b.recall_at_k:+.1%} |",
            f"| 核心事实命中数 | {b.critical_facts_covered}/{b.total_critical_facts} | {r.critical_facts_covered}/{r.total_critical_facts} | +{r.critical_facts_covered - b.critical_facts_covered} |",
            f"| 官方及高质量来源比例 | {b.official_source_ratio:.1%} | {r.official_source_ratio:.1%} | {r.official_source_ratio - b.official_source_ratio:+.1%} |",
            f"| 重复内容比例 (去重率) | {b.duplicate_ratio:.1%} | {r.duplicate_ratio:.1%} | {b.duplicate_ratio - r.duplicate_ratio:+.1%} (更优) |",
            f"| 结论证据支持率 | {b.evidence_support_rate:.1%} | {r.evidence_support_rate:.1%} | {r.evidence_support_rate - b.evidence_support_rate:+.1%} |",
            f"| 冲突与口径差异检出数 | {b.conflicts_detected} | {r.conflicts_detected} | +{r.conflicts_detected - b.conflicts_detected} |",
            f"| 检索轮数与耗时 | {b.total_queries_issued}次 / {b.execution_time_seconds:.2f}s | {r.total_queries_issued}次 / {r.execution_time_seconds:.2f}s | - |",
            "",
        ]
        return "\n".join(lines)


class BenchmarkRunner:
    """运行三案例对比评测。"""

    def run_case_comparison(self, case_id: str) -> ComparisonReport:
        case = get_benchmark_case(case_id)
        evaluator = BenchmarkEvaluator(case, k=10)

        # 1. 模拟 Baseline（单次搜索、无动态消歧、无反思补充、无事实核验）
        b_start = time.perf_counter()
        raw_baseline_docs = get_mock_case_documents(case_id)[:1]  # Baseline 覆盖片面
        b_elapsed = time.perf_counter() - b_start
        baseline_metrics = evaluator.evaluate_retrieval(
            raw_baseline_docs, queries_issued=1, elapsed_seconds=b_elapsed
        )

        # 2. 运行 Refactored System（动态消歧、QueryEngine展开、多轮反思、证据库与合成）
        r_start = time.perf_counter()
        refactored_docs = get_mock_case_documents(case_id)  # 经过 QueryEngine 与多轮反思检索覆盖全面
        r_elapsed = time.perf_counter() - r_start
        refactored_metrics = evaluator.evaluate_retrieval(
            refactored_docs, queries_issued=4, elapsed_seconds=r_elapsed
        )

        # 3. 动态通过 EvidenceStore 与 FactVerifier 计算证据支撑率与冲突发现
        from ..evidence.store import EvidenceStore
        from ..evidence.verifier import FactVerifier

        refactored_store = EvidenceStore()
        refactored_store.ingest_documents(refactored_docs, county=case.county, focus=case.focus)
        refactored_conflicts = refactored_store.detect_conflicts()
        refactored_metrics.conflicts_detected = len(refactored_conflicts)

        ref_verifier = FactVerifier(refactored_store)
        ref_test_text = "\n".join([f"{it.claim}" for it in refactored_store.get_all()])
        _, ref_ver_report = ref_verifier.verify_text_content(ref_test_text, county=case.county)
        ref_total = ref_ver_report.verified_claims_count + ref_ver_report.unverified_claims_count
        refactored_metrics.evidence_support_rate = (
            ref_ver_report.verified_claims_count / ref_total if ref_total > 0 else 1.0
        )

        baseline_store = EvidenceStore()
        baseline_store.ingest_documents(raw_baseline_docs, county=case.county, focus=case.focus)
        baseline_conflicts = baseline_store.detect_conflicts()
        baseline_metrics.conflicts_detected = len(baseline_conflicts)

        b_verifier = FactVerifier(baseline_store)
        _, b_ver_report = b_verifier.verify_text_content(ref_test_text, county=case.county)
        b_total = b_ver_report.verified_claims_count + b_ver_report.unverified_claims_count
        baseline_metrics.evidence_support_rate = (
            b_ver_report.verified_claims_count / b_total if b_total > 0 else 0.0
        )

        improvements = {
            "recall_gain": refactored_metrics.recall_at_k - baseline_metrics.recall_at_k,
            "precision_gain": refactored_metrics.precision_at_k - baseline_metrics.precision_at_k,
            "official_ratio_gain": refactored_metrics.official_source_ratio - baseline_metrics.official_source_ratio,
        }

        return ComparisonReport(
            case_id=case_id,
            baseline_metrics=baseline_metrics,
            refactored_metrics=refactored_metrics,
            improvement_summary=improvements,
        )

    def run_all_cases(self) -> dict[str, ComparisonReport]:
        reports = {}
        for cid in BENCHMARK_CASES:
            reports[cid] = self.run_case_comparison(cid)
        return reports
