import { defineConfig, devices } from "@playwright/test";

const appUrl = process.env.GOLDEN_PATH_APP_URL;
if (!appUrl) throw new Error("GOLDEN_PATH_APP_URL is required");

export default defineConfig({
  testDir: "./tests-full-stack",
  timeout: 120_000,
  expect: { timeout: 10_000 },
  retries: 0,
  workers: 1,
  outputDir: process.env.GOLDEN_PATH_OUTPUT_DIR ?? "test-results/full-stack",
  reporter: [
    ["line"],
    ["html", { open: "never", outputFolder: process.env.GOLDEN_PATH_REPORT_DIR ?? "playwright-report/full-stack" }]
  ],
  use: {
    baseURL: appUrl,
    screenshot: "only-on-failure",
    trace: "retain-on-failure"
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }]
});
