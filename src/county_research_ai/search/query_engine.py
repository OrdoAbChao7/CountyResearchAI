"""动态检索与查询展开引擎 (QueryEngine)。

借鉴 BettaFish QueryEngine 设计思想：
1. 摆脱单一死板关键词模版，按经济规模、政策规划、产业链企业、市场渠道、历史沿革等多维度动态生成检索词；
2. 结合行政区划消歧上下文（省份/地级市限定词），避免同名县域或地级市总量混淆；
3. 专业词动态扩展（“国民经济与社会发展统计公报”、“十四五规划”、“规上工业总产值”等）；
4. 反思补充检索词生成（针对 Critic 识别的证据缺口与矛盾进行定向补充挖掘）。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from ..domain.research_contracts import QuestionSlot, ResearchSpec
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
    slot_id: str = ""
    expected_metrics: tuple[str, ...] = ()
    gap_id: str = ""


_MODE_SLOT_DEFINITIONS: dict[str, tuple[tuple[str, str, tuple[str, ...], int], ...]] = {
    "snapshot": (
        ("economic_scale", "目标年度经济规模与增速", ("地区生产总值", "总产值", "增加值", "增速"), 1),
        ("industry_structure", "产业结构与县域贡献", ("产业结构", "规上工业", "产业占比"), 1),
        ("supply_chain", "龙头企业与产业链", ("龙头企业", "产业链", "园区"), 1),
        ("policy", "政策、园区与规划", ("政策", "规划", "十四五"), 2),
        ("market", "市场渠道与品牌竞争", ("市场", "销售", "品牌"), 2),
        ("risk", "现状风险与发展瓶颈", ("风险", "瓶颈", "挑战"), 2),
    ),
    "rise-fall": (
        ("origin", "兴起条件与早期产业", ("起家", "资源", "起源", "历史"), 1),
        ("growth", "重要增长节点与产业高峰", ("增长", "高峰", "鼎盛", "产值"), 1),
        ("decline", "衰退或转型迹象", ("衰退", "转型", "拐点", "关停"), 1),
        ("structural", "兴衰的结构性原因", ("原因", "冲击", "资源", "环保"), 2),
        ("adjustment", "当前调整措施", ("调整", "接续产业", "规划"), 2),
    ),
    "long-history": (
        ("administration", "历史时期与行政区划", ("建县", "沿革", "区划", "县志"), 1),
        ("geography", "地理与交通条件", ("地理", "交通", "驿道", "水运"), 1),
        ("traditional", "传统经济基础", ("传统", "农业", "商贸", "地方志"), 1),
        ("industrialization", "工业化历史", ("近代", "工业", "商业", "铁路"), 2),
        ("planned", "计划经济阶段", ("计划经济", "国营", "工矿", "水利"), 2),
        ("reform", "改革开放影响与现代转型", ("改革开放", "民营", "产业集群", "转型"), 2),
    ),
}


def _normalize_years(years: Iterable[str] | None) -> list[str]:
    result: list[str] = []
    for value in years or []:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def _year_token(years: Iterable[str] | None) -> str:
    values = _normalize_years(years)
    if not values:
        return ""
    if len(values) == 1:
        return f"{values[0]}年"
    return f"{values[0]}-{values[-1]}年"


def _period_label(years: Iterable[str] | None) -> str:
    values = _normalize_years(years)
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return f"{values[0]}-{values[-1]}"


def _with_year_query(
    queries: list[GeneratedQuery],
    county: str,
    year_token: str,
) -> list[GeneratedQuery]:
    """Ensure at least one statutory statistical query names the target year."""
    if not year_token or any(year_token in query.query for query in queries):
        return queries
    return [
        GeneratedQuery(
            query=f"{county} {year_token} 统计公报 国民经济和社会发展统计公报",
            intent=QueryIntent.ECONOMIC_SCALE,
            target_channel="gov",
            priority=1,
            explanation="检索目标期间官方统计公报",
        ),
        *queries,
    ]


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
        *,
        target_years: Iterable[str] | None = None,
    ) -> list[GeneratedQuery]:
        """根据县域、研究方向和研究模式动态生成首轮检索查询计划。"""
        disambig = disambiguate_region(county)
        clean_county = disambig.clean_name
        focus_term = (focus or "").strip()
        prefix = disambig.get_preferred_query_prefix()
        year_token = _year_token(target_years)

        queries: list[GeneratedQuery] = []

        if mode == "rise-fall":
            queries.extend(self._generate_rise_fall_queries(clean_county, prefix, focus_term))
        elif mode == "long-history":
            queries.extend(self._generate_long_history_queries(clean_county, prefix, focus_term))
        else:
            queries.extend(
                self._generate_snapshot_queries(
                    clean_county, prefix, focus_term, year_token=year_token
                )
            )
        queries = _with_year_query(queries, clean_county, year_token)

        # 按优先级排序并截断
        queries.sort(key=lambda q: q.priority)
        return self._annotate_queries(queries[:max_queries], clean_county, focus_term, mode)

    def generate_period_queries(
        self,
        county: str,
        focus: str | None = None,
        target_years: Iterable[str] | None = None,
        *,
        max_queries: int = 2,
    ) -> list[GeneratedQuery]:
        """Build supplemental queries that explicitly name the target period.

        These are used when topical coverage is satisfied but no selected claim
        falls inside the requested years. The wording differs from the first
        snapshot query so a follow-up round does not repeat it verbatim.
        """
        year_token = _year_token(target_years)
        if not year_token or max_queries <= 0:
            return []
        disambig = disambiguate_region(county)
        clean_county = disambig.clean_name
        focus_term = (focus or "产业").strip()
        candidates = [
            GeneratedQuery(
                query=f"{clean_county} {year_token} 统计年鉴 统计公报 主要经济指标",
                intent=QueryIntent.ECONOMIC_SCALE,
                target_channel="gov",
                priority=1,
                explanation="补充目标期间官方统计资料",
            ),
            GeneratedQuery(
                query=f"{clean_county} {focus_term} {year_token} 产值 产量 统计数据",
                intent=QueryIntent.ECONOMIC_SCALE,
                target_channel="web",
                priority=1,
                explanation="补充目标期间产业统计数据",
            ),
        ]
        return candidates[:max_queries]

    def generate_question_slots(
        self,
        county: str,
        focus: str | None = None,
        mode: str = "snapshot",
        *,
        budget_chars: int = 12000,
        target_years: Iterable[str] | None = None,
        time_period: str = "",
    ) -> list[QuestionSlot]:
        """Return explicit, mode-specific evidence requirements."""
        county_name = disambiguate_region(county).clean_name
        focus_name = (focus or "主导产业").strip()
        period = time_period or _period_label(target_years)
        definitions = _MODE_SLOT_DEFINITIONS.get(mode, _MODE_SLOT_DEFINITIONS["snapshot"])
        return [
            QuestionSlot(
                slot_id=f"{mode}:{slot_key}",
                research_question=f"{county_name}{focus_name}{question}",
                required_metrics=list(metrics),
                region=county_name,
                time_period=period,
                priority=priority,
                evidence_requirement="至少有一条可追溯原文片段和来源",
                budget_chars=budget_chars,
            )
            for slot_key, question, metrics, priority in definitions
        ]

    def generate_research_spec(
        self,
        county: str,
        focus: str | None = None,
        mode: str = "snapshot",
        *,
        budget_chars: int = 12000,
        target_years: Iterable[str] | None = None,
        time_period: str = "",
    ) -> ResearchSpec:
        county_name = disambiguate_region(county).clean_name
        years = _normalize_years(target_years)
        return ResearchSpec(
            region_id=county_name,
            region_name=county_name,
            mode=mode,
            research_focus=(focus or "").strip(),
            target_years=years,
            architecture_version="evidence_first_v2",
            required_question_slots=self.generate_question_slots(
                county_name,
                focus,
                mode,
                budget_chars=budget_chars,
                target_years=years,
                time_period=time_period,
            ),
            budget=budget_chars,
        )

    def generate_gap_queries(
        self,
        spec: ResearchSpec,
        missing_slots: list[str] | None = None,
        *,
        max_queries: int = 5,
    ) -> list[GeneratedQuery]:
        """Create follow-up queries linked to concrete missing QuestionSlots."""
        wanted = set(missing_slots or [slot.slot_id for slot in spec.question_slots])
        queries: list[GeneratedQuery] = []
        for slot in spec.question_slots:
            if slot.slot_id not in wanted:
                continue
            generated = self.generate_reflection_queries(
                spec.region_name,
                spec.research_focus,
                [{"description": f"{slot.research_question} {' '.join(slot.required_metrics)}"}],
                max_queries=1,
                target_years=spec.target_years,
            )
            for query in generated:
                queries.append(
                    replace(
                        query,
                        slot_id=slot.slot_id,
                        expected_metrics=tuple(slot.required_metrics),
                        gap_id=f"gap:{slot.slot_id}",
                        priority=slot.priority,
                    )
                )
        return sorted(queries, key=lambda item: (item.priority, item.slot_id, item.query))[:max_queries]

    @staticmethod
    def _annotate_queries(
        queries: list[GeneratedQuery],
        county: str,
        focus: str,
        mode: str,
    ) -> list[GeneratedQuery]:
        definitions = _MODE_SLOT_DEFINITIONS.get(mode, _MODE_SLOT_DEFINITIONS["snapshot"])
        slot_by_intent = {
            QueryIntent.ECONOMIC_SCALE: [item for item in definitions if item[0] in {"economic_scale", "growth", "decline"}],
            QueryIntent.POLICY_PLANNING: [item for item in definitions if item[0] in {"policy", "adjustment", "reform"}],
            QueryIntent.SUPPLY_CHAIN: [item for item in definitions if item[0] in {"supply_chain", "structural", "industrialization"}],
            QueryIntent.MARKET_CHANNELS: [item for item in definitions if item[0] in {"market", "traditional"}],
            QueryIntent.HISTORICAL_MILESTONES: [item for item in definitions if item[0] in {"origin", "administration", "geography", "planned", "traditional"}],
            QueryIntent.RISK_BOTTLENECK: [item for item in definitions if item[0] in {"risk", "decline", "structural"}],
        }
        counters: dict[QueryIntent, int] = {}
        annotated: list[GeneratedQuery] = []
        for query in queries:
            candidates = slot_by_intent.get(query.intent, list(definitions)) or list(definitions)
            index = counters.get(query.intent, 0)
            definition = candidates[index % len(candidates)]
            counters[query.intent] = index + 1
            annotated.append(
                replace(
                    query,
                    slot_id=f"{mode}:{definition[0]}",
                    expected_metrics=tuple(definition[2]),
                )
            )
        return annotated

    def generate_reflection_queries(
        self,
        county: str,
        focus: str | None,
        gaps: list[dict[str, Any]] | list[str],
        max_queries: int = 5,
        *,
        target_years: Iterable[str] | None = None,
    ) -> list[GeneratedQuery]:
        """针对反思阶段发现的信息缺口，生成高针对性的补充检索词。"""
        disambig = disambiguate_region(county)
        c_name = disambig.clean_name
        focus_term = (focus or "").strip()
        year_token = _year_token(target_years)

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
                q_text = (
                    f"{c_name} {year_token} 统计公报 国民经济 {focus_term} 产值 产量 面积 最新".strip()
                    if year_token
                    else f"{c_name} 统计公报 国民经济 {focus_term} 产值 产量 面积 最新".strip()
                )
            else:
                year_prefix = f"{year_token} " if year_token else ""
                q_text = f"{c_name} {year_prefix}{focus_term} {gap_desc[:15]}".strip()

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
        self, county: str, prefix: str, focus: str, *, year_token: str = ""
    ) -> list[GeneratedQuery]:
        focus_str = focus or "优势特色产业"
        year_prefix = f"{year_token} " if year_token else ""
        year_suffix = f" {year_token}" if year_token else ""
        queries = [
            # 维度 1：宏观公报与官方统计
            GeneratedQuery(
                query=f"{county} {year_prefix}统计公报 国民经济和社会发展统计公报",
                intent=QueryIntent.ECONOMIC_SCALE,
                target_channel="gov",
                priority=1,
                explanation="检索官方年度国民经济与社会发展统计公报基石数据",
            ),
            # 维度 2：产业产值与经济贡献
            GeneratedQuery(
                query=f"{county} {focus_str}{year_suffix} 总产值 规上工业 增加值 增速 占比",
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
