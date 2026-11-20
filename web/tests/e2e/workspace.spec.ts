import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const evidenceDir = path.resolve(
  here,
  "../../../experiments/quality/20261026_q5_e2e",
);

test("create task, stream events, inspect evidence quote, export brief", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "AxiomScope" })).toBeVisible();

  await page.getByLabel("研究目标").fill("E2E 德清县 2024 产业评估");
  await page.getByLabel("地区（逗号分隔）").fill("德清县");
  await page.getByLabel("研究方向（可选）").fill("竹产业");
  await page.getByRole("button", { name: "开始研究" }).click();

  const detail = page.locator(".detail");
  await expect(detail.locator(".badge", { hasText: "已完成" }).first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(detail.locator(".badge", { hasText: "证据充分" })).toBeVisible();

  await page.locator(".tabs button", { hasText: "时间线" }).click();
  await expect(page.getByText("job.completed")).toBeVisible();
  await expect(page.getByText("evidence.persisted")).toBeVisible();

  await page.locator(".tabs button", { hasText: "证据" }).click();
  await expect(
    page.locator(".finding-group .badge", { hasText: "已支持" }).first(),
  ).toBeVisible();
  await expect(page.locator(".finding-card").first()).toBeVisible();
  await page.locator(".finding-head").first().click();
  await page.getByRole("button", { name: "查看来源" }).first().click();
  await expect(page.locator(".source-viewer")).toBeVisible();
  await expect(page.locator(".source-content mark")).toBeVisible();

  await page.screenshot({
    path: path.join(evidenceDir, "evidence.png"),
    fullPage: true,
  });

  await page.locator(".tabs button", { hasText: "决策简报" }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载决策简报" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/brief\.md$/);

  await page.screenshot({
    path: path.join(evidenceDir, "brief.png"),
    fullPage: true,
  });
});

test("cancel a running task and resume it", async ({ page, request }) => {
  const objective = `E2E 取消恢复 ${Date.now()}`;
  const created = await request.post("/api/v1/research/tasks", {
    data: {
      contract: {
        objective,
        regions: ["德清县"],
        research_focus: "竹产业",
      },
    },
  });
  expect(created.ok()).toBeTruthy();

  await page.goto("/");
  await page.locator(".task-item", { hasText: objective }).click();
  const detail = page.locator(".detail");
  await expect(detail.locator(".badge", { hasText: "运行中" }).first()).toBeVisible({
    timeout: 15_000,
  });

  await detail.getByRole("button", { name: "取消" }).click();
  await expect(detail.locator(".badge", { hasText: "已取消" }).first()).toBeVisible({
    timeout: 15_000,
  });

  await detail.getByRole("button", { name: "恢复运行" }).click();
  await expect(detail.locator(".badge", { hasText: "运行中" }).first()).toBeVisible({
    timeout: 15_000,
  });
  await expect(detail.locator(".badge", { hasText: "已完成" }).first()).toBeVisible({
    timeout: 30_000,
  });

  await page.screenshot({
    path: path.join(evidenceDir, "cancel-resume.png"),
    fullPage: true,
  });
});
