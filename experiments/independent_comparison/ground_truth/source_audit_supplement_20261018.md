# Ground Truth Source Audit Supplement — 2026-10-18

本文件是主 Agent 对公开来源的补充检索记录，不是 D1–D4 的独立核查报告，也不增加正式 Ground Truth 的 verification_context 数量。它只记录来源发现、可访问性和版本处理，避免把检索到的页面误写成已冻结事实。

## 方法与限制

- `agent-reach doctor --json` 在当前环境不可用；按技能降级规则使用公开网页搜索/阅读。
- 未调用 CountyResearchAI API，未调用 Gemini、Tavily 或 DeepSeek。
- 未把搜索摘要作为唯一事实依据；正式 claim 仍要求两个来源和两个独立核查上下文。

## 新增或确认的来源

### 德清县

湖州市统计局 PDF：
`https://tjj.huzhou.gov.cn/module/download/downfile.jsp?classid=-1&filename=2503311442095589175.pdf`

公开检索结果显示该文件包含德清县 2024 年 GDP 722.5 亿元、增速 5.8% 的区县对比数据。它属于地级市统计部门来源，不是德清县统计局原始年度公报，因此只能支持“初始发布值”版本，不能消除后续 723.1/5.2 版本冲突。

### 长汀县

长汀县人民政府年鉴入口：
`https://www.changting.gov.cn/xxgk/tjxx/tjnj/202602/t20260202_2274562.htm`

页面明确提供官方《长汀统计年鉴2025》PDF 附件：
`https://www.changting.gov.cn/xxgk/tjxx/tjnj/202602/P020260205534015753419.pdf`

入口真实性已确认，但本轮 PDF 正文抓取超时，未取得页码、表号和上下文摘录。因此长汀 357.8/4.9 仍保持候选状态，不能因入口存在而形式化冻结。

### 攀枝花市

攀枝花市人民政府官方页面：
`https://www.panzhihua.gov.cn/ninfo_2584.html`

该页面公开列出 2024 年全市 GDP 1395.24 亿元、增长 6.3%，可作为初始发布值的官方叙述性上下文。它不是统计公报，不能单独替代原始统计表。

后续版本来源：
`https://www.sohu.com/a/979362062_121106884`

该公开转载稿称“经最终核实”后 2024 年 GDP 为 1375.14 亿元、增长 6.2%。当前仍缺少可直接核验的攀枝花市统计局原始发布页，故继续按版本争议保存，不选择单一值进入正式 Ground Truth。

## 审计结论

本补充记录改变了来源审计的细节，但没有解除正式 gate：德清县和攀枝花市仍存在版本冲突，长汀县仍缺少完成页码级独立上下文；六地区 Ground Truth 继续保持 `UNFROZEN`。相关状态已同步到 `datasets/source_audit.yaml` 和 `ground_truth/verification_matrix_20261018.yaml` 的既有结论中。
