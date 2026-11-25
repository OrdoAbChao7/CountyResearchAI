import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const outputDir = path.resolve(
  here,
  "../../../experiments/quality/finish_roadmap_e2e",
);

const TERMINAL = [
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "BUDGET_EXHAUSTED",
  "INTERRUPTED",
];

async function createTerminalJob(
  request: APIRequestContext,
  objective: string,
): Promise<string> {
  const created = await request.post("/api/v1/research/tasks", {
    data: {
      contract: {
        objective,
        regions: ["安吉县"],
        research_focus: "竹产业",
        options: { deep_research: true },
      },
    },
  });
  expect(created.ok()).toBeTruthy();
  const jobId = (await created.json()).job_id as string;
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    const response = await request.get(`/api/v1/research/tasks/${jobId}`);
    if (response.ok()) {
      const detail = (await response.json()) as { status: string };
      if (TERMINAL.includes(detail.status)) return jobId;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`job ${jobId} did not reach a terminal state`);
}

function buildLargeGraph(runId: string) {
  const nodes: Array<Record<string, unknown>> = [];
  const edges: Array<Record<string, unknown>> = [];
  const counts: Record<string, number> = {};

  function addNode(node: Record<string, unknown> & { type: string }) {
    nodes.push(node);
    counts[node.type] = (counts[node.type] ?? 0) + 1;
  }

  function addEdge(source: string, target: string, type: string) {
    edges.push({
      id: `edge-${edges.length}`,
      source,
      target,
      type,
      label: type,
      directed: true,
      weight: 1,
      data: {},
    });
  }

  addNode({
    id: "county:perf",
    type: "county",
    label: "安吉县",
    sublabel: "snapshot",
    weight: 1,
    data: {},
  });
  for (let index = 0; index < 20; index += 1) {
    addNode({
      id: `q:${index}`,
      type: "question",
      label: `性能问题 ${index}`,
      sublabel: "economic",
      weight: 1,
      data: {},
    });
  }
  for (let index = 0; index < 300; index += 1) {
    addNode({
      id: `ev:${index}`,
      type: "evidence",
      label: `证据节点 ${index}`,
      sublabel: "产值指标",
      weight: 0.8,
      data: { claim_id: `claim-${index}`, status: "SUPPORTED" },
    });
  }
  for (let index = 0; index < 60; index += 1) {
    addNode({
      id: `src:${index}`,
      type: "source",
      label: `来源 ${index}`,
      sublabel: "example.gov.cn",
      weight: 0.6,
      data: {},
    });
  }
  for (let index = 0; index < 12; index += 1) {
    addNode({
      id: `topic:${index}`,
      type: "topic",
      label: `指标 ${index}`,
      sublabel: "经济",
      weight: 0.5,
      data: { metric: `指标 ${index}` },
    });
  }
  for (let index = 0; index < 7; index += 1) {
    addNode({
      id: `gap:${index}`,
      type: "gap",
      label: `缺口 ${index}`,
      sublabel: "high",
      weight: 1,
      data: {},
    });
  }

  for (let index = 0; index < 20; index += 1) {
    addEdge("county:perf", `q:${index}`, "has_question");
  }
  for (let index = 0; index < 300; index += 1) {
    addEdge(`q:${index % 20}`, `ev:${index}`, "supported_by");
  }
  for (let index = 0; index < 300; index += 1) {
    addEdge(`ev:${index}`, `src:${index % 60}`, "cited_from");
  }
  for (let topic = 0; topic < 12; topic += 1) {
    for (let offset = 0; offset < 15; offset += 1) {
      addEdge(`topic:${topic}`, `ev:${topic * 15 + offset}`, "belongs_to");
    }
  }

  return {
    run_id: runId,
    nodes,
    edges,
    meta: {
      total_nodes: nodes.length,
      returned_nodes: nodes.length,
      total_edges: edges.length,
      returned_edges: edges.length,
      truncated: false,
      coverage_rate: 0.55,
      counts,
      returned_counts: counts,
      dropped_self_loops: 0,
      unmatched_conflicts: 0,
    },
  };
}

test("wizard: define, run, inspect graph evidence, and read verified report", async ({
  page,
}) => {
  const objective = `E2E 安吉县竹产业深度研究 ${Date.now()}`;

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "CountyResearchAI" }),
  ).toBeVisible();
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

  await page.getByRole("tab", { name: /冲突与缺口/ }).click();
  await expect(page.locator(".disputes-panel")).toBeVisible();
  const taskId = new URL(page.url()).searchParams.get("task") ?? "";
  expect(taskId).not.toBe("");
  const reportResponse = await page.request.get(
    `/api/v1/research/tasks/${taskId}/report.json`,
  );
  expect(reportResponse.ok()).toBeTruthy();
  const reportData = (await reportResponse.json()) as {
    conflicts: unknown[];
    gaps: unknown[];
  };
  expect(reportData.conflicts.length).toBeGreaterThan(0);
  expect(reportData.gaps.length).toBeGreaterThan(0);
  await expect(page.locator(".conflict-card")).toHaveCount(
    reportData.conflicts.length,
  );
  await expect(page.locator(".gap-table tbody tr")).toHaveCount(
    reportData.gaps.length,
  );
  await page.screenshot({
    path: path.join(outputDir, "09-disputes.png"),
    fullPage: false,
  });

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

  await page.locator(".section-citations button").first().click();
  await expect(drawer).toBeVisible();
  await drawer.getByRole("button", { name: "在图谱中定位" }).click();
  await expect(page).toHaveURL(/step=3/);
  await expect(page).toHaveURL(/layout=graph/);
  await expect(page.locator(".graph-panel")).toBeVisible();
  await expect(page.locator(".context-panel .selection-card")).toContainText(
    "报告定位",
  );
  await page.screenshot({
    path: path.join(outputDir, "10-report-graph-link.png"),
    fullPage: false,
  });
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

test("graph: a 400-node projection stays interactive with the bounded layout", async ({
  page,
  request,
}) => {
  const jobId = await createTerminalJob(
    request,
    `E2E 大图谱性能 ${Date.now()}`,
  );
  const graph = buildLargeGraph(jobId);
  await page.route(
    new RegExp(`/api/v1/research/tasks/${jobId}/graph`),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(graph),
      }),
  );

  const started = Date.now();
  await page.goto(`/?step=3&layout=graph&task=${jobId}`);
  const canvas = page.locator('[data-testid="graph-canvas"]');
  await expect(canvas).toHaveAttribute("data-node-count", "400", {
    timeout: 30_000,
  });
  await expect(canvas).toHaveAttribute("data-layout", "concentric");
  await expect(canvas.locator("canvas").first()).toBeVisible({
    timeout: 30_000,
  });
  const renderMs = Date.now() - started;
  expect(renderMs).toBeLessThan(10_000);
  await page.screenshot({
    path: path.join(outputDir, "11-large-graph.png"),
    fullPage: false,
  });

  const listStarted = Date.now();
  await page.getByRole("tab", { name: "列表" }).click();
  await expect(page.locator(".graph-list-view tbody tr")).toHaveCount(400, {
    timeout: 10_000,
  });
  const listMs = Date.now() - listStarted;
  expect(listMs).toBeLessThan(3_000);
  console.log(
    `[perf] 400-node graph: first canvas ${renderMs}ms, list switch ${listMs}ms`,
  );

  await page.screenshot({
    path: path.join(outputDir, "12-large-graph-list.png"),
    fullPage: false,
  });
});

test("a11y: define, run, report, disputes and drawer pass WCAG A/AA", async ({
  page,
  request,
}) => {
  async function scan(surface: string) {
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    if (results.violations.length > 0) {
      console.log(
        `[a11y:${surface}]`,
        JSON.stringify(
          results.violations.map((violation) => ({
            id: violation.id,
            impact: violation.impact,
            targets: violation.nodes.map((node) => node.target.join(" ")),
          })),
        ),
      );
    }
    expect(
      results.violations,
      `${surface} accessibility violations`,
    ).toEqual([]);
  }

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "定义一个可验证的研究问题" }),
  ).toBeVisible();
  await scan("define");

  const jobId = await createTerminalJob(request, `E2E 无障碍 ${Date.now()}`);
  await page.goto(`/?step=2&layout=split&task=${jobId}`);
  await expect(page.locator(".run-status-strip")).toContainText("已完成");
  await scan("run");

  await page.goto(`/?step=4&layout=workbench&task=${jobId}`);
  await expect(page.locator(".report-section")).toHaveCount(6);
  await scan("report");

  await page.getByRole("tab", { name: /冲突与缺口/ }).click();
  await expect(page.locator(".disputes-panel")).toBeVisible();
  await scan("disputes");

  await page.goto(`/?step=3&layout=graph&task=${jobId}`);
  await page.getByRole("tab", { name: "列表" }).click();
  await expect(page.locator(".graph-list-view")).toBeVisible();
  await scan("graph list");

  await page
    .locator(".graph-list-view tbody tr")
    .filter({ has: page.locator(".type-evidence") })
    .first()
    .getByRole("button", { name: "打开证据" })
    .click();
  await expect(page.getByRole("dialog", { name: "证据抽屉" })).toBeVisible();
  await scan("evidence drawer");
});
