import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const outputDir = path.resolve(
  here,
  "../../../experiments/quality/finish_roadmap_e2e",
);

test("wizard: define, run, inspect graph evidence, and read verified report", async ({
  page,
}) => {
  const objective = `E2E 安吉县竹产业深度研究 ${Date.now()}`;

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "AxiomScope" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "定义一个可验证的研究问题" }),
  ).toBeVisible();
  await expect(page.getByLabel("研究目标")).toHaveValue(
    "评估安吉县 2024 年竹产业发展现状与财政贡献",
  );
  await expect(page.getByLabel(/启用深度研究/)).toBeChecked();
  await page.screenshot({
    path: path.join(outputDir, "01-define.png"),
    fullPage: false,
  });

  await page.getByLabel("研究目标").fill(objective);
  await page.getByLabel("地区（逗号分隔）").fill("安吉县");
  await page.getByLabel("研究方向（可选）").fill("竹产业");
  await page.getByRole("button", { name: "开始研究" }).click();

  await expect(page).toHaveURL(/step=2/);
  await expect(page).toHaveURL(/task=/);
  await expect(page.getByRole("heading", { name: objective })).toBeVisible();
  await expect(page.locator(".run-status-strip")).toContainText("已完成", {
    timeout: 60_000,
  });

  await expect(
    page.getByRole("heading", { name: "Agent 时间线" }),
  ).toBeVisible();
  await expect(page.locator(".event-type", { hasText: "question_tree.created" })).toBeVisible();
  await expect(page.locator(".event-type", { hasText: "synthesis.completed" })).toBeVisible();
  await expect(page.locator(".event-type", { hasText: "report.rendered" })).toBeVisible();
  await expect(
    page.locator(".agent-timeline .agent-run").filter({ hasText: "Agent" }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(outputDir, "02-run.png"),
    fullPage: false,
  });

  await page.getByRole("button", { name: "查看证据图谱" }).click();
  await expect(page).toHaveURL(/step=3/);
  await expect(page.locator(".graph-panel")).toBeVisible();
  await expect(
    page.locator('[data-testid="graph-canvas"] canvas').first(),
  ).toBeVisible({ timeout: 30_000 });
  await page.screenshot({
    path: path.join(outputDir, "03-graph.png"),
    fullPage: false,
  });

  await page.getByRole("tab", { name: "列表" }).click();
  const evidenceRow = page
    .locator(".graph-list-view tbody tr")
    .filter({ has: page.locator(".type-evidence") })
    .first();
  await expect(evidenceRow).toBeVisible();
  await evidenceRow.getByRole("button", { name: "打开证据" }).click();

  const drawer = page.getByRole("dialog", { name: "证据抽屉" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("heading", { name: "证据链" })).toBeVisible();
  await drawer.getByRole("button", { name: "查看来源" }).first().click();
  await expect(drawer.locator(".source-content mark")).toBeVisible();
  await page.screenshot({
    path: path.join(outputDir, "04-evidence.png"),
    fullPage: false,
  });

  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(evidenceRow.getByRole("button", { name: "打开证据" })).toBeFocused();

  await page.locator(".step-button").filter({ hasText: "报告工作台" }).click();
  await expect(page).toHaveURL(/step=4/);
  await expect(page.locator(".report-section")).toHaveCount(6);
  await expect(page.locator(".verification-strip")).toContainText("已支持");
  await expect(page.locator(".report-nav")).toContainText("已核实事实");
  await page.screenshot({
    path: path.join(outputDir, "05-verified-report.png"),
    fullPage: false,
  });

  await page.locator(".section-citations button").first().click();
  await expect(drawer).toBeVisible();
  await page.screenshot({
    path: path.join(outputDir, "06-report-citation.png"),
    fullPage: false,
  });
  await drawer.getByRole("button", { name: "关闭证据抽屉" }).click();
  await expect(drawer).toHaveCount(0);

  await page.getByRole("tab", { name: /旧版叙述/ }).click();
  await expect(page.locator(".narrative-note")).toContainText("原生章节");
  await expect(page.locator(".narrative-section").first()).toBeVisible();
  await page.screenshot({
    path: path.join(outputDir, "07-narrative.png"),
    fullPage: false,
  });

  await page.locator(".layout-switch button").filter({ hasText: "图谱" }).click();
  await expect(page).toHaveURL(/layout=graph/);
  await page.reload();
  await expect(
    page.locator(".layout-switch button").filter({ hasText: "图谱" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".report-section")).toHaveCount(6);
});

test("wizard: running report is unavailable and cancel/resume is honest", async ({
  page,
  request,
}) => {
  const objective = `E2E 取消恢复 ${Date.now()}`;
  const created = await request.post("/api/v1/research/tasks", {
    data: {
      contract: {
        objective,
        regions: ["安吉县"],
        research_focus: "竹产业",
      },
    },
  });
  expect(created.ok()).toBeTruthy();
  const jobId = (await created.json()).job_id as string;

  await page.goto(`/?step=4&task=${jobId}&layout=workbench`);
  await expect(
    page.locator(".step-button.active"),
  ).toContainText("运行研究");
  await expect(page.locator(".report-section")).toHaveCount(0);
  await expect(page.locator(".run-status-strip")).toContainText("运行中");

  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.locator(".run-status-strip")).toContainText("已取消", {
    timeout: 30_000,
  });

  await page.getByRole("button", { name: "恢复运行", exact: true }).click();
  await expect(page.locator(".run-status-strip")).toContainText("运行中", {
    timeout: 15_000,
  });
  await expect(page.locator(".run-status-strip")).toContainText("已完成", {
    timeout: 60_000,
  });
  await page.screenshot({
    path: path.join(outputDir, "08-cancel-resume.png"),
    fullPage: false,
  });
});
