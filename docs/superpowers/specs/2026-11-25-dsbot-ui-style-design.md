# CountyResearchAI × DS-Bot 风格前端优化（短设计）

## 意图

用户要求停止使用 AxiomScope 品牌名，前端统一为 CountyResearchAI；并按 `ds-bot-ui-style` skill 的参考，把现有证据研究台从纸张/深色侧栏风格调整为安静、紧凑的浅色桌面工作台。

## 目标

- 前端可见品牌、页面标题与包名改为 CountyResearchAI；E2E 断言同步更新。
- 采用 DS-Bot 的浅色语义色：主背景 `#fcfcfc`、侧栏 `#f7f7f7`、卡片 `#ffffff`、主文字 `#141414`、低对比分隔线 `rgba(20,20,20,.08)`、蓝色强调以 `#4d6bfe` 为基准。实现时因 `#4d6bfe` 在白底只有 4.33:1、侧栏只有 4.04:1，达不到 WCAG AA，故拆为 `--accent: #3f5be0`（填充）、`--accent-deep: #2f4ad0`（浅底文字/hover）、`--accent-bright: #4d6bfe`（仅装饰）。
- 外壳、侧栏、顶栏、状态栏、输入/按钮、高频卡片先统一；图谱画布与 Cytoscape 节点配色同步改为浅色。
- 保留四步工作流、全部功能、数据结构、URL 状态和现有 E2E 选择器。

## 非目标

- 不复制 DS-Bot 的品牌、头像、图标、聊天气泡或布局。
- 不改 API、后端、环境变量名（`AXIOMSCOPE_*` 保持兼容）。
- 不新增依赖，不引入第二套设计系统。
- 不强制改成聊天应用；保留研究台的三栏工作台结构。

## 约束

- `.step-button`、`.run-status-strip`、`.graph-panel`、`.conflict-card`、`.gap-table`、`.layout-switch` 等 E2E 依赖类名不变。
- 弱文字透明度不能直接照搬 `.36` 到正文；按实际对比度调整，确保 axe WCAG A/AA 通过。
- 保留 `prefers-reduced-motion` 与现有响应式断点。
- 交互态必须有可见的 hover/focus/disabled 区分，不能只靠颜色传达状态。

## 采用方式

**A. 语义变量 + 外壳优先的渐进改造（采用）**：先替换颜色/圆角/边框/间距 token，再覆盖侧栏、顶栏、状态栏、按钮输入与高频卡片；GraphCanvas 同步换浅色主题。风险集中在对比度与图谱可读性，由 axe 与截图验证。

其他方案：B 只改强调色（不足以体现 DS-Bot 的层次与密度）；C 直接移植 DS-Bot 组件（会引入其品牌与聊天布局，违背适配原则）。

## 具体改动

1. 品牌：`web/src/components/StepRail.tsx`、`web/src/App.tsx`、`web/index.html`、`web/package.json`、`web/package-lock.json`、`web/tests/e2e/workspace.spec.ts`。
2. 主题：`web/src/styles.css` 的 `:root` 变量与关键组件样式；新增 DS-Bot 视觉覆盖段，放在媒体查询之前。
3. 图谱：`web/src/components/GraphCanvas.tsx` 的 Cytoscape 颜色表，及 `.graph-canvas` 背景。
4. 验证：typecheck、20 个 Vitest、build、Playwright 4/4（含 axe），并查看桌面截图。
