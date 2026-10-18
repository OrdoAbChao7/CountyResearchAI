# Formal Input Offline Preflight — 2026-10-18

本报告只记录正式实验输入和编排配置的离线校验，不是质量结果，也没有调用 Gemini、Tavily 搜索或其他业务 API。

## 校验结果

| 项目 | 结果 |
| --- | --- |
| Formal Ground Truth | `PASS`，6 条 claim、6 个地区 |
| Ground Truth source hash | `7a5af074d7530f174d057d7958bf204663af39c964a034b7fdad31f652da8bc7` |
| E2 fixed-input packs | `PASS`，6 个包全部可加载 |
| E2 pack manifest hashes | `PASS`，6/6 匹配 |
| E1 specs (`repeats=3`) | `PASS`，54 个 spec |
| E1 groups | `A`、`B`、`C` |
| Formal launch manifest | `PASS`，5/5 frozen-file hashes、6/6 pack file hashes、6/6 pack source hashes |
| Formal gate at check time | `NOT_RUN` |
| Business API calls | `0` |

校验使用正式 runner 的 `load_formal_regions`、`build_formal_specs`、`load_formal_fixed_input_pack`，以及 `require_frozen_ground_truth`；没有修改冻结输入或 Ground Truth 文件。

该结果只证明 gate 解锁后的输入完整性和编排规模，不证明任何研究质量或 Provider 免费资格。
