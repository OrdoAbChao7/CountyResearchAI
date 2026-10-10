"""评测指标与评估套件。

计算：
1. 检索相关性 Precision@K
2. 关键事实覆盖率 Recall@K（基于 BenchmarkCase 事实标注）
3. 官方及高质量来源覆盖率（.gov.cn / stats.gov.cn 等）
4. 重复内容比例（URL 去重与标题相似度）
5. 关键结论证据支持率（Claim 有清晰证据溯源）
6. 统计年份有效性（数据时效性）
7. 冲突发现与处理能力
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models import RawDoc, ResearchReport
from .datasets import BenchmarkCase, FactPoint


@dataclass
class EvaluationMetrics:
    """综合评估指标。"""
    case_id: str
    total_docs_retrieved: int = 0
    unique_urls: int = 0
    duplicate_ratio: float = 0.0
    official_source_ratio: float = 0.0
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    critical_facts_covered: int = 0
    total_critical_facts: int = 0
    evidence_support_rate: float = 0.0
    recent_data_ratio: float = 0.0
    conflicts_detected: int = 0
    total_queries_issued: int = 0
    execution_time_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "total_docs_retrieved": self.total_docs_retrieved,
            "unique_urls": self.unique_urls,
            "duplicate_ratio": round(self.duplicate_ratio, 4),
            "official_source_ratio": round(self.official_source_ratio, 4),
            "precision_at_k": round(self.precision_at_k, 4),
            "recall_at_k": round(self.recall_at_k, 4),
            "critical_facts_covered": f"{self.critical_facts_covered}/{self.total_critical_facts}",
            "evidence_support_rate": round(self.evidence_support_rate, 4),
            "recent_data_ratio": round(self.recent_data_ratio, 4),
            "conflicts_detected": self.conflicts_detected,
            "total_queries_issued": self.total_queries_issued,
            "execution_time_seconds": round(self.execution_time_seconds, 2),
            "notes": self.notes,
        }


class BenchmarkEvaluator:
    """基于基准案例评估检索和报告质量。"""

    def __init__(self, case: BenchmarkCase, k: int = 10) -> None:
        self.case = case
        self.k = k

    def evaluate_retrieval(
        self,
        docs: list[RawDoc],
        queries_issued: int = 0,
        elapsed_seconds: float = 0.0,
    ) -> EvaluationMetrics:
        """评估检索结果质量。"""
        metrics = EvaluationMetrics(
            case_id=self.case.case_id,
            total_docs_retrieved=len(docs),
            total_queries_issued=queries_issued,
            execution_time_seconds=elapsed_seconds,
        )

        if not docs:
            metrics.notes.append("No documents retrieved.")
            return metrics

        # 1. URL 去重与重复率
        urls = [d.url for d in docs if d.url]
        unique_urls = set(urls)
        metrics.unique_urls = len(unique_urls)
        metrics.duplicate_ratio = (
            (len(docs) - len(unique_urls)) / len(docs) if docs else 0.0
        )

        # 2. 官方来源比例
        official_count = 0
        for doc in docs:
            url_lower = (doc.url or "").lower()
            if (
                "gov.cn" in url_lower
                or doc.domain_type == "government"
                or "stats." in url_lower
            ):
                official_count += 1
        metrics.official_source_ratio = official_count / len(docs)

        # 3. Precision@K: Top-K 中与县名及核心方向相关的比例
        top_k_docs = docs[: self.k]
        relevant_count = 0
        county_kw = self.case.county
        county_stem = county_kw.rstrip("县市旗区") if len(county_kw) > 2 else county_kw
        focus_kw = self.case.focus
        for doc in top_k_docs:
            text = f"{doc.title} {doc.snippet} {doc.content}"
            if (county_kw in text or county_stem in text) and (
                not focus_kw or focus_kw in text or self._matches_focus_synonyms(text)
            ):
                relevant_count += 1
        metrics.precision_at_k = relevant_count / len(top_k_docs) if top_k_docs else 0.0

        # 4. Recall@K: 事实点覆盖率（Top-K 文档包含的事实点 / 总事实点）
        covered_facts = set()
        aggregated_top_text = " ".join(
            f"{d.title} {d.snippet} {d.content}" for d in top_k_docs
        )
        for fact in self.case.ground_truth_facts:
            if self._text_matches_fact(aggregated_top_text, fact):
                covered_facts.add(fact.id)

        metrics.recall_at_k = (
            len(covered_facts) / len(self.case.ground_truth_facts)
            if self.case.ground_truth_facts
            else 0.0
        )
        critical_facts = [f for f in self.case.ground_truth_facts if f.is_critical]
        metrics.total_critical_facts = len(critical_facts)
        metrics.critical_facts_covered = sum(
            1 for f in critical_facts if f.id in covered_facts
        )

        # 5. 时效性比例（出现 2021-2026 年份的文档比例）
        year_re = re.compile(r"202[1-6]年?")
        recent_count = sum(
            1 for d in docs if year_re.search(f"{d.title} {d.snippet} {d.content}")
        )
        metrics.recent_data_ratio = recent_count / len(docs)

        return metrics

    def evaluate_report(
        self,
        report: ResearchReport,
        report_text: str,
        retrieval_metrics: EvaluationMetrics | None = None,
    ) -> EvaluationMetrics:
        """评估最终研究报告质量。"""
        metrics = retrieval_metrics or EvaluationMetrics(case_id=self.case.case_id)

        # 1. 事实覆盖率检查（在报告全文中）
        covered_facts = set()
        for fact in self.case.ground_truth_facts:
            if self._text_matches_fact(report_text, fact):
                covered_facts.add(fact.id)

        metrics.recall_at_k = (
            len(covered_facts) / len(self.case.ground_truth_facts)
            if self.case.ground_truth_facts
            else 0.0
        )
        critical_facts = [f for f in self.case.ground_truth_facts if f.is_critical]
        metrics.total_critical_facts = len(critical_facts)
        metrics.critical_facts_covered = sum(
            1 for f in critical_facts if f.id in covered_facts
        )

        # 2. 证据支持率：有来源 URL 或来源标注的章节比例
        if report.sections:
            supported_sections = sum(
                1 for s in report.sections if s.sources or "http" in s.content or "来源" in s.content
            )
            metrics.evidence_support_rate = supported_sections / len(report.sections)
        else:
            metrics.evidence_support_rate = 1.0 if "http" in report_text else 0.0

        # 3. 冲突识别标注检查
        if "冲突" in report_text or "差异" in report_text or "口径" in report_text:
            metrics.conflicts_detected += 1

        return metrics

    def _matches_focus_synonyms(self, text: str) -> bool:
        synonyms = {
            "竹产业": ["竹林", "竹材", "竹制品", "竹加工", "安吉竹", "以竹代塑", "竹"],
            "脐橙产业": ["脐橙", "柑橘", "果业", "果园", "赣南脐橙"],
            "产业转型": ["转型", "煤炭", "石墨", "资源枯竭", "接续产业"],
        }
        for syn in synonyms.get(self.case.focus, []):
            if syn in text:
                return True
        return False

    @staticmethod
    def _text_matches_fact(text: str, fact: FactPoint) -> bool:
        # 必须匹配至少 2 个关键词（如果 keywords 数量 >= 2）
        matched_kws = sum(1 for kw in fact.keywords if kw in text)
        if matched_kws < min(2, len(fact.keywords)):
            return False
        # 必须包含期望值之一
        return any(val in text for val in fact.expected_values)
