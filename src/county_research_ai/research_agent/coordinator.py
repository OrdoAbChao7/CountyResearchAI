"""深度多智能体研究总协调器 (DeepResearchCoordinator)。

实现了任务核心重构目标：
研究规划 → 初次检索 → 证据提取 → 发现缺口 → 补充检索 → 交叉验证 → 综合研究 → 报告生成。

协调流程：
1. Planning: 生成研究问题树 (QuestionTree)；
2. Retrieval: 结合消歧上下文与 QueryEngine 执行首轮并发定向采集；
3. Ingestion: 证据库 (EvidenceStore) 抽取结构化事实指标；
4. Reflection Loop: ResearchCritic 审计材料缺口并生成补充检索词，支持多轮迭代补充搜索（有最大轮数与预算控制）；
5. Specialized Analysis: 调度 EconomicAgent, PolicyAgent, IndustryAgent 分头深入研究；
6. Synthesis: Synthesizer 融合研究结论，嵌入事实核验标记、冲突排查说明、资料缺口声明与参考文献表。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..evidence.store import EvidenceStore
from ..models import (
    AnalysisResult,
    CountyInfo,
    CountyLongHistoryAnalysis,
    CountyRiseFallAnalysis,
    EvidenceConflict,
    EvidenceGap,
    QuestionTree,
    RawDoc,
    ReflectionResult,
)
from .critic import ResearchCritic
from .specialized.economic import EconomicAnalysisOutput, EconomicResearchAgent
from .specialized.industry import IndustryAnalysisOutput, IndustryResearchAgent
from .specialized.policy import PolicyAnalysisOutput, PolicyResearchAgent
from .specialized.synthesizer import ResearchSynthesizer
from .tree import build_question_tree

logger = logging.getLogger(__name__)


@dataclass
class DeepResearchResult:
    """深度多智能体研究全量结果。"""
    county: CountyInfo
    focus: str
    mode: str
    question_tree: QuestionTree
    evidence_store: EvidenceStore
    reflection_history: list[ReflectionResult]
    economic_output: EconomicAnalysisOutput | None = None
    policy_output: PolicyAnalysisOutput | None = None
    industry_output: IndustryAnalysisOutput | None = None
    analyses: list[AnalysisResult] = field(default_factory=list)
    rise_fall_analysis: CountyRiseFallAnalysis | None = None
    long_history_analysis: CountyLongHistoryAnalysis | None = None
    executive_summary: str = ""
    all_raw_docs: list[RawDoc] = field(default_factory=list)
    total_turns: int = 1
    conflicts: list[EvidenceConflict] = field(default_factory=list)
    gaps: list[EvidenceGap] = field(default_factory=list)


class DeepResearchCoordinator:
    """深度多智能体研究协调器。"""

    def __init__(
        self,
        search_collector: Any = None,
        critic: ResearchCritic | None = None,
        max_turns: int = 2,  # 默认最多迭代补充 2 轮
        analyzer: Any = None,
        rise_fall_analyzer: Any = None,
        long_history_analyzer: Any = None,
        llm: Any = None,
    ) -> None:
        self.collector = search_collector
        self.critic = critic or ResearchCritic(max_turns=max_turns)
        self.economic_agent = EconomicResearchAgent()
        self.policy_agent = PolicyResearchAgent()
        self.industry_agent = IndustryResearchAgent()
        self.synthesizer = ResearchSynthesizer()
        self.analyzer = analyzer
        self.rise_fall_analyzer = rise_fall_analyzer
        self.long_history_analyzer = long_history_analyzer
        self.llm = llm
        self.max_turns = max_turns

    def _get_llm(self) -> Any:
        if self.llm is not None:
            return self.llm
        from ..config import get_settings
        from ..mocks.llm import MockLLMClient
        try:
            settings = get_settings()
            if settings.llm.api_key and settings.llm.api_key.get_secret_value():
                from ..llm.client import OpenAICompatibleClient
                return OpenAICompatibleClient(settings=settings)
        except Exception:
            pass
        return MockLLMClient()

    def run_deep_research(
        self,
        county: str,
        focus: str | None = None,
        mode: str = "snapshot",
        existing_docs: list[RawDoc] | None = None,
    ) -> DeepResearchResult:
        c_info = CountyInfo.from_name(county)
        f_name = focus or ("兴衰规律" if mode == "rise-fall" else ("长周期兴衰史" if mode == "long-history" else "特色优势产业"))

        logger.info("=== 启动深度多智能体研究 === | county=%s | focus=%s | mode=%s", county, f_name, mode)

        # 1. 动态生成研究问题树
        qtree = build_question_tree(county=county, focus=f_name, mode=mode)
        evidence_store = EvidenceStore()
        all_docs: list[RawDoc] = list(existing_docs or [])

        # 2. 首轮检索（如果已有资料不足）
        if not all_docs and self.collector is not None:
            logger.info("执行首轮多角度定向检索...")
            all_docs = self._collect_initial(county, f_name, mode)

        # 3. 证据提取与摄入
        evidence_store.ingest_documents(all_docs, county=county, focus=f_name)

        # 4. 检索—反思—补充循环
        reflection_history: list[ReflectionResult] = []
        turn = 1
        last_gaps: list[EvidenceGap] = []

        while turn <= self.max_turns:
            reflection = self.critic.reflect(
                evidence_store=evidence_store,
                question_tree=qtree,
                current_turn=turn,
            )
            reflection_history.append(reflection)
            last_gaps = reflection.gaps

            if reflection.is_sufficient or not reflection.followup_queries:
                logger.info("反思通过或无更多补充检索词，结束迭代 | turn=%d", turn)
                break

            # 执行有针对性的定向补充检索
            logger.info(
                "触发第 %d 轮补充检索 | 检索词数=%d: %s",
                turn + 1,
                len(reflection.followup_queries),
                reflection.followup_queries,
            )
            supp_docs = self._collect_supp(reflection.followup_queries)
            if not supp_docs:
                logger.info("补充检索未返回更多新内容，停止迭代")
                break

            all_docs.extend(supp_docs)
            evidence_store.ingest_documents(supp_docs, county=county, focus=f_name)
            turn += 1

        # 5. 依据研究模式调度专业智能体或模式分析器
        if mode == "rise-fall":
            from ..llm.rise_fall_analyzer import RiseFallAnalyzer
            from ..processor import DocumentProcessor
            proc_data = DocumentProcessor().process(all_docs, county=c_info, focus=f_name)
            rf_analyzer = self.rise_fall_analyzer or RiseFallAnalyzer(llm=self._get_llm())
            rf_analysis = rf_analyzer.analyze(county=c_info, data=proc_data)
            return DeepResearchResult(
                county=c_info,
                focus=f_name,
                mode=mode,
                question_tree=qtree,
                evidence_store=evidence_store,
                reflection_history=reflection_history,
                rise_fall_analysis=rf_analysis,
                all_raw_docs=all_docs,
                total_turns=turn,
                conflicts=evidence_store.get_conflicts(),
                gaps=last_gaps,
            )
        elif mode == "long-history":
            from ..llm.long_history_analyzer import LongHistoryAnalyzer
            from ..processor import DocumentProcessor
            proc_data = DocumentProcessor().process(all_docs, county=c_info, focus=f_name)
            lh_analyzer = self.long_history_analyzer or LongHistoryAnalyzer(llm=self._get_llm())
            lh_analysis = lh_analyzer.analyze(county=c_info, data=proc_data)
            return DeepResearchResult(
                county=c_info,
                focus=f_name,
                mode=mode,
                question_tree=qtree,
                evidence_store=evidence_store,
                reflection_history=reflection_history,
                long_history_analysis=lh_analysis,
                all_raw_docs=all_docs,
                total_turns=turn,
                conflicts=evidence_store.get_conflicts(),
                gaps=last_gaps,
            )
        else:
            # Snapshot / Industry 模式
            logger.info("调度专业研究智能体进行分项分析...")
            econ_out = self.economic_agent.analyze(county=county, focus=f_name, evidence_store=evidence_store)
            pol_out = self.policy_agent.analyze(county=county, focus=f_name, evidence_store=evidence_store)
            ind_out = self.industry_agent.analyze(county=county, focus=f_name, evidence_store=evidence_store)

            logger.info("执行研究成果综合合成与审计...")
            analyses = self.synthesizer.synthesize(
                county=c_info,
                focus=f_name,
                economic_out=econ_out,
                policy_out=pol_out,
                industry_out=ind_out,
                evidence_store=evidence_store,
                gaps=last_gaps,
            )
            summary = self.synthesizer.generate_executive_summary(
                county=c_info, focus=f_name, analyses=analyses
            )

            return DeepResearchResult(
                county=c_info,
                focus=f_name,
                mode=mode,
                question_tree=qtree,
                evidence_store=evidence_store,
                reflection_history=reflection_history,
                economic_output=econ_out,
                policy_output=pol_out,
                industry_output=ind_out,
                analyses=analyses,
                executive_summary=summary,
                all_raw_docs=all_docs,
                total_turns=turn,
                conflicts=evidence_store.get_conflicts(),
                gaps=last_gaps,
            )

    def _collect_initial(self, county: str, focus: str, mode: str) -> list[RawDoc]:
        if hasattr(self.collector, "collect"):
            try:
                return self.collector.collect(county=county, focus=focus, mode=mode)
            except TypeError:
                return self.collector.collect(county, focus, 10)
        elif hasattr(self.collector, "search"):
            return self.collector.search(f"{county} {focus}", max_results=10)
        return []

    def _collect_supp(self, queries: list[str]) -> list[RawDoc]:
        if not self.collector:
            return []
        if hasattr(self.collector, "collect_supplemental"):
            return self.collector.collect_supplemental(queries=queries, max_results=8)
        elif hasattr(self.collector, "search"):
            results: list[RawDoc] = []
            for q in queries[:3]:
                try:
                    results.extend(self.collector.search(q, max_results=4))
                except Exception:
                    pass
            return results
        return []
