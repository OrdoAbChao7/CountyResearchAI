# Phase 6 — 效率与架构版本

状态：`ENGINEERING_PARTIAL / TOKEN_EFFECT_PENDING`

## 已完成

- `RunManifest` 记录 `architecture_version` 并纳入配置哈希；新实验缺少版本声明时标记 `INVALID_CONFIG`。旧 manifest 不回写。
- 核心架构版本为 `workflow_legacy`、`deep_legacy`、`evidence_first_v2`；A/B/C 对照组额外标记为 `traditional_search_baseline`、`general_ai_baseline`、`evidence_first_v2`，未知值被拒绝。各实验 spec builder 已显式填写实际执行路径。当前 ResearchApplication 与 QueryEngine 明确声明 `evidence_first_v2`，ResearchSpec 兼容归一化旧拼写 `evidence-first-v2`。
- long-history 在一次 Ledger 构建后生成来源可追溯的句级子片段（保留父 chunk ID 与原文 offset），用年份提示和任务词选择六个时期 EvidencePack；已选 Packs 传入报告审核附录并显示时期、来源、chunk IDs 和缺口。新选择器在有明确任务命中时排除零分噪声，每个来源最多补入两个纯时期上下文片段；无任务命中时保持有限回退。
- 阶段划分任务仍使用一次最多 18,000 字符的完整上下文；地理、传统、近代、计划经济、改革开放、新世纪分别使用最多 6,000 字符的主题/时期包。五个分析任务先定义宽时期，再用模型抽取且可解析的 HistoricalPeriod 与宽时期求交后路由证据；无解析结果或无交集时退回原任务时期。明确写在任务中的年份另外提高对应片段排序。任务分析提示仍保持通用时期描述，因此动态阶段当前影响证据路由，不改写分析任务定义。
- 初版整文档截断在失败测试中被证伪：相关句在长文档尾部时曾被漏掉。当前句级选择对这个回归案例有测试，并在预算允许时保留多来源。
- 纯离线回放以实际 PromptLoader 渲染前七个 LLM 调用（阶段划分 + 六个专门任务）。3 份历史 long-history C 组 raw_docs（2、2、1 篇文档）的 prompt 字符数旧/新分别为 112,472/24,542（减少 78.2%）、64,137/19,241（减少 70.0%）、8,494/8,432（减少 0.7%）。总计 185,103→52,215 字符，加权减少 71.8%。其中任务显式年份锚点使于都 contemporary context 从 676 增至 717 字符、德清从 2,212 增至 3,210 字符。实际模板字符数不等同 tokenizer tokens；pattern/summary 两个依赖前序模型输出的调用未计入。
- 以六组配置词项作有限 lexical sanity check：旧上下文中出现的 31 个词项，优化上下文保留 30 个（96.8%）。于都 contemporary task 的 `2020` 现已恢复；`2000` 仍在时期范围 `2001-至今` 外，因此不保留。词项保留不是 Ground Truth evidence recall，也不能证明事实完整性。
- 归档来源数分别只有 2、2、1，样本极小；字符数变化不能外推 token、成本、延迟或事实质量。负面遗漏已显式记录，未调整历史实验分数。
- 通用输入长度上限仍为 `7 × 18,000 = 126,000` 对 `18,000 + 6 × 6,000 = 54,000` 字符，但历史实际回放已展示小输入场景会因重复来源标记而出现字符增长。
- 历史 matched-budget long-history 样本记录 52,561 LLM tokens、120 秒容量、实际 136.231 秒并标记 `BUDGET_EXHAUSTED`。存档没有逐次 prompt token 明细，不能用于声称新旧 token 改善。
- 清除 ResearchSynthesizer 中硬编码的 token 使用量，确定性合成记为 0，而不是伪造 LLM usage。

## 验证

- 新增缺失/未知架构版本拒绝、A/B/C 架构映射、实际架构标识及兼容归一化测试；时间范围选择、动态时期交集路由、无交集回退、句级父片段溯源、多来源、过滤无关 chunk、报告多包审计测试；离线脚本 `scripts/evaluate_long_history_efficiency_offline.py`。
- 长周期分析器可选启用 task checkpoint；每个子任务完成后原子持久化，重启时恢复已有结果，仅执行未完成任务。checkpoint 身份绑定输入哈希、县名、Provider/model 参数及模板/回退 prompt 哈希；身份漂移拒绝续跑。初始分析日期保存在 checkpoint 状态中，跨日续跑沿用原日期。`LongHistoryModeHandler` 可通过请求选项 `analysis_checkpoint_path` 将路径传给分析器；默认仍不写 checkpoint。
- 固定输入批次当前拒绝恢复仍处于 `RUNNING` 的实验 run。直接解除限制会带来未结算资源租约、LLM 响应产物覆盖风险；本轮未放宽这一保护，因此正式批次硬中断续跑尚未接通。
- 全量 `pytest --no-cov -q`：569 passed；有一条 Windows `.pytest_cache` 权限警告。
- 改动范围 Ruff（含架构契约、实验运行器、研究应用、QueryEngine 和相关测试）通过。
- 扩大检查到全仓 `ruff check src tests scripts` 仍报告 75 条既有/跨阶段问题；Phase 6 改动相关文件集合单独 Ruff 全部通过。未对无关历史脚本做批量格式改写。
- 离线效率脚本显式加载仓库 PromptLoader 渲染各任务提示，无任何 LLM/Provider 请求；脚本 Ruff 通过。
- 未调用 Provider 或 Judge。

## 限制与后续

当前检索仍是轻量词项/年份筛选，不是语义检索；动态时期测试依赖结构化阶段边界，未通过 provider replay 评估模型抽取阶段噪声对选择结果的影响。3 个存档不能证明事实质量；未跑含长汀样本的 tokenization，字符差异也可能与 token 差异不同。需扩展冻结集、做独立证据覆盖评分；只有真实 Provider Usage 或受控实验才能验证 token/延迟。Phase 6 仍不满足效率/质量验收，不标记完成。
