import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  snapshotPathTemplate:
    "{testDir}/visual-baselines/{projectName}/{platform}/{testFilePath}/{arg}{ext}",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  // The source viewer is intentionally image-heavy; a single browser worker
  // keeps local and constrained CI runs deterministic instead of provoking
  // Chromium renderer termination under parallel desktop navigation.
  workers: 1,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  expect: {
    toHaveScreenshot: {
      animations: "disabled",
      maxDiffPixelRatio: 0.015,
      threshold: 0.2,
    },
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: "mobile",
      use: {
        ...devices["iPhone 13"],
        viewport: { width: 390, height: 844 },
      },
    },
  ],
  webServer: {
    command: "corepack pnpm build && corepack pnpm start:e2e:standalone",
    url: "http://127.0.0.1:3000",
    env: {
      NEXT_PUBLIC_AKC_DEMO_MODE: "true",
      NEXT_PUBLIC_AKC_API_URL: "http://127.0.0.1:8000",
      NODE_OPTIONS: "--max-old-space-size=4096",
    },
    reuseExistingServer: !process.env.CI,
    timeout: process.env.CI ? 120_000 : 300_000,
  },
});
