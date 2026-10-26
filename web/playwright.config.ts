import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webDir = fileURLToPath(new URL(".", import.meta.url));
const root = path.resolve(webDir, "..");

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { outputFolder: "../experiments/quality/20261026_q5_e2e/playwright-report" }]],
  use: {
    baseURL: "http://127.0.0.1:8000",
    trace: "on",
    screenshot: "on",
    video: "off",
  },
  webServer: {
    command: ".venv\\Scripts\\python.exe -m county_research_ai.api",
    cwd: root,
    url: "http://127.0.0.1:8000/health",
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      DATA_DIR: path.join(root, "experiments/quality/20261026_q5_e2e/data"),
      REPORTS_DIR: path.join(root, "experiments/quality/20261026_q5_e2e/reports"),
      AXIOMSCOPE_API_LIVE: "false",
      AXIOMSCOPE_API_PORT: "8000",
      AXIOMSCOPE_API_HOST: "127.0.0.1",
      AXIOMSCOPE_MOCK_STAGE_DELAY_SECONDS: "3",
    },
  },
});
