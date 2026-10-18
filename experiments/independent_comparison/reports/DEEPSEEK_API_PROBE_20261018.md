# DeepSeek API Probe — 2026-10-18

本文件记录正式批次前的独立连通性探针，不进入 A/B/C 质量指标。

- `GET https://api.deepseek.com/v1/models`: HTTP 200；返回 `deepseek-flash`、`deepseek-v4-pro`。
- `POST https://api.deepseek.com/v1/tools/search`: 成功；`query` 为最小县域产业检索，返回 3 个结果；provider stats 为 `requests=1, successful_requests=1, failed_requests=0`。
- OpenAI-compatible Chat Completion：模型 `deepseek-flash`，响应为 `DS_OK`；`prompt_tokens=36`、`completion_tokens=14`、`total_tokens=50`。
- API Key 未写入本文件、日志或命令输出。
- 本探针证明当前 Key 可用，不证明 DeepSeek Search/Fetch 免费；本批次依据用户明确指令记录为 `USER_AUTHORIZED_PAID`。

正式批次仍须通过持久化 gate、统一 ResourceManager、运行 Manifest、Usage 记录和后处理审计；失败样本不得删除或排除。
