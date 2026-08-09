import { expect, test } from "@playwright/test";

/**
 * §20 evidence pass. One project per verification viewport (see
 * playwright.config.ts) so a layout that only breaks at 768 or 360 fails here
 * rather than in review.
 *
 * These are the machine-checkable items of §25.3 that depend on viewport:
 *   - horizontal overflow 0
 *   - no horizontal scroll at 200% zoom
 *   - no console errors
 */
const ROUTES = [
  "/",
  "/product",
  "/benchmarks",
  "/security",
  "/pricing",
  "/quick-convert",
  "/app/home",
  "/documents/sample-dart/processing",
] as const;

for (const route of ROUTES) {
  test(`${route} has no horizontal overflow`, async ({ page }) => {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await expect(page.locator("main")).toBeVisible();
    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }));
    expect(
      overflow.scrollWidth,
      `${route} overflows by ${overflow.scrollWidth - overflow.innerWidth}px`,
    ).toBeLessThanOrEqual(overflow.innerWidth);
  });
}

test("the homepage does not scroll sideways at 200% zoom", async ({
  page,
  viewport,
}) => {
  test.skip(viewport === null, "needs a fixed viewport");
  // 200% zoom is equivalent to halving the CSS viewport at the same device
  // pixel count. The floor is 320 CSS px: that is the width WCAG 2.2 1.4.10
  // names, and it is the narrowest layout anyone is entitled to. Halving 390 or
  // 360 lands at 195 or 180 px, which no criterion asks a layout to survive —
  // asserting there would fail a compliant page.
  const width = Math.max(320, Math.round(viewport!.width / 2));
  await page.setViewportSize({
    width,
    height: Math.round(viewport!.height / 2),
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(
    overflow,
    `overflows by ${overflow}px at ${width} CSS px`,
  ).toBeLessThanOrEqual(0);
});

/**
 * §25.3 "console errors 0". This is the authoritative check, not Lighthouse's
 * errors-in-console audit — that audit counts failed network requests, and the
 * App Router prefetches every visible <Link> then aborts those requests, so it
 * reports two dozen failures on a page that has none.
 *
 * Here the three signals are separated: real console errors and page
 * exceptions must be zero, and a failed request must be zero unless it is an
 * RSC prefetch the framework itself cancelled.
 */
test("public routes log no console errors", async ({ page }) => {
  const errors: string[] = [];
  const failedRequests: string[] = [];

  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error}`));
  page.on("requestfailed", (request) => {
    // ?_rsc= is the App Router's prefetch; aborting one is normal.
    if (request.url().includes("_rsc=")) return;
    failedRequests.push(`${request.url()} — ${request.failure()?.errorText}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      failedRequests.push(`HTTP ${response.status()} ${response.url()}`);
    }
  });

  for (const route of ["/", "/product", "/benchmarks"]) {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await expect(page.locator("main")).toBeVisible();
  }

  expect(errors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
