"""Mock LLM 实现。

MockLLMClient 根据 task 返回构造的分析文本,无需真实 LLM API。
支持 discovery / industry_status / advantages / shortcomings / recommendations / summary。
"""
from __future__ import annotations

import logging
from typing import Any

from ..llm.base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class MockLLMClient(LLMClient):
    """Mock LLM:根据 task 返回构造的分析文本,无需真实 API。"""

    name = "mock-llm"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        # 从 messages 中解析 task 关键词
        user_msg = "\n".join(m.get("content", "") for m in messages)
        task = "industry_status"
        if "产业方向" in user_msg and "识别" in user_msg:
            task = "discovery"
        elif "优势" in user_msg:
            task = "advantages"
        elif "短板" in user_msg or "风险" in user_msg:
            task = "shortcomings"
        elif "建议" in user_msg or "对策" in user_msg:
            task = "recommendations"

        content = {
            "discovery": (
                '{"candidates": ['
                '{"industry": "特色农业", "confidence": 0.85, '
                '"reason": "搜索结果显示该县农业占GDP 30%,规上企业80家", '
                '"evidence_urls": ["https://example.gov.cn/某县/tjgb-1", "https://example.gov.cn/某县/fzgh-2"], '
                '"related_keywords": ["年产值", "规上企业", "产业链", "产业园区"], '
                '"supporting_documents": ["某县2025年统计公报", "十四五产业发展规划"]}, '
                '{"industry": "乡村旅游", "confidence": 0.7, '
                '"reason": "多个政府规划提到乡村旅游与文旅融合", '
                '"evidence_urls": ["https://example.gov.cn/某县/fzgh-2"], '
                '"related_keywords": ["文旅", "乡村", "旅游", "民宿"], '
                '"supporting_documents": ["十四五产业发展规划"]}, '
                '{"industry": "先进制造业", "confidence": 0.55, '
                '"reason": "有省级工业园区,龙头企业投产精深加工线", '
                '"evidence_urls": ["https://example.com/news/某县-top-enterprise"], '
                '"related_keywords": ["工业园区", "制造业", "精深加工"], '
                '"supporting_documents": ["龙头XX股份带动产业升级"]}'
                '], "selected_focus": "特色农业"}'
            ),
            "industry_status": (
                "## 产业概况\n"
                "该县该产业已形成'种植(上游)—加工(中游)—销售(下游)'完整产业链,"
                "规上企业80余家,2025年产值约120亿元,占全县GDP约18%,是县域经济第一支柱产业。\n\n"
                "## 产业链结构\n"
                "- 上游:种源培育与规模化种植,全县种植面积约50万亩\n"
                "- 中游:82家规上加工企业,主要产品为初加工原料、食品、保健品三大类\n"
                "- 下游:覆盖全国的线下经销网络 + 电商渠道占比已达35%\n\n"
                "## 市场主体\n"
                "1家主板上市龙头,3家省级专精特新企业,产业园区1个(省级),入驻企业56家。\n\n"
                "## 发展阶段判断\n"
                "处于**成长期后期向成熟期过渡**阶段——规模基本形成,但精深加工与品牌溢价仍有提升空间。"
            ),
            "advantages": (
                "## 核心优势\n"
                "1. **资源禀赋** — 县域气候土壤适配度全国Top3,原料品质稳定,具备产地差异化基础\n"
                "2. **产业基础** — 60年种植传统,熟练工人充足,配套加工产能集中\n"
                "3. **龙头带动** — XX股份上市后具备全国品牌影响力,精深加工技术领先\n"
                "4. **政策支持** — 纳入省级特色产业集群,十四五规划明确百亿级目标与配套资金"
            ),
            "shortcomings": (
                "## 主要短板\n"
                "1. **精深加工占比偏低** — 初加工占产值70%,利润率仅为精深加工的1/5,附加值挖掘不足\n"
                "2. **区域品牌辨识度弱** — 企业品牌强、区域品牌弱,消费者对该县与该产业的关联度认知低\n"
                "3. **数字化水平滞后** — 中小企业信息化覆盖率不足40%,供应链协同效率偏低\n"
                "4. **人才供给不足** — 食品加工、电商运营、品牌营销等中高端岗位招聘困难"
            ),
            "recommendations": (
                "## 建议一:补精深加工短板(1年内见成效)\n"
                "- **问题**:初加工占比过高,价值链中高端环节缺失\n"
                "- **对策**:通过专项技改补贴 + 龙头示范线带动,引导企业向功能食品、生物提取延伸\n"
                "- **路径**:"
                "  短期(6个月):出台精深加工技改补贴(设备投入补贴30%,上限500万);"
                "  中期(1-2年):龙头XX股份开放工艺合作,建设共享中试车间;"
                "  长期(3年):打造精深加工产业集聚区\n"
                "- **责任主体**:县工信局+龙头企业+产业园区管委会\n"
                "- **预期成效**:2027年精深加工占比提升至40%,产业利润率提升3-5个百分点\n\n"
                "## 建议二:区域品牌建设(1年启动,3年见规模)\n"
                "- **问题**:消费者对该县与该产业关联度低,产品溢价难以实现\n"
                "- **对策**:打造地理标志证明商标 + 统一区域公共品牌 + 电商矩阵运营\n"
                "- **路径**:"
                "  短期:完成地理标志申报,统一区域品牌VI;"
                "  中期:入驻头部电商公共品牌专区,对接MCN资源;"
                "  长期:进入国家级特色农产品优势区\n"
                "- **责任主体**:县农业农村局+商务局+市场监管局\n"
                "- **预期成效**:2028年区域品牌知名度进入全国Top10,产品溢价空间提升15%+"
            ),
        }[task]

        return LLMResponse(
            content=content,
            model="mock-llm-v1",
            prompt_tokens=800,
            completion_tokens=1200,
            total_tokens=2000,
        )
