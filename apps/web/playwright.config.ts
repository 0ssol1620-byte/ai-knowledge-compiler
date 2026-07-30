import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
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
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["iPhone 13"] } },
  ],
  webServer: {
    command: "pnpm dev",
    url: "http://127.0.0.1:3000",
    env: {
      NEXT_PUBLIC_AKC_DEMO_MODE: "true",
      NEXT_PUBLIC_AKC_API_URL: "http://127.0.0.1:8000",
    },
    reuseExistingServer: !process.env.CI,
    timeout: process.env.CI ? 120_000 : 300_000,
  },
});
