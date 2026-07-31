import { expect, test } from "@playwright/test";

test.beforeEach(({}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop",
    "Approved screenshot baselines are desktop-only; compact and mobile behavior is covered by the browser matrix.",
  );
});

const visualRoutes = [
  { name: "marketing-home", path: "/" },
  { name: "verify-product", path: "/product/verify" },
  { name: "dart-public-proof", path: "/demo/dart" },
  { name: "sec-public-proof", path: "/demo/sec" },
  { name: "security-architecture", path: "/security" },
  { name: "projects-operations", path: "/projects" },
  { name: "review-studio", path: "/review" },
  { name: "knowledge-studio", path: "/knowledge-bases" },
  { name: "privacy-publication-control", path: "/legal/privacy" },
] as const;

for (const route of visualRoutes) {
  test(`${route.name} visual baseline`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    const response = await page.goto(route.path, { waitUntil: "networkidle" });
    expect(response?.status()).toBeLessThan(400);
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).toBeVisible();
    await page.addStyleTag({
      content: `
        *, *::before, *::after {
          animation-delay: 0s !important;
          animation-duration: 0s !important;
          caret-color: transparent !important;
          transition-delay: 0s !important;
          transition-duration: 0s !important;
        }
      `,
    });
    await page.evaluate(() => document.fonts.ready);
    await expect(page).toHaveScreenshot(`${route.name}.png`, {
      fullPage: true,
      animations: "disabled",
    });
  });
}
