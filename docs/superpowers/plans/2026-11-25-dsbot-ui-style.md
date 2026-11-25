# CountyResearchAI × DS-Bot UI Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把前端品牌改为 CountyResearchAI，并按 DS-Bot 参考完成浅色、紧凑、蓝色强调的工作台视觉优化。

**Architecture:** 先用 CSS 语义变量替换全局色彩与圆角/边框，再覆盖外壳、侧栏、顶栏、状态栏和高频组件；GraphCanvas 的 Cytoscape 颜色表同步改为浅色主题。功能与数据流不变。

**Tech Stack:** React 18 + TypeScript + Vite 5 + Cytoscape；Vitest + Playwright + axe。

**Spec:** `docs/superpowers/specs/2026-11-25-dsbot-ui-style-design.md`

## Global Constraints

- 保留 `.step-button`、`.run-status-strip`、`.graph-panel`、`.conflict-card`、`.gap-table`、`.layout-switch`。
- axe WCAG A/AA 必须通过；弱文字不能直接使用 `.36` 透明度。
- 图谱节点/边颜色与画布背景必须一起改。
- 保留响应式断点与 `prefers-reduced-motion`。
- 不改 API、后端、`AXIOMSCOPE_*` 环境变量、四步工作流。
- 不新增依赖，不复制 DS-Bot 品牌资源。
- 不提交；本仓库提交由独立会话处理。

## Review Focus

- 浅色画布上的节点标签对比度 → Task 3 图谱截图与 axe。
- 浅色侧栏中禁用步骤/次级文字对比度 → Task 2 axe。
- E2E 依赖类名或标题文案变化导致误报 → Task 1/4 完整 E2E。
- 图谱状态色（SUPPORTED/冲突/缺口）在浅色主题中失去区分 → Task 3 截图检查。
- 响应式与 reduced-motion 被覆盖丢失 → Task 2 的 CSS diff 检查。

---

### Task 1: 品牌更名为 CountyResearchAI

**Files:**
- Modify: `web/index.html:6`、`web/package.json:2`、`web/package-lock.json:2,8`
- Modify: `web/src/App.tsx:455`、`web/src/components/StepRail.tsx:68`
- Test: `web/tests/e2e/workspace.spec.ts:171`

**Interfaces:**
- Consumes: 现有品牌文案与页面标题。
- Produces: 页面 `<h1>` 为 `CountyResearchAI`；包名 `countyresearchai-web`；顶栏面包屑文案 `CountyResearchAI`。

- [x] **Step 1: 先改 E2E 断言**

把标题断言改为 `heading { name: "CountyResearchAI" }`。

- [x] **Step 2: 运行并确认失败**

Run: `PY="$(python -c 'import sys; print(sys.executable)')"; AXIOMSCOPE_E2E_PYTHON="$PY" npm --prefix web run test:e2e -- --grep wizard`
Expected: FAIL，页面仍显示 AxiomScope。

- [x] **Step 3: 替换 UI 与包名文案**

仅替换前端可见品牌与包名；保留 `AXIOMSCOPE_*` 环境变量。

- [x] **Step 4: 运行品牌用例**

Run: 同上
Expected: PASS；后续完整 E2E 在 Task 4 执行。

### Task 2: DS-Bot 浅色 token 与外壳

**Files:**
- Modify: `web/src/styles.css:1-30`（`:root`）、`286-530`（step-rail）、`540-591`（top-bar）、`2063-2141`（status-bar/layout-switch）、`87-149`（button/input）

**Interfaces:**
- Consumes: 原变量名 `--paper`、`--surface`、`--line`、`--orange`、`--rail` 等。
- Produces: 同名变量改为 DS-Bot 浅色语义；新增 `--accent`、`--accent-deep`、`--accent-soft`、`--hover`、`--active`，旧 `--orange*` 作为别名指向蓝色强调。

- [x] **Step 1: 更新 token 与外壳样式**

主背景 `#fcfcfc`、侧栏 `#f7f7f7`、卡片 `#ffffff`、文字 `#141414`、分隔线 `rgba(20,20,20,.08)`；按钮/输入圆角 8px，卡片 12px，胶囊控件 999px；hover 用低对比底色而非黑白反转。

强调色以 DS-Bot 的 `#4d6bfe` 为基准，但它在白底/侧栏上只有 4.04–4.33:1，达不到 AA。最终落地为三档：`--accent: #3f5be0`（填充底，白字 5.55:1）、`--accent-deep: #2f4ad0`（浅底上的强调文字与 hover，白底 6.97:1）、`--accent-bright: #4d6bfe`（仅装饰）。弱文字 `--muted` 从 `.56` 提到 `.70`，`--green` 改 `#007a45`，`--red` 改 `#c81b2d`，以满足 axe。

- [x] **Step 2: 浅色化侧栏与状态栏**

步骤行改为圆角列表项，活动项用蓝色左侧条 + 淡色底；状态栏改浅底深字；保留全部类名。

- [x] **Step 3: 运行检查**

Run: `npm --prefix web run typecheck && npm --prefix web test`
Expected: exit 0，20/20 通过。

- [x] **Step 4: 确认响应式规则仍在**

检查 `web/src/styles.css` 中 1280/1120/820/560/1180 断点与 `prefers-reduced-motion` 仍存在。

### Task 3: 浅色图谱与状态色

**Files:**
- Modify: `web/src/components/GraphCanvas.tsx:13-182`
- Modify: `web/src/styles.css:1269-1275`（`.graph-canvas`）

**Interfaces:**
- Consumes: Task 2 的 `--accent`、`--line`、`--ink` 语义。
- Produces: 同一组节点/边类型；颜色改为浅色主题：节点白/近白、标签深色、强调蓝、成功绿、冲突红、缺口橙。

- [x] **Step 1: 改写 Cytoscape 颜色表**

保留 selector 与尺寸/形状；只改颜色。`data-testid`、`data-node-count`、`data-layout` 不变。

- [x] **Step 2: 改画布背景**

`.graph-canvas` 改为 `#fcfcfc` 点阵背景与 `var(--line)` 边框。

- [x] **Step 3: 运行图谱 E2E**

Run: `PY="$(python -c 'import sys; print(sys.executable)')"; AXIOMSCOPE_E2E_PYTHON="$PY" npm --prefix web run test:e2e -- --grep graph`
Expected: 400 节点用例通过，截图标签可读。

### Task 4: 全量回归与截图检查

**Files:**
- Test: `web/tests/e2e/workspace.spec.ts`

- [x] **Step 1: 运行完整前端检查**

Run: `npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build`
Expected: typecheck 无错误，20/20，build exit 0。

- [x] **Step 2: 运行 E2E**

E2E 由后端静态托管 `web/dist`（`src/county_research_ai/api/app.py:531`），改完样式必须先 `npm --prefix web run build`，否则测的还是旧产物。

Run: `npm --prefix web run build && PY="$(python -c 'import sys; print(sys.executable)')"; AXIOMSCOPE_E2E_PYTHON="$PY" npm --prefix web run test:e2e`
Expected: 4/4，含 axe WCAG A/AA。

- [x] **Step 3: 查看截图并恢复产物**

查看 `01-define.png`、`03-graph.png`、`05-verified-report.png`，确认浅色层次、蓝色强调、标签可读；随后 `git restore -- 'experiments/quality/finish_roadmap_e2e/*.png'`。

### Task 5: 图谱呈现改为 MiroFish 式（点 + 外置标签）

参考 `666ghj/MiroFish` 的 `frontend/src/components/GraphPanel.vue`（Vue 3 + D3 v7 力导向图）：它的干净来自「节点与标签解耦」——节点是 r=10 的按类型上色的圆点，标签放在点右侧 14px、8 字符截断，类型靠颜色 + 图例表达，状态靠描边表达。

**Files:**
- Create: `web/src/graphPalette.ts`（类型色 / 状态色单一来源，画布与筛选胶囊共用）
- Modify: `web/src/components/GraphCanvas.tsx`
- Modify: `web/src/components/GraphPanel.tsx`
- Modify: `web/src/styles.css`

- [x] **Step 1: 节点退化为按类型上色的点**

县 30px 蓝、图问题 22px 紫、证据 17px 青（描边环表示 SUPPORTED / NEEDS_REVIEW / CONTRADICTED / INSUFFICIENT）、来源 13px 灰菱形、指标 13px 橄榄绿虚线点、缺口 17px 琥珀菱形、冲突 24px 红六边形；统一 2–3px 白色描边。

- [x] **Step 2: 标签移到节点外侧**

`text-halign: right` + `text-margin-x: 7`；按类型截断：图问题 168px、证据 132px、其余 120px；悬停时放宽到 300px 并置顶。左右半区分别朝外（`label-left` 类，中线按节点中心而非带标签的包围盒计算），把密集处的文字分散到两侧。

- [x] **Step 3: 布局跟着改**

`cose` 去掉 `nodeDimensionsIncludeLabels`（标签外置后节点包围盒变「宽而扁」，开启会把节点竖直摞成一列——实测 304×1995）；斥力 3200、边距 120、重力 1.1。`normalizeAspect` 改为基于初值坐标的幂等实现（下限 0.6），并在 ResizeObserver 中重算，画布比例变化后能重新贴合。

- [x] **Step 4: 图例与标签开关**

筛选胶囊增加类型色点，关掉的类型色点变淡；工具栏新增「节点标签」开关（`node.hide-label`），大图不显示该开关（大图本就隐藏标签）。

- [x] **Step 5: 验证**

Run: `npm --prefix web run build && npm --prefix web test && AXIOMSCOPE_E2E_PYTHON=python npm --prefix web run test:e2e`
Expected（已核对）：20/20 单测、E2E 4/4（含 axe WCAG A/AA）、400 节点首帧 499ms；760×650 画布下缩放约 1.0，无节点越界。

- [x] **Step 6: 交互手感（滚轮 / 拖动）**

`wheelSensitivity` 0.18 → 1.5：cytoscape 的缩放步长是 `10^((delta/-250)*sens)`，0.18 时每个滚轮刻度只有 0.8%，1.5 时实测 7.2%。`.graph-canvas` 补 `touch-action: none`、`overscroll-behavior: contain`、`user-select: none`（拖动不再被页面滚动/文字选中抢走），并用 `cursor: grab/grabbing` 给出可拖动提示；`boxSelectionEnabled: false` 避免拖动误开框选；悬停展开标签改为停留 120ms 后才触发，扫过画布时不再反复触发文字重排。
