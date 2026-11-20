# 可核查底表设计与实施计划（2026-10-22）

服务研究人员，减少重复查证与更新返工。工程闭环与人工收益分开验收。无需网络、付费模型或完整报告生成。

## 现状核对
- domain/research_contracts.py 已有 SourceDocument、AtomicClaim、口径/期间字段，但未知值多为空串，无持久化核查历史。
- evidence/ledger.py 已有内存证据关系、重复内容关系和单位数值归一化；不具备跨运行版本、人工审计、增量待办。
- evidence/source_contract.py 已有 URL＋正文哈希标识和摘录 offset；复用其标识算法与 SourceDocument 合同。发布时间仅使用 publish_date/published_at，不以抓取时间补年份。
- storage/local_fs.py 原始资料按县/日期保存，processed 为可覆盖缓存；不能作为不可覆盖版本库。
- application/research.py 已附加内存 Ledger，现有报告模板和 evaluation 是整篇报告流程。新增独立模块及 CLI，避免改写用户已有未提交工作。
- PHASE7_EXPERIMENTAL_EVALUATION.md 结论为效果验收未满足，保留原文件及全部实验。

## 决策与边界
采用标准库 SQLite＋内容寻址原文归档。比复用可覆盖 JSON 更适合事务与依赖查询；不引入服务。SourceDocument 为适配边界，旧 Ledger 不变。事实版本不可修改；状态由追加审计事件推导。导入包允许携带人工整理的候选字段，必须精确绑定正文 offset；限定规则抽取只匹配明示年份/指标/数值，不读取答案。不承诺通用自动语义抽取。

事实：project、region_id（稳定行政代码）、metric_id、original_name、value（十进制字符串或 null）、unit、period、scope、caliber、price_basis、source_id、excerpt、start/end、extraction_status、created_at、parent。未知字符串为 unknown，缺失数值为 null；保留约数 qualifier。来源：URL＋正文 hash 标识、发布时间、归档路径、元数据。核查日志：actor/time/reason/action/source_id/fact_id。计算：公式、输入版本、结果、输出位置；输出文字位置显式登记，任何输入变化或撤销均标记待核查。

相同正文不同 URL 记录 exact_content_hash 转载依据，不生成第二组事实；同 URL 新正文保留版本。不同正文但摘录高度相同仅记录可能重复，不能认作独立证据。相同指标/地区/期间但不同口径单列；未知口径为信息不足；不同值为修订候选＋未解决冲突，不因日期自动采用。确认冲突候选须显式指定 supersedes，并留理由；旧确认仍在历史，当前使用被替代版本。自动导入不能覆盖人工校正。新来源版本使旧证据确认待复核，即使值相同，也不静默确认新证据。

单位规则仅金额元/万元/亿元、面积亩/万亩、数量个/万个，其他同单位可比。增长率必须连续年度、全部口径已知一致、值非缺失、基期非零、输入当前已确认且无未解决冲突；计算只按显式输入生成，不自动替换。重算为新结果版本。别名只接受包内规则来源或人工确认，不模糊映射。

## 资料范围
只使用仓库真实 RawDocs，不访问 ground_truth 或历史生成报告选择事实。现有安吉竹产业原文提供 2022、2023 产值与增长率；2024/2025 缺少可核查完整数据。缩小为安吉县（330523）、竹产业、2022—2023、2 个实测指标；登记约 10 指标定义与缺失矩阵，不伪造 3–5 县/近三年覆盖。排除 example.com 和 XX 企业模拟资料。真实第二轮展示新增年份及重复信息；历史修订、园区差异、重复转载等边界由明确标识 synthetic 的冻结测试验证，不制造真实历史修订。

## 实施顺序与验收
1. 冻结设计、范围与测试协议；创建行为测试，验证初始失败。
2. 实现版本库与可比性、审计、依赖、导出；迁移命令是新库 schema v1 初始化及旧 RawDoc/SourceDocument 导入，绝不改动旧存档。未来未知 schema 拒绝打开。
3. 独立 python -m county_research_ai.research_table CLI：import/list/show/review/correct/calculate/export；可在离线环境运行。
4. 真实两轮示例和 synthetic 两轮评测分开；导入与评分分离，固定输入 hashes、预期事件/影响集合、评分分母；不读取答案指导抽取。
5. 执行必要风险测试及原流程相关回归，输出 CSV、证据清单、增量 Markdown、离线结果和用户实验模板。

不做：网页 UI、联网检索、付费模型、部署发布、自动改写并确认文字、任意公式执行、自动判断新发布时间更正确、声称人工时间减少。
