import { expect, test, type BrowserContext, type TestInfo } from "@playwright/test";

test.beforeEach(({}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop",
    "Approved screenshot baselines are desktop-only; compact and mobile behavior is covered by the browser matrix.",
  );
});

type Locale = "en" | "ko";

const localeCookieName = "akc_locale";
const integrityPath = "/integrity?reference=1";

const visualRoutes = [
  { name: "marketing-home", path: "/", locale: "en" },
  { name: "evidence-film", path: "/film?scene=4&static=1", locale: "en" },
  { name: "benchmark-evidence", path: "/benchmarks", locale: "en" },
  { name: "verify-product", path: "/product/verify", locale: "en" },
  { name: "dart-public-proof", path: "/demo/dart", locale: "en" },
  { name: "sec-public-proof", path: "/demo/sec", locale: "en" },
  { name: "security-architecture", path: "/security", locale: "en" },
  { name: "projects-operations", path: "/projects", locale: "ko" },
  { name: "integrity-console", path: integrityPath, locale: "ko" },
  { name: "knowledge-studio", path: "/knowledge-bases", locale: "ko" },
  { name: "privacy-publication-control", path: "/legal/privacy", locale: "en" },
] as const;

// Pins the locale per capture so each screenshot matches its approved baseline
// without relying on (or changing) the product's default locale.
async function setLocaleCookie(context: BrowserContext, testInfo: TestInfo, locale: Locale) {
  const baseURL = testInfo.project.use.baseURL;
  if (!baseURL) {
    throw new Error(
      `Playwright project "${testInfo.project.name}" has no use.baseURL; cannot scope the ${localeCookieName} cookie.`,
    );
  }
  await context.addCookies([{ name: localeCookieName, value: locale, url: baseURL }]);
}

function langPattern(locale: Locale) {
  return new RegExp(`^${locale}(-|$)`, "i");
}

for (const route of visualRoutes) {
  test(`${route.name} visual baseline`, async ({ page }, testInfo) => {
    await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await setLocaleCookie(page.context(), testInfo, route.locale);
    const response = await page.goto(route.path, { waitUntil: "networkidle" });
    expect(response?.status()).toBeLessThan(400);
    await expect(page.locator("html")).toHaveAttribute("lang", langPattern(route.locale));
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
        .st-home > section,
        .folynta-v4-home > section,
        .tv-home > section {
          content-visibility: visible !important;
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

test("unauthenticated visitor without a locale cookie defaults to Korean", async ({ page }) => {
  const cookies = await page.context().cookies();
  expect(cookies.find((cookie) => cookie.name === localeCookieName)).toBeUndefined();
  const response = await page.goto("/", { waitUntil: "networkidle" });
  expect(response?.status()).toBeLessThan(400);
  await expect(page.locator("html")).toHaveAttribute("lang", langPattern("ko"));
});

for (const locale of ["en", "ko"] as const) {
  test(`integrity sidebar brand subtitle is fully visible (${locale})`, async ({ page }, testInfo) => {
    await setLocaleCookie(page.context(), testInfo, locale);
    const response = await page.goto(integrityPath, { waitUntil: "networkidle" });
    expect(response?.status()).toBeLessThan(400);
    await expect(page.locator("html")).toHaveAttribute("lang", langPattern(locale));

    const subtitle = page.locator(".app-frame .sidebar .brand-copy small");
    await expect(subtitle).toHaveCount(1);
    await expect(subtitle).toBeVisible();
    await expect(subtitle).toHaveText("The Knowledge Compiler");
    await page.evaluate(() => document.fonts.ready);

    const metrics = await subtitle.evaluate((element) => {
      const measure = (node: Element | null) =>
        node ? { clientWidth: node.clientWidth, scrollWidth: node.scrollWidth } : null;
      return {
        subtitle: measure(element),
        brandCopy: measure(element.closest(".brand-copy")),
      };
    });

    expect(metrics.brandCopy, "brand-copy container").not.toBeNull();
    expect(metrics.brandCopy!.clientWidth, "brand-copy has layout width").toBeGreaterThan(0);
    expect(metrics.brandCopy!.scrollWidth, "brand-copy is not horizontally clipped").toBeLessThanOrEqual(
      metrics.brandCopy!.clientWidth,
    );
    expect(metrics.subtitle!.scrollWidth, "subtitle is not horizontally clipped").toBeLessThanOrEqual(
      metrics.subtitle!.clientWidth,
    );
  });
}
