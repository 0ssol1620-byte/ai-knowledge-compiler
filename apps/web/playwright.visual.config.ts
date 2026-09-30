import { defineConfig, devices } from "@playwright/test";

// Keep the approved platform-specific baselines separate from behavioral tests.
export default defineConfig({
  testDir: "./e2e",
  testMatch: /visual-regression\.spec\.ts/,
  outputDir: "./test-results/visual",
  snapshotPathTemplate:
    "{testDir}/visual-baselines/{projectName}/{platform}/{testFilePath}/{arg}{ext}",
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
  webServer: {
    command: "pnpm build && pnpm start:e2e:standalone",
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
