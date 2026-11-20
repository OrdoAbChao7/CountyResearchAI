# Resource Precheck — 2026-10-18

## 结果

- Gemini `models.list` 返回 HTTP 200，`gemini-3.1-flash-lite` 可见。
- Google 官方价格页将该模型的标准 Free Tier 输入和输出标为免费，但 `models.list` 不返回账户级 quota 或 billing 状态；当前 key 是否绑定付费项目无法从本地/API 只读结果确认。
- 只读浏览器核验进入 Google AI Studio 后被重定向到 Google 登录页；当前受控浏览器没有已登录会话，未输入凭据，也未修改账户设置。因此不能从网页控制台补齐账户级 billing 证据。
- Tavily `/usage` 返回 `Researcher` 计划，当前使用量 `230 / 1000` credits，保守剩余 `770` credits，`paygo_usage=0`。资源管理仍按保守上限执行。
- DeepSeek 未配置且保持 `DISABLED_BY_POLICY`。

## 门禁结论

`formal_target_gate_20261018.json` 保持 `NOT_RUN`。本次没有调用 Gemini 业务模型，也没有启动 E1/E2 API 批次。Gemini 账户计费边界未确认前，不把公开价格页当作账户级免费资格证明。

## 证据

- 机器可读结果：`manifests/resource_precheck_20261018.json`
- Gemini 模型可见性：只读 `models.list` 检查，未输出 key 或响应原文。
- Gemini 账户页面：Playwright 只读导航，结果为 `GOOGLE_LOGIN_REQUIRED`，没有账户操作。
- Tavily 账户用量：只读 `GET https://api.tavily.com/usage`，未输出 key。
- 公开计费说明：[Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)、[Gemini billing](https://ai.google.dev/gemini-api/docs/billing/)、[Tavily pricing](https://www.tavily.com/pricing)
