"""动态研究问题树生成器 (ResearchTree)。

根据县域名称、研究方向和研究模式，动态拆解为多层次的结构化研究问题树，
明确每个子问题必须检索和核验的核心指标与关键要素。
"""
from __future__ import annotations

from ..models import QuestionTree, ResearchQuestion


def build_question_tree(
    county: str,
    focus: str | None = None,
    mode: str = "snapshot",
) -> QuestionTree:
    """根据研究模式生成定制化研究问题树。"""
    c_name = county.strip()
    f_name = (focus or "").strip()

    if mode == "rise-fall":
        return _build_rise_fall_tree(c_name, f_name)
    elif mode == "long-history":
        return _build_long_history_tree(c_name, f_name)
    else:
        return _build_snapshot_tree(c_name, f_name)


def _build_snapshot_tree(county: str, focus: str) -> QuestionTree:
    target = focus or "主导特色产业"
    questions = [
        ResearchQuestion(
            id="q_scale",
            title=f"{county}{target}产业规模与经济贡献",
            category="economic",
            description=f"查清{county}{target}的总产值、规上工业产值、增加值、全县GDP占比及近期增速。",
            required_indicators=["总产值", "规上产值", "增速", "GDP占比", "统计公报"],
        ),
        ResearchQuestion(
            id="q_production",
            title=f"{county}{target}种植/开采/产能规模",
            category="economic",
            description=f"查清{county}{target}的基础规模（如种植面积、采伐量、年产量等实物指标）。",
            required_indicators=["面积", "产量", "产能", "规模"],
        ),
        ResearchQuestion(
            id="q_policy",
            title=f"{county}{target}政策扶持与中长期规划",
            category="policy",
            description=f"查清党委政府关于{target}的十四五规划、专项扶持政策、用地用林及财政补贴文件。",
            required_indicators=["十四五", "规划", "政策", "意见", "方案"],
        ),
        ResearchQuestion(
            id="q_supply_chain",
            title=f"{county}{target}产业链图谱与骨干企业",
            category="industry",
            description="梳理产业链上下游配套、链主龙头企业、产业园集聚及专精特新企业布局。",
            required_indicators=["产业链", "龙头企业", "园区", "链主", "加工"],
        ),
        ResearchQuestion(
            id="q_market",
            title=f"{county}{target}销售渠道与品牌竞争力",
            category="industry",
            description="考证区域公共品牌建设、电商流通渠道、深加工利用及国内外市场竞争格局。",
            required_indicators=["品牌", "市场", "销售", "电商", "深加工"],
        ),
        ResearchQuestion(
            id="q_risks",
            title=f"{county}{target}痛点短板与未来破局路径",
            category="risk",
            description="分析劳动力要素成本、生态环境约束、技术瓶颈及面临的外部竞争风险。",
            required_indicators=["成本", "短板", "瓶颈", "风险", "挑战"],
        ),
    ]
    return QuestionTree(county=county, focus=focus, mode="snapshot", questions=questions)


def _build_rise_fall_tree(county: str, focus: str) -> QuestionTree:
    topic = focus or "主导产业"
    questions = [
        ResearchQuestion(
            id="rf_origin",
            title=f"{county}{topic}起步立县要素禀赋",
            category="history",
            description="考证早期立县起家产业、资源禀赋与政策历史机遇。",
            required_indicators=["起家", "资源", "起源", "早期", "历史"],
        ),
        ResearchQuestion(
            id="rf_golden_age",
            title=f"{county}{topic}黄金扩张期与产业极盛画像",
            category="economic",
            description="查明产业扩张期的巅峰产值、企业规模及在全国或全省的产业地位。",
            required_indicators=["巅峰", "鼎盛", "扩张", "产值", "龙头"],
        ),
        ResearchQuestion(
            id="rf_turning_points",
            title=f"{county}{topic}发展拐点与衰落驱动因子",
            category="risk",
            description="剖析资源枯竭、环保关停、技术替代或产业转移等导致由盛转衰的致命拐点。",
            required_indicators=["资源枯竭", "关停", "衰退", "拐点", "冲击"],
        ),
        ResearchQuestion(
            id="rf_talent_drain",
            title=f"{county}人口收缩与财政变迁轨迹",
            category="economic",
            description="结合人口普查与财政公报，分析人才流失、人口收缩与财政承压机制。",
            required_indicators=["人口流出", "收缩", "老龄化", "财政收入", "公报"],
        ),
        ResearchQuestion(
            id="rf_transformation",
            title=f"{county}转型探索与接续替代产业培育",
            category="industry",
            description="查清县域当前探索的转型突破口（新材料、文旅、高端制造等）及成效。",
            required_indicators=["转型", "接续产业", "新动能", "规划"],
        ),
    ]
    return QuestionTree(county=county, focus=focus, mode="rise-fall", questions=questions)


def _build_long_history_tree(county: str, focus: str) -> QuestionTree:
    questions = [
        ResearchQuestion(
            id="lh_origins",
            title=f"{county}建县沿革与地理区位",
            category="history",
            description="考证建县历史、历代行政区划演变与地缘边界功能。",
            required_indicators=["建县", "沿革", "县志", "区划", "地理"],
        ),
        ResearchQuestion(
            id="lh_traditional",
            title=f"{county}传统时代的地理历史因子与生存逻辑",
            category="history",
            description="基于地方志考证传统农业、驿道水运商贸及移民生存逻辑。",
            required_indicators=["驿道", "水运", "商贸", "地方志", "农业"],
        ),
        ResearchQuestion(
            id="lh_modern",
            title=f"{county}近代工商业冲击与变迁",
            category="history",
            description="梳理近现代交通线变动、战乱与早期工业萌芽带来的社会冲击。",
            required_indicators=["近代", "工业", "商业", "铁路", "交通"],
        ),
        ResearchQuestion(
            id="lh_state_period",
            title=f"{county}计划经济时期的国家力量再组织",
            category="history",
            description="分析1949-1978年间国营工矿、水利建设、供销社对县域的重塑。",
            required_indicators=["计划经济", "国营", "工矿", "水利", "农垦"],
        ),
        ResearchQuestion(
            id="lh_reform",
            title=f"{county}改革开放以来的特色产业重塑",
            category="economic",
            description="考察改革开放后民营企业崛起、专业市场与特色产业集群发展。",
            required_indicators=["改革开放", "民营", "专业市场", "产业集群"],
        ),
        ResearchQuestion(
            id="lh_pattern",
            title=f"{county}长周期命运主线与结构规律",
            category="general",
            description="归纳决定该县数百年兴衰变迁的核心深层结构变量与历史模式。",
            required_indicators=["长周期", "规律", "兴衰", "命运"],
        ),
    ]
    return QuestionTree(county=county, focus=focus, mode="long-history", questions=questions)
