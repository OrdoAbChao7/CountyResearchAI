"""研究成果综合合成智能体 (ResearchSynthesizer)。

职责：
1. 整合 Economic、Policy、Industry 专业 Agent 的深度分析；
2. 调度 FactVerifier 对全篇数据进行事实核验与不确定性标注；
3. 显式呈现：
   - 执行摘要（结论先行、核心数字）
   - 经济规模与统计公报
   - 政策规划与制度供给
   - 产业链企业与竞争短板
   - 多来源交叉核验与数据冲突说明
   - 资料缺口与不确定性提示
   - 结构化参考文献与证据溯源表
4. 保证向后兼容生成 list[AnalysisResult] 与完整可审计 Markdown 报告。
"""
from __future__ import annotations

from ...domain.research_contracts import EvidencePack
from ...evidence.bound_verifier import EvidenceBoundVerifier
from ...evidence.store import EvidenceStore
from ...evidence.verifier import FactVerifier
from ...models import AnalysisResult, CountyInfo, EvidenceGap
from .economic import EconomicAnalysisOutput
from .industry import IndustryAnalysisOutput
from .policy import PolicyAnalysisOutput


class ResearchSynthesizer:
    """多智能体深度研究报告合成器。"""

    def synthesize(
        self,
        county: CountyInfo,
        focus: str,
        economic_out: EconomicAnalysisOutput,
        policy_out: PolicyAnalysisOutput,
        industry_out: IndustryAnalysisOutput,
        evidence_store: EvidenceStore,
        gaps: list[EvidenceGap] | None = None,
        evidence_packs: list[EvidencePack] | None = None,
    ) -> list[AnalysisResult]:
        """将多 Agent 分析结果合成标准 AnalysisResult 列表并注入事实核验标记。"""
        c_name = county.display()
        f_name = focus or "特色产业"

        def verify(markdown: str):
            if evidence_packs:
                return EvidenceBoundVerifier().verify_markdown(
                    markdown, evidence_packs, county=county.name
                )
            return FactVerifier(evidence_store).verify_text_content(markdown, county=c_name)

        # 1. 现状分析章节（合成经济与实物规模）
        status_raw = economic_out.markdown_content
        status_annotated, rep1 = verify(status_raw)

        # 2. 优势与政策章节
        policy_raw = policy_out.markdown_content
        policy_annotated, rep2 = verify(policy_raw)

        # 3. 产业链、企业与短板章节
        industry_raw = industry_out.markdown_content
        industry_annotated, rep3 = verify(industry_raw)

        # 4. 发展建议与治理对策
        rec_lines = [
            f"### 四、{c_name}{f_name}高质量发展建议与破局路径",
            "",
            "以下内容为研究建议，不作为已发生事实：",
            "",
        ]
        if industry_out.bottlenecks_and_risks:
            rec_lines.extend(
                f"- 针对已记录的风险，建议先核实其影响范围与可行应对措施：{risk}"
                for risk in industry_out.bottlenecks_and_risks[:5]
            )
        else:
            rec_lines.append(
                "- 当前材料未支持县域特定的产业建议；应先补齐可追溯的风险、市场与政策原文。"
            )
        rec_lines.append("")
        rec_content = "\n".join(rec_lines)

        # 5. 生成专业审计附录：数据冲突说明 + 资料缺口说明 + 参考文献表
        appendix_lines = [
            "---",
            "### 附录：研究证据链与可信度审计记录",
            "",
            evidence_store.render_conflicts_section(),
            "",
            "#### 资料缺口与不确定性提示",
        ]
        if gaps:
            for g in gaps:
                appendix_lines.append(f"- ⚠ {g.description}")
        else:
            appendix_lines.append("- 未生成结构化缺口记录；这不代表现有证据已充分。")

        appendix_lines.extend([
            "",
            "#### 核心参考文献与证据溯源表",
            evidence_store.render_citations_table(),
            "",
        ])
        appendix_content = "\n".join(appendix_lines)

        # 组合各 AnalysisResult，与既有 LLMAnalyzer.TASK_CONFIGS 完全对齐
        results = [
            AnalysisResult(
                task="industry_status",
                content=status_annotated,
                model="deep-multi-agent-v2",
                tokens_used=0,
            ),
            AnalysisResult(
                task="advantages",
                content=policy_annotated,
                model="deep-multi-agent-v2",
                tokens_used=0,
            ),
            AnalysisResult(
                task="shortcomings",
                content=industry_annotated,
                model="deep-multi-agent-v2",
                tokens_used=0,
            ),
            AnalysisResult(
                task="recommendations",
                content=f"{rec_content}\n\n{appendix_content}",
                model="deep-multi-agent-v2",
                tokens_used=0,
            ),
        ]
        return results

    def generate_executive_summary(
        self,
        county: CountyInfo,
        focus: str,
        analyses: list[AnalysisResult],
    ) -> str:
        """生成面向决策者的执行摘要。"""
        c_name = county.display()
        f_name = focus or "特色产业"
        supported = [
            line.strip()
            for analysis in analyses
            for line in analysis.content.splitlines()
            if "[证据：" in line or "^[来源:" in line
        ]
        if not supported:
            return (
                f"**{c_name}{f_name}研究摘要：**当前没有可复述的、已关联来源的核验事实。"
                "现有结论应视为待核实，需补齐具体原文证据后再作县域判断。"
            )
        return (
            f"**{c_name}{f_name}研究摘要：**\n"
            + "\n".join(f"- {line}" for line in supported[:3])
            + "\n\n摘要仅摘录已关联来源的事实；建议与推断不代表已发生事实。"
        )
