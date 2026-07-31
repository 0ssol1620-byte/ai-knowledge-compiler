import { expect, test } from "@playwright/test";

const representativeRoutes = [
  "/",
  "/product/verify",
  "/demo/dart",
  "/demo/sec",
  "/security",
  "/quick-convert",
  "/projects",
  "/knowledge-bases",
  "/review",
  "/legal/privacy",
] as const;

test("representative public and product surfaces remain usable across the release matrix", async ({
  page,
}, testInfo) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  for (const route of representativeRoutes) {
    const response = await page.goto(route, { waitUntil: "domcontentloaded" });
    expect(
      response?.status(),
      `${route} response on ${testInfo.project.name}`,
    ).toBeLessThan(400);
    await expect(
      page.locator("h1"),
      `${route} must expose exactly one H1 on ${testInfo.project.name}`,
    ).toHaveCount(1);
    await expect(
      page.locator("h1"),
      `${route} H1 must be visible on ${testInfo.project.name}`,
    ).toBeVisible();

    const metrics = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      activeElementHidden:
        document.activeElement instanceof HTMLElement &&
        (document.activeElement.hidden ||
          document.activeElement.getAttribute("aria-hidden") === "true"),
    }));
    const hasOverflow =
      metrics.scrollWidth > metrics.clientWidth + 1 ||
      metrics.bodyWidth > metrics.clientWidth + 1;
    const overflowDiagnostics = hasOverflow
      ? await page.evaluate(() =>
          Array.from(document.querySelectorAll<HTMLElement>("body *"))
            .map((element) => {
              const rect = element.getBoundingClientRect();
              return {
                tag: element.tagName.toLowerCase(),
                className: element.className?.toString().slice(0, 120) || "",
                id: element.id,
                left: Math.round(rect.left),
                right: Math.round(rect.right),
                width: Math.round(rect.width),
                scrollWidth: element.scrollWidth,
                clientWidth: element.clientWidth,
              };
            })
            .filter(
              (item) =>
                item.right > document.documentElement.clientWidth + 1 ||
                item.left < -1 ||
                item.scrollWidth > item.clientWidth + 1,
            )
            .sort((left, right) => right.right - left.right)
            .slice(0, 12),
        )
      : [];
    expect(
      metrics.scrollWidth,
      `${route} document overflow on ${testInfo.project.name}: ${JSON.stringify(overflowDiagnostics)}`,
    ).toBeLessThanOrEqual(metrics.clientWidth + 1);
    expect(
      metrics.bodyWidth,
      `${route} body overflow on ${testInfo.project.name}`,
    ).toBeLessThanOrEqual(metrics.clientWidth + 1);
    expect(metrics.activeElementHidden).toBe(false);
  }

  expect(
    consoleErrors.filter(
      (message) =>
        !message.includes("favicon") &&
        !message.includes("Download the React DevTools"),
    ),
  ).toEqual([]);
});
