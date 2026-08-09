import { defineConfig, devices, type PlaywrightTestConfig } from "@playwright/test";

// §20 evidence viewports. AGENTS.md previously asked for four widths
// (1920/1440/1024/390) and this file only had two projects; the masterplan asks
// for seven. The seven-width set wins — see decision.md, "검증 뷰포트" — and
// AGENTS.md was updated to match.
const EVIDENCE_VIEWPORTS = [
  { name: "w1920", width: 1920, height: 1080 },
  { name: "w1440", width: 1440, height: 900 },
  { name: "w1280", width: 1280, height: 800 },
  { name: "w1024", width: 1024, height: 768 },
  { name: "w768", width: 768, height: 1024 },
  { name: "w390", width: 390, height: 844 },
  { name: "w360", width: 360, height: 800 },
] as const;

type Project = NonNullable<PlaywrightTestConfig["projects"]>[number];

const evidenceProjects: Project[] = EVIDENCE_VIEWPORTS.map((viewport) => ({
  name: viewport.name,
  testMatch: /evidence\.spec\.ts/,
  use: {
    ...devices["Desktop Chrome"],
    viewport: { width: viewport.width, height: viewport.height },
  },
}));

const reducedMotionProject: Project = {
  name: "reduced-motion",
  testMatch: /evidence\.spec\.ts/,
  use: {
    ...devices["Desktop Chrome"],
    viewport: { width: 1440, height: 900 },
    // Playwright exposes reduced motion through contextOptions, not as a
    // top-level use key.
    contextOptions: { reducedMotion: "reduce" },
  },
};

const projects: Project[] = [
  // Behaviour suite. Kept at two projects on purpose: running the 34-route and
  // 31-route manifests once per viewport would multiply the run by seven for no
  // extra behavioural coverage.
  {
    name: "desktop",
    testIgnore: /evidence\.spec\.ts/,
    use: { ...devices["Desktop Chrome"] },
  },
  {
    name: "mobile",
    testIgnore: /evidence\.spec\.ts/,
    use: { ...devices["iPhone 13"] },
  },

  // Evidence suite. Overflow, zoom, and console checks at every §20 width.
  ...evidenceProjects,
  reducedMotionProject,
];

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
  projects,
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
