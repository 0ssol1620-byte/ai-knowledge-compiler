import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

const repoRoot = resolve(__dirname, "../..");
const serverTimeout = process.env.CI ? 180_000 : 300_000;

export default defineConfig({
  testDir: "./e2e-live",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["html", { open: "never" }], ["list"]],
  // This single journey performs real registration, verification, upload,
  // analysis, compilation, SSE, and export. A cold Windows/CI process can
  // legitimately spend more than two minutes compiling routes and importing
  // the local parser before the workflow itself starts.
  timeout: 300_000,
  expect: {
    timeout: 20_000,
  },
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "live-chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "node scripts/start-e2e-api.mjs",
      cwd: repoRoot,
      url: "http://127.0.0.1:8100/health/ready",
      reuseExistingServer: false,
      timeout: serverTimeout,
    },
    {
      command:
        "pnpm --filter @akc/web exec next dev --webpack --hostname 127.0.0.1 --port 3100",
      cwd: repoRoot,
      url: "http://127.0.0.1:3100/api/health",
      env: {
        NEXT_DIST_DIR: ".next-e2e-live",
        NEXT_PUBLIC_AKC_DEMO_MODE: "false",
        NEXT_PUBLIC_AKC_API_URL: "http://127.0.0.1:8100",
      },
      reuseExistingServer: false,
      timeout: serverTimeout,
    },
  ],
});
