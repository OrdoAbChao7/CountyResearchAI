import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webDir = fileURLToPath(new URL(".", import.meta.url));
const root = path.resolve(webDir, "..");
const port = Number(process.env.AXIOMSCOPE_E2E_PORT ?? "8000");
const python =
  process.env.AXIOMSCOPE_E2E_PYTHON ??
  path.join(
    root,
    ".venv",
    process.platform === "win32" ? "Scripts" : "bin",
    process.platform === "win32" ? "python.exe" : "python",
  );
const runDir = path.join(root, "experiments", "quality", "finish_roadmap_e2e");

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { outputFolder: path.join(runDir, "playwright-report") }],
  ],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 960 },
    trace: "on",
    screenshot: "only-on-failure",
    video: "off",
  },
  webServer: {
    command: `"${python}" -m county_research_ai.api`,
    cwd: root,
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      PYTHONPATH: path.join(root, "src"),
      DATA_DIR: path.join(runDir, "data"),
      REPORTS_DIR: path.join(runDir, "reports"),
      AXIOMSCOPE_API_LIVE: "false",
      AXIOMSCOPE_API_PORT: String(port),
      AXIOMSCOPE_API_HOST: "127.0.0.1",
      AXIOMSCOPE_MOCK_STAGE_DELAY_SECONDS: "2",
      PYTHONIOENCODING: "utf-8",
    },
  },
});
