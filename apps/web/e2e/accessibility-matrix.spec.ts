import { expect, test } from "@playwright/test";

const coreRoutes = [
  "/",
  "/intake",
  "/workspace",
  "/integrity",
  "/knowledge-bases",
  "/demo/dart",
] as const;

const typographyRoutes = [
  "/",
  "/product/verify",
  "/intake",
  "/documents/sample-dart/processing",
  "/integrity?reference=1",
  "/knowledge-bases",
  "/demo/dart",
  "/demo/sec",
  "/security",
  "/projects",
  "/legal/privacy",
] as const;

test("core journeys preserve meaning and focus in forced colors", async ({
  page,
}) => {
  await page.emulateMedia({
    forcedColors: "active",
    reducedMotion: "reduce",
    colorScheme: "light",
  });

  for (const route of coreRoutes) {
    const response = await page.goto(route, { waitUntil: "domcontentloaded" });
    expect(response?.status(), route).toBeLessThan(400);
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("h1")).toBeVisible();
    const focusable = page
      .locator(
        'main a[href], main button:not([disabled]), main input:not([disabled]), main select:not([disabled]), main textarea:not([disabled]), main [tabindex="0"]',
      )
      .first();
    if ((await focusable.count()) > 0) {
      await focusable.focus();
      await expect(focusable).toBeFocused();
      const focusStyle = await focusable.evaluate((element) => {
        const style = getComputedStyle(element);
        return {
          outlineStyle: style.outlineStyle,
          outlineWidth: style.outlineWidth,
          boxShadow: style.boxShadow,
        };
      });
      expect(
        focusStyle.outlineStyle !== "none" ||
          focusStyle.outlineWidth !== "0px" ||
          focusStyle.boxShadow !== "none",
        `${route} must retain a visible focus treatment in forced colors`,
      ).toBe(true);
    }
  }
});

test("core journeys tolerate 200 percent text scaling without horizontal overflow", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "desktop text-scaling contract");

  for (const route of coreRoutes) {
    const response = await page.goto(route, { waitUntil: "domcontentloaded" });
    expect(response?.status(), route).toBeLessThan(400);
    await page.addStyleTag({
      content: `
        html { font-size: 200% !important; }
        *, *::before, *::after {
          animation: none !important;
          transition: none !important;
        }
      `,
    });
    await expect(page.locator("h1")).toBeVisible();
    const metrics = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
    }));
    expect(metrics.scrollWidth, `${route} document overflow at 200% text`).toBeLessThanOrEqual(
      metrics.clientWidth + 1,
    );
    expect(metrics.bodyWidth, `${route} body overflow at 200% text`).toBeLessThanOrEqual(
      metrics.clientWidth + 1,
    );
  }
});

test("core journeys never render visible text below 12 pixels", async ({
  page,
}) => {
  for (const route of typographyRoutes) {
    const response = await page.goto(route, { waitUntil: "domcontentloaded" });
    expect(response?.status(), route).toBeLessThan(400);
    await expect(page.locator("h1")).toBeVisible();

    const undersized = await page.evaluate(() => {
      const failures: Array<{
        selector: string;
        size: number;
        text: string;
      }> = [];
      const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
      );

      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const text = node.textContent?.replace(/\s+/g, " ").trim();
        const element = node.parentElement;
        if (
          !text ||
          !element ||
          element.closest(
            'script, style, template, noscript, svg, [aria-hidden="true"]',
          )
        ) {
          continue;
        }
        const range = document.createRange();
        range.selectNodeContents(node);
        const rect = range.getBoundingClientRect();
        const style = getComputedStyle(element);
        const visible =
          rect.width > 1 &&
          rect.height > 1 &&
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          Number(style.opacity) > 0;
        const fontSize = Number.parseFloat(style.fontSize);
        if (visible && Number.isFinite(fontSize) && fontSize < 11.99) {
          failures.push({
            selector: [
              element.tagName.toLowerCase(),
              element.id ? `#${element.id}` : "",
              ...Array.from(element.classList, (name) => `.${name}`),
            ].join(""),
            size: fontSize,
            text: text.slice(0, 80),
          });
        }
      }

      return failures.slice(0, 40);
    });

    expect(undersized, `${route} contains visible text below 12px`).toEqual([]);
  }
});

test("core controls and form labels render at 14 pixels or larger", async ({
  page,
}) => {
  const controlRoutes = [
    "/",
    "/product/verify",
    "/intake",
    "/documents/sample-dart/processing",
    "/integrity?reference=1",
    "/knowledge-bases",
    "/demo/dart",
    "/demo/sec",
    "/security",
    "/projects",
    "/legal/privacy",
  ] as const;

  for (const route of controlRoutes) {
    const response = await page.goto(route, { waitUntil: "domcontentloaded" });
    expect(response?.status(), route).toBeLessThan(400);
    await expect(page.locator("h1")).toBeVisible();

    const undersized = await page.evaluate(() =>
      Array.from(
        document.querySelectorAll<HTMLElement>(
          "main a[href], main button, main input, main select, main textarea, main summary, main label",
        ),
      )
        .filter((element) => {
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          const hasVisibleCopy =
            element.innerText.trim().length > 0 ||
            (element instanceof HTMLInputElement &&
              (element.value.length > 0 || element.placeholder.length > 0)) ||
            element instanceof HTMLSelectElement ||
            element instanceof HTMLTextAreaElement;
          return (
            hasVisibleCopy &&
            rect.width > 1 &&
            rect.height > 1 &&
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            Number(style.opacity) > 0
          );
        })
        .map((element) => ({
          selector: [
            element.tagName.toLowerCase(),
            element.id ? `#${element.id}` : "",
            ...Array.from(element.classList, (name) => `.${name}`),
          ].join(""),
          size: Number.parseFloat(getComputedStyle(element).fontSize),
          text: (
            element.innerText ||
            (element instanceof HTMLInputElement
              ? element.value || element.placeholder
              : "")
          )
            .replace(/\s+/g, " ")
            .trim()
            .slice(0, 80),
        }))
        .filter(({ size }) => Number.isFinite(size) && size < 13.99)
        .slice(0, 40),
    );

    expect
      .soft(undersized, `${route} contains a core control below 14px`)
      .toEqual([]);
  }
});
