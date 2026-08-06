"""Mock 搜索实现。

MockSearchProvider 返回构造的示例 RawDoc,链路可跑不需要真实搜索 API。
根据 query 中的关键词生成带有县名和产业方向的示例文档。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..models import RawDoc
from ..search.base import SearchProvider

logger = logging.getLogger(__name__)


class MockSearchProvider(SearchProvider):
    """Mock 搜索:返回构造的示例 RawDoc,链路可跑不需要真实 API。"""

    name = "mock"

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        logger.debug("MockSearch.search | query=%s", query)
        parts = query.split()
        county_hint = parts[0] if parts else "某县"
        focus_hint = parts[1] if len(parts) > 1 else "产业"
        now = datetime.now(timezone.utc)
        return [
            RawDoc(
                title=f"{county_hint}{focus_hint}产业年产值突破百亿",
                url=f"https://example.gov.cn/{county_hint}/tjgb-1",
                snippet="近年该县特色产业快速发展,规上企业超过80家,从业人员超3万人。",
                content=(
                    f"据{county_hint}2025年统计公报,{focus_hint}产业规上企业达到82家,"
                    f"实现产值120亿元,同比增长15%。产业园区占地约2000亩,"
                    f"入驻企业56家,形成了上游种植、中游加工、下游销售的完整链条。"
                ),
                source="mock-gov",
                fetched_at=now,
            ),
            RawDoc(
                title=f"{county_hint}十四五{focus_hint}产业发展规划",
                url=f"https://example.gov.cn/{county_hint}/fzgh-2",
                snippet="该县十四五规划明确提出重点打造百亿级特色产业集群。",
                content=(
                    f"《{county_hint}十四五{focus_hint}产业发展规划》提出:"
                    f"到2027年实现产值200亿元,培育龙头企业10家,"
                    f"建成省级产业园区1个,公共服务平台3个。"
                    f"重点方向:品牌建设、精深加工、冷链物流、电子商务。"
                ),
                source="mock-gov",
                fetched_at=now,
            ),
            RawDoc(
                title=f"龙头XX股份带动{focus_hint}产业升级",
                url=f"https://example.com/news/{county_hint}-top-enterprise",
                snippet=f"本地龙头XX股份{focus_hint}精深加工线投产,年新增产值20亿。",
                content=(
                    f"本地龙头企业XX股份2024年投产国内首条智能化{focus_hint}精深加工线,"
                    f"年产能达12万吨,新增产值约20亿元。该企业通过'公司+合作社+农户'模式,"
                    f"带动全县6000余农户增收,户均年增收约1.5万元。"
                ),
                source="mock-news",
                fetched_at=now,
            ),
        ]
