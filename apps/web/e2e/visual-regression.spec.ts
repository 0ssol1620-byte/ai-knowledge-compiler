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

// The utilities-layer 12px leaf floor is !important, so it outranks unlayered
// component sizes; this pins the exemptions without letting the floor lapse.
test("privacy page keeps component type sizes above the 12px leaf floor", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
  await setLocaleCookie(page.context(), testInfo, "en");
  const response = await page.goto("/legal/privacy", { waitUntil: "networkidle" });
  expect(response?.status()).toBeLessThan(400);
  await expect(page.locator("html")).toHaveAttribute("lang", langPattern("en"));
  await page.evaluate(() => document.fonts.ready);

  const fontSize = async (selector: string) => {
    const target = page.locator(selector).first();
    await expect(target, selector).toBeVisible();
    return target.evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize));
  };

  const thesis = await fontSize(".tv-thesis p");
  expect(thesis, "thesis").toBeGreaterThanOrEqual(40);
  expect(thesis, "thesis").toBeLessThanOrEqual(64);

  const headline = await fontSize(".tv-page-hero-copy h1");
  expect(headline, "headline").toBeGreaterThanOrEqual(58);
  expect(headline, "headline").toBeLessThanOrEqual(82);

  expect(await fontSize(".tv-page-hero-copy > p:not(.tv-context-label)"), "body lead").toBe(18);
  expect(await fontSize(".tv-page-sections p"), "section body").toBe(17);

  for (const [label, selector] of [
    ["thesis caption", ".tv-thesis span"],
    ["context label", ".tv-page-hero-copy > .tv-context-label"],
  ] as const) {
    expect(await fontSize(selector), label).toBeGreaterThanOrEqual(12);
  }
});

test("integrity status register code exposes every character", async ({ page }, testInfo) => {
  await setLocaleCookie(page.context(), testInfo, "ko");
  const response = await page.goto(integrityPath, { waitUntil: "networkidle" });
  expect(response?.status()).toBeLessThan(400);
  await expect(page.locator("html")).toHaveAttribute("lang", langPattern("ko"));
  await page.evaluate(() => document.fonts.ready);

  const code = page.locator(".app-frame .integrity-status-register code").filter({ hasText: /^authority_verified$/ });
  await expect(code).toHaveCount(1);

  const initialViewport = page.viewportSize();
  expect(initialViewport, "project defines a viewport").not.toBeNull();
  const viewportHeight = initialViewport!.height;

  for (const width of [1440, 768, 390, 360]) {
    await page.setViewportSize({ width, height: viewportHeight });
    await page.evaluate(() => document.fonts.ready);

    await expect(code, `code visible at ${width}px`).toBeVisible();
    await expect(code, `full text at ${width}px`).toHaveText("authority_verified");

    const metrics = await code.evaluate((element) => {
      const isClipped = (node: Element) =>
        node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1;

      const control = document.createElement("span");
      control.textContent = element.textContent;
      control.style.font = getComputedStyle(element).font;
      Object.assign(control.style, {
        display: "block",
        width: "64px",
        whiteSpace: "nowrap",
        overflow: "hidden",
        textOverflow: "ellipsis",
      });

      const measured = {
        text: element.textContent,
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
        scrollHeight: element.scrollHeight,
        clientHeight: element.clientHeight,
        clipped: isClipped(element),
      };

      element.parentElement!.append(control);
      try {
        return { ...measured, controlClipped: isClipped(control) };
      } finally {
        control.remove();
      }
    });

    expect(metrics.controlClipped, `negative control: 64px nowrap ellipsis span is clipped at ${width}px`).toBe(true);
    expect(metrics.text, `measured text at ${width}px`).toBe("authority_verified");
    expect(metrics.clientWidth, `code has layout width at ${width}px`).toBeGreaterThan(0);
    expect(metrics.scrollWidth, `no horizontal clipping at ${width}px`).toBeLessThanOrEqual(metrics.clientWidth + 1);
    expect(metrics.scrollHeight, `no vertical clipping at ${width}px`).toBeLessThanOrEqual(metrics.clientHeight + 1);
    expect(metrics.clipped, `code is not clipped at ${width}px`).toBe(false);
  }
});
