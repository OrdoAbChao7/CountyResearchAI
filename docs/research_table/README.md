# 可核查底表与增量更新

独立离线入口不初始化模型、搜索或多 Agent。保留原 `county-research` 命令。需要现有 `.venv`；数据库 schema v1 首次打开自动建立，未知版本拒绝打开。不要把旧缓存或旧报告视为已核查事实。

## 复现两轮示例

在项目根目录 PowerShell 执行（输出目录必须不存在，避免覆盖旧实验）：

```powershell
.venv/Scripts/python -m scripts.build_research_table_example --output experiments/research_table/my_example
.venv/Scripts/python -m scripts.evaluate_research_table_offline --output experiments/research_table/my_offline
.venv/Scripts/python -m pytest tests/test_research_table.py tests/test_research_application.py tests/test_research_contract.py tests/test_source_contract.py tests/test_evidence_ledger.py tests/test_models.py tests/test_mode_registry.py -o addopts='' -p no:cacheprovider -q
```

真实资料在 real_inputs，第一轮导入 2022 年、第二轮导入 2023 年。每轮目录包含 facts.csv（全部不可覆盖事实版本）、evidence.json（来源、核查、转载依据、依赖和待办）、update.md（历史事件与当前待办分开）。两轮例子的确认仅为脚本演示，核查人和理由已明示，不代表专家判断。原文使用现有存档，不做联网真实性再认证。

已交付结果在 experiments/research_table/example_final 与 offline_final。coverage.csv 保留缺失单元格；coverage.json 给分母。10 项指标中仅2项有明示原文，安吉 2022—2023 网格缺失16/20；2023—2025 近三年网格缺失28/30。其他县资料不具备足够同产业同期间覆盖，首版范围据此缩小。指标字典中 definition_only_missing_data 表示只有定义，没有自动抽取能力。

## 建库、核查和更新

```powershell
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db import work/round1.json
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db list
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db show FACT_ID
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db review FACT_ID confirm --actor researcher --reason '已对照原文和口径定义'
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db correct FACT_ID --changes '{"value":"101"}' --actor researcher --reason '修正抄录错误'
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db review NEW_FACT_ID confirm --supersedes OLD_FACT_ID --actor researcher --reason '已核对修订依据'
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db review FACT_ID conflict --actor researcher --reason '来源数值冲突'
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db review FACT_ID revoke --actor researcher --reason '撤销确认，重新查证'
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db calculate BASE_FACT_ID CURRENT_FACT_ID --location 'report.md#growth'
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db link-text FACT_ID --location 'report.md#conclusion'
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db import work/round2.json
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db export work/round2-output
.venv/Scripts/python -m county_research_ai.research_table --db work/research.db reproduce CALCULATION_ID
```

`show` 返回完整归档正文、摘录 offset、证据版本与审计日志，可直接检查原文。确认冲突必须列出所有需要替代的版本，旧版本保留。人工校正产生新候选，须再次确认。撤销与冲突会影响依赖输出。新确认后用新输入版本运行 calculate 生成新结果；不会自动改写报告。reproduce 使用旧输入重放历史结果，即使旧确认后来撤销。

## 输入合同与旧档迁移

导入一个对象或对象数组，每个对象包括 project、source、facts。source 接受 canonical_url/url、content、source_title/title、publish_date/published_at。事实最小例子：

```json
{"project":"pilot","source":{"canonical_url":"local:doc1","content":"2023年产值100亿元"},"facts":[{"region_id":"330523","metric_id":"bamboo_output","original_name":"竹产业总产值","mapping_basis":"人工确认：研究员R，指标定义v1","value":"100","unit":"亿元","period":"2023","scope":"county","caliber":"unknown","price_basis":"unknown","excerpt":"2023年产值100亿元","start":0}]}
```

start/end 为 Python Unicode 字符 offset，必须精确匹配完整存档；PDF 可先转文本，首版不保存页坐标。value=null 是缺失，绝不转为0；其他未知字段显式 unknown。period 是数据年度，与发布日期分开。别名必须给 mapping_basis（规则出处或人工确认说明），系统不自动猜测别名。输入事实默认 manual_candidate；有限规则抽取输出 rule_candidate。

已有 RawDoc 列表的只读迁移命令：

```powershell
.venv/Scripts/python -m scripts.import_research_table_archive data/raw/安吉县/20261005/raw_docs.json --db work/migrated.db --project pilot --region-id 330523
```

迁移复用 serialize_source_documents，只提取有明示年份的竹产业产值和邻接同比，其余归档为来源；不会把 document_timestamp 抓取时间充作发布日期。原存档不改，确认不会从旧 Ledger 继承。迁移不会自动识别模拟资料，研究人员需筛选真实来源；业务例子已排除 example.com/XX模拟数据。

## 能力限制

人工录入合同与有限词法规则已经可用，不是通用产业自动抽取器。SQLite 适合单机顺序 CLI；首版没有多用户并发协调、权限管理或联网采集。单位换算限显式规则，不自动补足币种。可比性四类见 compare；口径未知不可计算，即使已确认摘录。金额指标必须定义清楚币种，首版例子不提供跨币种计算。

相同正文转载按 hash 留依据；同摘录同值只标可能相关，不增加独立证据权重。改写转载的语义识别尚未实现。来源正文任意变化会保守使该文档旧确认待复核，尚未做到段落级实质变化过滤，可能产生额外复核。计算和文字依赖必须显式登记，未登记的旧报告文字无法自动发现。所有导出包含历史版本，应按 verification_status 筛选；没有自动选取“最新正确值”。对空项目只导出证据和更新报告，不产生无列定义的空 CSV。

工程行为的离线合成评分不代表产品收益；真实人工对比流程与空记录模板见 USER_STUDY.md。历史 Phase 7 负面评价原样保留。
