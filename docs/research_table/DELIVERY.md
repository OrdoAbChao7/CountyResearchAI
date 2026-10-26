# 交付与验收记录

## 已完成

新增独立 research_table 包、离线 CLI、非破坏迁移脚本、两轮演示与评分运行器。未修改原研究入口与已有源码；未提交、推送、部署、发布或调用模型/搜索。保留原未提交内容及历史 Phase 7 负面评测。设计与执行计划见 DESIGN_AND_PLAN.md，操作见 README.md。

SQLite v1＋内容寻址原文保存来源和事实版本；追加核查日志保存人、时间、理由和证据版本；别名要求依据、缺失保留 unknown/null。相同资料及转载重放幂等，人工校正不会被重放覆盖。冲突候选必须显式替代旧版本，来源日期不能自动决定正确性。支持核查、纠正、冲突、撤销、原文查看、四级可比、限定单位换算、年度增长率、显式文字位置依赖、旧结果重放和新版本重算。CSV 为完整版本历史，evidence.json 包含审计及当前状态，update.md 区分历史事件和当前待办。

真实示例为安吉竹产业，2个存档来源、2022/2023年、2个有数据指标、4条事实。输入冻结 hash 可检查。仅保留词法规则直接命中原文；没有读取标准答案或生成报告选事实。确认记录明确为脚本演示，不是真实用户签核。口径未知，禁止计算派生增长率。登记10指标字典及缺失网格，2022—2023缺失16/20，近三年2023—2025缺失28/30。

## 验证证据

117 项针对本功能及相关原流程回归通过：16 个新功能案例（含参数化）及原 application/contracts/source/ledger/models/mode/CLI/agent CLI/pipeline 回归。命令见下。Ruff 新增范围检查通过。旧 RawDoc 真实档案迁移及导出已实际执行，原档案不修改。

独立审查发现并修复两个幂等问题：A→转载B→A重放错误绑定来源；CRLF原文读取换行转换造成完整性误报。修复前2个新增测试均失败，修复后纳入117项回归。

冻结合成任务（不是业务效果）：影响识别 TP=2、FP=0、FN=0，precision/recall各1.0；不同口径混算0/1；当前确认事实溯源4/4；重复导入幂等、转载未新增事实、未受影响记录不进入待办、输入值持久化保真均通过。详见 experiments/research_table/offline_final/scores.json 与 observations.json、两轮 CSV/证据及更新报告。这里的保真不等于自动抽取准确率。协议与答案在运行前固定，gold内容仅在执行及观测落盘后用于评分。

```powershell
.venv/Scripts/python -m pytest tests/test_research_table.py tests/test_research_application.py tests/test_research_contract.py tests/test_source_contract.py tests/test_evidence_ledger.py tests/test_models.py tests/test_mode_registry.py tests/test_cli.py tests/test_agent_cli.py tests/test_pipeline.py -o addopts='' -p no:cacheprovider -q
.venv/Scripts/python -m ruff check src/county_research_ai/research_table scripts/build_research_table_example.py scripts/import_research_table_archive.py scripts/evaluate_research_table_offline.py tests/test_research_table.py
```

未运行依赖外部API的真实研究生成验证；本轮没有为此调用模型或搜索。没有声明全仓测试全部通过；验收范围为新增闭环及相关原流程。

## 未验证与剩余问题

产品收益 NOT_VALIDATED：没有真实研究人员对比，不能声称人工时间下降40%，不能声称真实正确性高于或不低于通用AI基线。已提供可执行 USER_STUDY.md 和空CSV记录模板，分别记录首次成本、更新成本、人工计时、模型等待、质量与缺失。

真实资料覆盖不足，已按授权缩小范围；历史修订、园区差异、改值冲突、重复转载的系统边界由明确 synthetic 的冻结任务和测试覆盖，不伪造真实业务案例。归档内容未联网复核；没有独立的通用自动语义抽取评测。真实修订样本和更多县/年份的扩展仍需补资料。

正文任意变化保守使旧确认待复核，段落级“实质变化”过滤尚无；对改写转载仅可标可能相关，缺少语义识别。依赖追踪覆盖显式登记的计算/文字位置，不能自动扫描全部既有报告。SQLite CLI 以单用户顺序操作为目标，没有多人并发协同。金额币种须由指标/口径定义明确，未实现跨币种换算。

因此工程闭环及离线验收材料完成，产品效果验收仍未通过；研究范围受现有资料限制。
