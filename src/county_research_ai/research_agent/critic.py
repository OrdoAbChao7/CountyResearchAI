"""研究反思与证据缺口审计器 (ResearchCritic)。

借鉴 BettaFish Reflection 机制：
1. 阶段检索完成后，主动审视当前 EvidenceStore 与 QuestionTree：
   - 哪些子问题缺乏数据或有效来源？
   - 统计数据是否陈旧过时？
   - 是否存在互相矛盾的指标？
   - 是否仅有二手自媒体观点而无官方公报？
2. 输出结构化 ReflectionResult：
   - 判定当前材料是否已充分满足研究要求 (is_sufficient)；
   - 识别具体证据缺口 (gaps)；
   - 生成针对性补充检索词 (followup_queries) 以驱动下一轮真实检索。
"""
from __future__ import annotations

import logging

from ..evidence.store import EvidenceStore
from ..models import QuestionTree, ReflectionResult
from ..search.query_engine import QueryEngine

logger = logging.getLogger(__name__)


class ResearchCritic:
    """研究反思与证据缺口发现者。"""

    def __init__(
        self,
        query_engine: QueryEngine | None = None,
        min_coverage_threshold: float = 0.75,
        max_turns: int = 3,
    ) -> None:
        self.query_engine = query_engine or QueryEngine()
        self.min_coverage_threshold = min_coverage_threshold
        self.max_turns = max_turns

    def reflect(
        self,
        evidence_store: EvidenceStore,
        question_tree: QuestionTree,
        current_turn: int = 1,
    ) -> ReflectionResult:
        """评估当前研究证据充分度，输出反思判断与定向补充检索词。"""
        # 1. 评估问题树覆盖度与缺口
        coverage_rate, gaps = evidence_store.assess_question_tree_coverage(question_tree)
        # 2. 检查冲突
        conflicts = evidence_store.get_conflicts()

        # 3. 检查是否有核心产值统计
        economic_items = evidence_store.get_by_topic("economic")
        has_authoritative_stats = any(
            it.credibility_score >= 0.85 and it.year and int(it.year) >= 2020
            for it in economic_items
        )

        reasons = []
        followup_queries: list[str] = []

        # 判定是否终止循环
        if current_turn >= self.max_turns:
            is_sufficient = True
            reasons.append(f"已达到最大反思检索轮数上限 ({self.max_turns}轮)，停止检索并进入分析。")
        elif coverage_rate >= self.min_coverage_threshold and (has_authoritative_stats or not gaps):
            is_sufficient = True
            reasons.append(
                f"证据充分度达标 (覆盖率: {coverage_rate:.1%})，核心宏观统计与产业要素已具备。"
            )
        else:
            is_sufficient = False
            reasons.append(
                f"证据尚不充分 (覆盖率: {coverage_rate:.1%} < {self.min_coverage_threshold:.1%})，"
                f"识别到 {len(gaps)} 处核心证据缺口，需启动补充检索。"
            )
            # 针对缺口生成高质量补充检索词
            generated = self.query_engine.generate_reflection_queries(
                county=question_tree.county,
                focus=question_tree.focus,
                gaps=[{"description": g.description} for g in gaps[:4]],
                max_queries=4,
            )
            followup_queries = [gq.query for gq in generated]

        logger.info(
            "ResearchCritic 反思评估完成 | turn=%d | sufficient=%s | coverage=%.1f%% | gaps=%d | followup=%d",
            current_turn,
            is_sufficient,
            coverage_rate * 100,
            len(gaps),
            len(followup_queries),
        )

        return ReflectionResult(
            turn=current_turn,
            is_sufficient=is_sufficient,
            gaps=gaps,
            conflicts=conflicts,
            followup_queries=followup_queries,
            reasoning="；".join(reasons),
        )
