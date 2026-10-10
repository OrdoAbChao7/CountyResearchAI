"""评测基准数据集。

为三个县域产业研究核心案例定义基准参考数据、关键事实点和核验标准：
- 案例 A：安吉县竹产业（现状、产值、政策、产业链）
- 案例 B：信丰县脐橙产业（历史、统计时效、官方公报、经济贡献）
- 案例 C：鹤岗市产业转型（长周期、产业变迁、人口经济、多来源交叉）
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FactPoint:
    """单个需被检索或分析覆盖的黄金事实点。"""
    id: str
    category: str              # economic / policy / industry / history / risk
    claim_template: str        # 事实陈述模版
    keywords: list[str]        # 核心关键词
    expected_values: list[str] # 期望包含的值或数值口径
    min_year: int | None = None # 最低有效年份
    is_critical: bool = True   # 是否为核心关键事实
    official_preferred: bool = True # 是否优先需要官方/公报来源


@dataclass(frozen=True)
class BenchmarkCase:
    """基准研究案例。"""
    case_id: str
    county: str
    focus: str
    mode: str
    description: str
    province: str
    prefecture: str
    ground_truth_facts: list[FactPoint]
    reference_sources: list[dict[str, str]]
    disambiguation_risk: str # 消歧风险点说明


# 案例 A：安吉县竹产业
CASE_A_ANJI = BenchmarkCase(
    case_id="case_a_anji",
    county="安吉县",
    focus="竹产业",
    mode="snapshot",
    description="安吉县竹产业现状、产值数据、以竹代塑政策与全产业链格局",
    province="浙江省",
    prefecture="湖州市",
    disambiguation_risk="避免将湖州市全市数据误作安吉县本级数据；需区分竹林面积与竹材加工产值",
    ground_truth_facts=[
        FactPoint(
            id="anji_area",
            category="economic",
            claim_template="安吉县竹林面积约为100万亩左右（约101.1万亩）",
            keywords=["安吉", "竹林面积", "万亩"],
            expected_values=["100", "101", "101.1"],
            is_critical=True,
        ),
        FactPoint(
            id="anji_output",
            category="economic",
            claim_template="安吉县竹产业总产值超200亿元（约250亿-300亿元规模）",
            keywords=["总产值", "竹产业", "亿元"],
            expected_values=["200", "250", "280", "300"],
            min_year=2021,
            is_critical=True,
        ),
        FactPoint(
            id="anji_policy_substitute",
            category="policy",
            claim_template="以竹代塑国家与省级创新政策扶持行动",
            keywords=["以竹代塑", "政策", "行动方案", "意见"],
            expected_values=["以竹代塑", "三年行动计划", "国家发展改革委"],
            is_critical=True,
        ),
        FactPoint(
            id="anji_supply_chain",
            category="industry",
            claim_template="涵盖竹机械、竹地板、竹纤维、竹炭、竹文旅全产业链",
            keywords=["产业链", "竹地板", "竹机械", "加工", "龙头企业"],
            expected_values=["全产业链", "竹机械", "竹地板", "龙头"],
            is_critical=False,
        ),
        FactPoint(
            id="anji_risk_cost",
            category="risk",
            claim_template="面临采伐用工成本高、劳动力老龄化、原竹下山难等制约",
            keywords=["用工成本", "劳动力", "采伐", "下山难", "老龄化"],
            expected_values=["成本", "劳动力", "用工", "下山"],
            is_critical=False,
        ),
    ],
    reference_sources=[
        {"name": "安吉县人民政府", "domain": "anji.gov.cn", "type": "government"},
        {"name": "国家发改委《加快“以竹代塑”发展三年行动计划》", "domain": "ndrc.gov.cn", "type": "government"},
        {"name": "浙江省统计局", "domain": "tjj.zj.gov.cn", "type": "government"},
    ],
)

# 案例 B：信丰县脐橙产业
CASE_B_XINFENG = BenchmarkCase(
    case_id="case_b_xinfeng",
    county="信丰县",
    focus="脐橙产业",
    mode="snapshot",
    description="信丰县赣南脐橙发源地历史、种植面积、产量产值时效与深加工龙头企业",
    province="江西省",
    prefecture="赣州市",
    disambiguation_risk="信丰县脐橙常与赣州市（赣南脐橙）全区总量混淆，需精准区分信丰县本级种植面积与全市百万亩总量",
    ground_truth_facts=[
        FactPoint(
            id="xinfeng_origin",
            category="history",
            claim_template="信丰县是赣南脐橙的发源地，1971年由袁守根在郭磊庄引种试种成功",
            keywords=["发源地", "1971", "袁守根", "郭磊庄", "引种"],
            expected_values=["发源地", "1971", "袁守根"],
            is_critical=True,
        ),
        FactPoint(
            id="xinfeng_acreage",
            category="economic",
            claim_template="信丰县脐橙种植面积约25万-28万亩左右",
            keywords=["种植面积", "信丰", "万亩", "脐橙"],
            expected_values=["25", "26", "27", "28"],
            min_year=2021,
            is_critical=True,
        ),
        FactPoint(
            id="xinfeng_output_value",
            category="economic",
            claim_template="信丰脐橙产业综合产值或鲜果产值超20亿-30亿元",
            keywords=["产值", "亿元", "信丰", "脐橙"],
            expected_values=["20", "25", "30", "35"],
            min_year=2021,
            is_critical=True,
        ),
        FactPoint(
            id="xinfeng_enterprise",
            category="industry",
            claim_template="引进农夫山泉等深加工龙头企业，建设脐橙全果利用深加工基地",
            keywords=["农夫山泉", "深加工", "果汁", "龙头企业"],
            expected_values=["农夫山泉", "果汁", "深加工"],
            is_critical=True,
        ),
        FactPoint(
            id="xinfeng_disease_control",
            category="risk",
            claim_template="黄龙病综合防控与智慧果园精准管理是产业安全底线",
            keywords=["黄龙病", "防控", "木虱", "智慧果园", "苗木"],
            expected_values=["黄龙病", "防控", "智慧果园"],
            is_critical=False,
        ),
    ],
    reference_sources=[
        {"name": "信丰县人民政府", "domain": "jxxf.gov.cn", "type": "government"},
        {"name": "赣州市果业发展中心", "domain": "gyj.ganzhou.gov.cn", "type": "government"},
        {"name": "江西省统计局", "domain": "tjj.jiangxi.gov.cn", "type": "government"},
    ],
)

# 案例 C：鹤岗市产业转型
CASE_C_HEGANG = BenchmarkCase(
    case_id="case_c_hegang",
    county="鹤岗市",
    focus="产业转型",
    mode="rise-fall",
    description="鹤岗市百年煤炭工业崛起、资源枯竭型城市演进、人口收缩与向石墨新材料转型",
    province="黑龙江省",
    prefecture="鹤岗市",
    disambiguation_risk="鹤岗市为地级市，避免将辖区六区（向阳、南山等）与两县（萝北、绥滨）混为一县；避免房产自媒体噪音掩盖产业本质",
    ground_truth_facts=[
        FactPoint(
            id="hegang_coal_history",
            category="history",
            claim_template="1917年发现煤田，建国后成为国家重要煤炭能源基地，具备百年煤城历史",
            keywords=["煤田", "1917", "煤城", "煤炭基地", "矿区"],
            expected_values=["1917", "百年煤城", "煤矿", "煤炭"],
            is_critical=True,
        ),
        FactPoint(
            id="hegang_resource_exhaustion",
            category="risk",
            claim_template="2011年被列入国家第三批资源枯竭型城市，面临一煤独大、产能关停冲击",
            keywords=["资源枯竭", "2011", "第三批", "一煤独大", "关停"],
            expected_values=["2011", "资源枯竭", "枯竭型城市"],
            is_critical=True,
        ),
        FactPoint(
            id="hegang_demographics",
            category="risk",
            claim_template="人口持续外流收缩与老龄化加剧，七普常住人口显著减少至百万人以下",
            keywords=["人口流出", "收缩", "老龄化", "七普", "常住人口"],
            expected_values=["人口", "流失", "收缩", "89", "90"],
            is_critical=True,
        ),
        FactPoint(
            id="hegang_graphite_transition",
            category="industry",
            claim_template="依托萝北石墨资源优势，培育石墨精深加工、负极材料等千亿级新能源材料转型主导产业",
            keywords=["石墨", "萝北", "新材料", "负极材料", "石墨烯"],
            expected_values=["石墨", "萝北", "新材料", "转型"],
            is_critical=True,
        ),
        FactPoint(
            id="hegang_fiscal_reorganization",
            category="economic",
            claim_template="财政重整与接续替代产业培育并进，推进生态修复与文旅边贸发展",
            keywords=["财政重整", "生态修复", "文旅", "替代产业"],
            expected_values=["重整", "生态", "转型", "替代"],
            is_critical=False,
        ),
    ],
    reference_sources=[
        {"name": "鹤岗市人民政府", "domain": "hegang.gov.cn", "type": "government"},
        {"name": "国家发改委振兴司资源型城市名录", "domain": "ndrc.gov.cn", "type": "government"},
        {"name": "黑龙江省统计局", "domain": "tjj.hlj.gov.cn", "type": "government"},
    ],
)

BENCHMARK_CASES = {
    "case_a_anji": CASE_A_ANJI,
    "case_b_xinfeng": CASE_B_XINFENG,
    "case_c_hegang": CASE_C_HEGANG,
}


def get_benchmark_case(case_id: str) -> BenchmarkCase:
    if case_id not in BENCHMARK_CASES:
        raise KeyError(f"Unknown benchmark case: {case_id}")
    return BENCHMARK_CASES[case_id]
