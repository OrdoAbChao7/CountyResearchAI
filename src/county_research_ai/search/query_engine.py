"""动态检索与查询展开引擎 (QueryEngine)。

借鉴 BettaFish QueryEngine 设计思想：
1. 摆脱单一死板关键词模版，按经济规模、政策规划、产业链企业、市场渠道、历史沿革等多维度动态生成检索词；
2. 结合行政区划消歧上下文（省份/地级市限定词），避免同名县域或地级市总量混淆；
3. 专业词动态扩展（“国民经济与社会发展统计公报”、“十四五规划”、“规上工业总产值”等）；
4. 反思补充检索词生成（针对 Critic 识别的证据缺口与矛盾进行定向补充挖掘）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .disambiguation import disambiguate_region


class QueryIntent(str, Enum):
    ECONOMIC_SCALE = "economic_scale"      # 产值规模、统计公报、增速、占比
    POLICY_PLANNING = "policy_planning"    # 产业规划、十四五、扶持政策、实施方案
    SUPPLY_CHAIN = "supply_chain"          # 龙头企业、产业链布局、园区集聚
    MARKET_CHANNELS = "market_channels"    # 销售市场、品牌培育、电商流通、外贸出口
    HISTORICAL_MILESTONES = "historical"   # 历史沿革、起家起源、兴衰拐点、变迁
    RISK_BOTTLENECK = "risk_bottleneck"    # 短板瓶颈、要素成本、环境制约、转型挑战


@dataclass(frozen=True)
class GeneratedQuery:
    """生成的单条检索查询。"""
    query: str
    intent: QueryIntent
    target_channel: str = "web"  # web / gov
    priority: int = 1            # 优先级（1 最高）
    explanation: str = ""


class QueryEngine:
    """多维度动态搜索词生成与查询展开引擎。"""

    def __init__(self, default_gov_ratio: float = 0.4) -> None:
        self.default_gov_ratio = default_gov_ratio

    def generate_research_queries(
        self,
        county: str,
        focus: str | None = None,
        mode: str = "snapshot",
        max_queries: int = 12,
    ) -> list[GeneratedQuery]:
        """根据县域、研究方向和研究模式动态生成首轮检索查询计划。"""
        disambig = disambiguate_region(county)
        clean_county = disambig.clean_name
        focus_term = (focus or "").strip()
        prefix = disambig.get_preferred_query_prefix()

        queries: list[GeneratedQuery] = []

        if mode == "rise-fall":
            queries.extend(self._generate_rise_fall_queries(clean_county, prefix, focus_term))
        elif mode == "long-history":
            queries.extend(self._generate_long_history_queries(clean_county, prefix, focus_term))
        else:
            queries.extend(self._generate_snapshot_queries(clean_county, prefix, focus_term))

        # 按优先级排序并截断
        queries.sort(key=lambda q: q.priority)
        return queries[:max_queries]

    def generate_reflection_queries(
        self,
        county: str,
        focus: str | None,
        gaps: list[dict[str, Any]] | list[str],
        max_queries: int = 5,
    ) -> list[GeneratedQuery]:
        """针对反思阶段发现的信息缺口，生成高针对性的补充检索词。"""
        disambig = disambiguate_region(county)
        c_name = disambig.clean_name
        focus_term = (focus or "").strip()

        reflection_queries: list[GeneratedQuery] = []

        for gap in gaps:
            gap_desc = gap.get("description", str(gap)) if isinstance(gap, dict) else str(gap)
            intent = QueryIntent.ECONOMIC_SCALE
            if "政策" in gap_desc or "规划" in gap_desc:
                intent = QueryIntent.POLICY_PLANNING
                q_text = f"{c_name} {focus_term} 政策文件 十四五 专项扶持 实施意见".strip()
            elif "企业" in gap_desc or "产业链" in gap_desc or "龙头" in gap_desc:
                intent = QueryIntent.SUPPLY_CHAIN
                q_text = f"{c_name} {focus_term} 龙头企业 骨干企业 专精特新 产业链".strip()
            elif "历史" in gap_desc or "起家" in gap_desc or "拐点" in gap_desc:
                intent = QueryIntent.HISTORICAL_MILESTONES
                q_text = f"{c_name} {focus_term} 历史 县志 发展历程 拐点 起源".strip()
            elif "产值" in gap_desc or "数据" in gap_desc or "面积" in gap_desc or "统计" in gap_desc:
                intent = QueryIntent.ECONOMIC_SCALE
                q_text = f"{c_name} 统计公报 国民经济 {focus_term} 产值 产量 面积 最新".strip()
            else:
                q_text = f"{c_name} {focus_term} {gap_desc[:15]}".strip()

            reflection_queries.append(
                GeneratedQuery(
                    query=q_text,
                    intent=intent,
                    target_channel="gov" if intent in (QueryIntent.ECONOMIC_SCALE, QueryIntent.POLICY_PLANNING) else "web",
                    priority=1,
                    explanation=f"补充缺口: {gap_desc[:30]}",
                )
            )

        return reflection_queries[:max_queries]

    def _generate_snapshot_queries(
        self, county: str, prefix: str, focus: str
    ) -> list[GeneratedQuery]:
        focus_str = focus or "优势特色产业"
        queries = [
            # 维度 1：宏观公报与官方统计
            GeneratedQuery(
                query=f"{county} 统计公报 国民经济和社会发展统计公报",
                intent=QueryIntent.ECONOMIC_SCALE,
                target_channel="gov",
                priority=1,
                explanation="检索官方年度国民经济与社会发展统计公报基石数据",
            ),
            # 维度 2：产业产值与经济贡献
            GeneratedQuery(
                query=f"{county} {focus_str} 总产值 规上工业 增加值 增速 占比",
                intent=QueryIntent.ECONOMIC_SCALE,
                target_channel="web",
                priority=1,
                explanation="检索该产业规模、产值体量及经济增长数据",
            ),
            # 维度 3：产业政策与十四五规划
            GeneratedQuery(
                query=f"{county} {focus_str} 十四五 产业发展规划 扶持政策 实施意见",
                intent=QueryIntent.POLICY_PLANNING,
                target_channel="gov",
                priority=2,
                explanation="检索地方党委政府关于该产业的中长期规划与配套政策",
            ),
            # 维度 4：龙头企业与产业链图谱
            GeneratedQuery(
                query=f"{county} {focus_str} 龙头企业 链主企业 产业园 专精特新 招商引资",
                intent=QueryIntent.SUPPLY_CHAIN,
                target_channel="web",
                priority=2,
                explanation="挖掘骨干企业、链主企业与产业空间集聚情况",
            ),
            # 维度 5：市场渠道与品牌竞争
            GeneratedQuery(
                query=f"{county} {focus_str} 销售市场 品牌价值 电商 展会 外贸出口",
                intent=QueryIntent.MARKET_CHANNELS,
                target_channel="web",
                priority=3,
                explanation="考察终端市场、区域公共品牌与销售渠道体系",
            ),
            # 维度 6：制约因素与短板风险
            GeneratedQuery(
                query=f"{county} {focus_str} 发展瓶颈 短板 挑战 风险 要素成本",
                intent=QueryIntent.RISK_BOTTLENECK,
                target_channel="web",
                priority=3,
                explanation="探究发展过程中的制约因素与转型痛点",
            ),
        ]

        # 如果有地级市/省份限定前缀，追加 1-2 条精准消歧检索词
        if prefix != county:
            queries.append(
                GeneratedQuery(
                    query=f"{prefix} {focus_str} 特色产业 发展现状",
                    intent=QueryIntent.ECONOMIC_SCALE,
                    target_channel="web",
                    priority=2,
                    explanation="添加省市前缀消歧检索",
                )
            )

        return queries

    def _generate_rise_fall_queries(
        self, county: str, prefix: str, focus: str
    ) -> list[GeneratedQuery]:
        topic = focus or "主导产业"
        return [
            GeneratedQuery(
                query=f"{county} {topic} 历史 发展演变 起家产业",
                intent=QueryIntent.HISTORICAL_MILESTONES,
                target_channel="web",
                priority=1,
                explanation="追溯县域早期立县产业与起步要素禀赋",
            ),
            GeneratedQuery(
                query=f"{county} 地方志 县志 工业 农业 变迁",
                intent=QueryIntent.HISTORICAL_MILESTONES,
                target_channel="web",
                priority=2,
                explanation="查阅地方志关于工农业经济演变记录",
            ),
            GeneratedQuery(
                query=f"{county} {topic} 黄金期 鼎盛时期 产值 龙头企业",
                intent=QueryIntent.ECONOMIC_SCALE,
                target_channel="web",
                priority=1,
                explanation="剖析产业扩张壮大期的高光表现与驱动机制",
            ),
            GeneratedQuery(
                query=f"{county} 资源枯竭 环保整治 产能关停 产业衰退",
                intent=QueryIntent.RISK_BOTTLENECK,
                target_channel="web",
                priority=1,
                explanation="寻找产业由盛转衰的关键转折点与外部冲击",
            ),
            GeneratedQuery(
                query=f"{county} 统计公报 人口流出 人口收缩 财政收入",
                intent=QueryIntent.ECONOMIC_SCALE,
                target_channel="gov",
                priority=2,
                explanation="结合统计公报分析人口与财政变迁轨迹",
            ),
            GeneratedQuery(
                query=f"{county} 产业转型 接续产业 新材料 培育发展",
                intent=QueryIntent.POLICY_PLANNING,
                target_channel="gov",
                priority=2,
                explanation="了解县域当前探索的产业转型突破口与新旧动能转换",
            ),
        ]

    def _generate_long_history_queries(
        self, county: str, prefix: str, focus: str
    ) -> list[GeneratedQuery]:
        return [
            GeneratedQuery(
                query=f"{county} 建县 历史 沿革 设县由来",
                intent=QueryIntent.HISTORICAL_MILESTONES,
                target_channel="web",
                priority=1,
                explanation="考证建县历史与行政区划变迁脉络",
            ),
            GeneratedQuery(
                query=f"{county} 县志 地方志 地理 驿道 水运 商贸",
                intent=QueryIntent.HISTORICAL_MILESTONES,
                target_channel="web",
                priority=1,
                explanation="县志地方志考证传统时代的地理与生存逻辑",
            ),
            GeneratedQuery(
                query=f"{county} 近代 商业 工业 战争 铁路 冲击",
                intent=QueryIntent.HISTORICAL_MILESTONES,
                target_channel="web",
                priority=2,
                explanation="近代外部冲击对传统社会的瓦解与重构",
            ),
            GeneratedQuery(
                query=f"{county} 计划经济 国营企业 矿区 水利 农垦",
                intent=QueryIntent.HISTORICAL_MILESTONES,
                target_channel="web",
                priority=2,
                explanation="1949-1978计划经济时期国家力量对县域的再组织",
            ),
            GeneratedQuery(
                query=f"{county} 改革开放 民营经济 专业市场 产业集群 演变",
                intent=QueryIntent.HISTORICAL_MILESTONES,
                target_channel="web",
                priority=2,
                explanation="改革开放后县域经济自主探索与特色产业形成",
            ),
            GeneratedQuery(
                query=f"{county} 长周期 兴衰 历史规律 命运总结",
                intent=QueryIntent.HISTORICAL_MILESTONES,
                target_channel="web",
                priority=3,
                explanation="长周期深层结构因子与规律归纳",
            ),
        ]
