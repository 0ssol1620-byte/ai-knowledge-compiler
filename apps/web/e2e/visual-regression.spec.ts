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

// Visual-hierarchy contract, not an interaction test: the leaf floor's
// max(12px, 1em) resolves against the parent, so without a named exemption it
// replaces authored proof-section sizes with the parent size. A <div> probe is
// outside the leaf selector, so it resolves each token as the component does.
test("home proof sections preserve authored type sizes and readability floors", async ({
  page,
}, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
  await setLocaleCookie(page.context(), testInfo, "en");
  const response = await page.goto("/", { waitUntil: "networkidle" });
  expect(response?.status()).toBeLessThan(400);
  await expect(page.locator("html")).toHaveAttribute("lang", langPattern("en"));
  await page.evaluate(() => document.fonts.ready);

  const typography = [
    {
      role: "section labels",
      selector:
        ".tv-accuracy-eyebrow, .tv-accuracy-table thead th, .tv-accuracy-evidence, .tv-recovery-eyebrow, .tv-recovery-arm span, .tv-recovery-arm small, .tv-campaign-eyebrow, .tv-campaign-rates article span, .tv-campaign-stages li span, .tv-campaign-pending span",
      token: "--fs-label",
    },
    {
      role: "accuracy and recovery figures",
      selector: ".tv-accuracy-figure strong, .tv-recovery-arm strong",
      token: "--fs-display-1",
    },
    {
      role: "campaign figures",
      selector: ".tv-campaign-rates article strong",
      token: "--fs-title-1",
    },
    {
      role: "accuracy figure captions",
      selector: ".tv-accuracy-figure span",
      token: "--fs-small",
    },
    {
      role: "body copy",
      selector:
        ".tv-accuracy-context p:not(.tv-accuracy-corpus), .tv-accuracy-spread, .tv-accuracy-cell b, .tv-accuracy-worst-note, .tv-recovery-context p, .tv-campaign-note",
      token: "--fs-body",
    },
    {
      role: "small copy and table cells",
      selector:
        ".tv-accuracy-corpus, .tv-accuracy-table td, .tv-recovery-corroboration dt, .tv-recovery-corroboration dd, .tv-recovery-direction, .tv-campaign-rates article p, .tv-campaign-stages li, .tv-campaign-guarantees li, .tv-campaign-pending p",
      token: "--fs-small",
    },
    {
      role: "recovery lead and campaign guarantees",
      selector: ".tv-recovery-lead, .tv-campaign-guarantees b",
      token: "--fs-lead",
    },
  ] as const;

  for (const { role, selector, token } of typography) {
    const leaves = page.locator(selector);
    expect(await leaves.count(), `${role} elements`).toBeGreaterThan(0);

    const measured = await leaves.evaluateAll(
      (elements, tokenName) =>
        elements.map((element) => {
          const parent = element.parentElement!;
          const probe = document.createElement("div");
          probe.setAttribute("aria-hidden", "true");
          probe.style.cssText = `position: absolute; visibility: hidden; font-size: var(${tokenName});`;
          parent.appendChild(probe);
          try {
            return {
              actual: Number.parseFloat(getComputedStyle(element).fontSize),
              expected: Number.parseFloat(getComputedStyle(probe).fontSize),
            };
          } finally {
            probe.remove();
          }
        }),
      token,
    );

    for (const [index, { actual, expected }] of measured.entries()) {
      const label = `${role} #${index}`;
      expect(Number.isFinite(expected), `${label}: ${token} resolves`).toBe(
        true,
      );
      expect(
        expected,
        `${label}: authored size respects the 12px minimum`,
      ).toBeGreaterThanOrEqual(12);
      expect(actual, `${label}: resolves ${token}`).toBe(expected);
    }
  }

  const floors = await page.evaluate(() => {
    const host = document.createElement("div");
    host.style.cssText =
      "position: fixed; inset: 0 auto auto 0; font-size: 10px;";
    const bodyLeaf = document.createElement("span");
    bodyLeaf.style.fontSize = "8px";
    const control = document.createElement("button");
    control.style.fontSize = "8px";
    host.append(bodyLeaf, control);
    document.querySelector("main")!.appendChild(host);
    try {
      return {
        body: Number.parseFloat(getComputedStyle(bodyLeaf).fontSize),
        control: Number.parseFloat(getComputedStyle(control).fontSize),
      };
    } finally {
      host.remove();
    }
  });
  expect(
    floors.body,
    "ordinary leaves retain the 12px floor",
  ).toBeGreaterThanOrEqual(12);
  expect(
    floors.control,
    "interactive controls retain the separate 14px floor",
  ).toBeGreaterThanOrEqual(14);
});

// The hero source page is an aria-hidden facsimile laid out at fixed bbox1000
// coordinates with overflow: hidden. A px floor there does not make it readable;
// it clips the title and drops table rows, so the picture stops matching the
// coordinates the highlights and threads are drawn from. This pins proportional
// type inside it while the readable surfaces around it keep their floors.
test("home source facsimile stays proportional and unclipped at its bbox geometry", async ({
  page,
}, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
  await setLocaleCookie(page.context(), testInfo, "en");
  const response = await page.goto("/", { waitUntil: "networkidle" });
  expect(response?.status()).toBeLessThan(400);
  await expect(page.locator("html")).toHaveAttribute("lang", langPattern("en"));
  await page.evaluate(() => document.fonts.ready);

  const paper = page.locator('.tv-hero-comp-paper[aria-hidden="true"]');
  await expect(paper).toHaveCount(1);
  await expect(
    page.locator(".tv-hero-comp-page > p.sr-only"),
    "the facsimile keeps its text alternative",
  ).toContainText("a demo document and not an actual source");

  const facsimile = await paper.evaluate((element) => {
    const width = element.getBoundingClientRect().width;
    const size = (node: Element) => Number.parseFloat(getComputedStyle(node).fontSize);
    const rect = (node: Element) => {
      const { top, right, bottom, left } = node.getBoundingClientRect();
      return { top, right, bottom, left };
    };
    const blocks = Array.from(element.querySelectorAll<HTMLElement>(".tv-hero-comp-block")).map(
      (block) => ({
        kind: block.dataset.kind,
        size: size(block),
        rect: rect(block),
        overflowX: block.scrollWidth - block.clientWidth,
        overflowY: block.scrollHeight - block.clientHeight,
      }),
    );
    const table = element.querySelector('.tv-hero-comp-block[data-kind="table"]')!;
    const sourcePage = element.closest(".tv-hero-comp-page")!;
    const head = element.querySelector<HTMLElement>(".tv-hero-comp-paper-head")!;
    const headLabel = head.querySelector("span")!;
    return {
      width,
      head: size(head),
      headLabel: size(headLabel),
      headOverflowX: head.scrollWidth - head.clientWidth,
      headRect: rect(head),
      headLabelRect: rect(headLabel),
      blocks,
      tableBlock: rect(table),
      tableLeaves: Array.from(table.querySelectorAll("caption, th, td")).map(size),
      rows: Array.from(table.querySelectorAll("tbody tr")).map(rect),
      highlights: Array.from(sourcePage.querySelectorAll<HTMLElement>(".tv-hero-comp-bbox")).map(
        (bbox) => ({ state: bbox.dataset.state, rect: rect(bbox) }),
      ),
    };
  });

  expect(facsimile.width, "facsimile has layout width").toBeGreaterThan(0);
  const cqw = (percent: number) => (facsimile.width * percent) / 100;
  const expectedSize = { title: 3.6, heading: 2.5, paragraph: 2.4, table: 2.1 } as const;

  expect(facsimile.head, "page header scales with the page").toBeCloseTo(cqw(2.1), 0);
  expect(facsimile.headLabel, "header sample label is not floored").toBeCloseTo(cqw(2.1), 0);
  // Both header labels are drawn whole: nothing runs past the header, the
  // disclaimer label ends inside it, and the header ends above the title bbox.
  expect(facsimile.headOverflowX, "page header is not horizontally clipped").toBeLessThanOrEqual(1);
  expect(
    facsimile.headLabelRect.right,
    "header sample label ends inside the header",
  ).toBeLessThanOrEqual(facsimile.headRect.right + 1);
  expect(facsimile.headRect.bottom, "page header ends above the title").toBeLessThanOrEqual(
    facsimile.blocks[0]!.rect.top,
  );
  expect(facsimile.blocks.map((block) => block.kind)).toEqual([
    "title",
    "heading",
    "paragraph",
    "table",
  ]);
  for (const block of facsimile.blocks) {
    const kind = block.kind as keyof typeof expectedSize;
    expect(block.size, `${kind} scales with the page`).toBeCloseTo(cqw(expectedSize[kind]), 0);
    expect(block.overflowX, `${kind} is not horizontally clipped`).toBeLessThanOrEqual(1);
    expect(block.overflowY, `${kind} is not vertically clipped`).toBeLessThanOrEqual(1);
  }
  for (const [index, leaf] of facsimile.tableLeaves.entries()) {
    expect(leaf, `table leaf #${index} is not floored`).toBeCloseTo(cqw(2.1), 0);
  }
  expect(facsimile.rows, "both table rows are drawn").toHaveLength(2);
  for (const [index, row] of facsimile.rows.entries()) {
    expect(row.bottom, `table row #${index} sits inside its bbox`).toBeLessThanOrEqual(
      facsimile.tableBlock.bottom + 1,
    );
  }

  // Highlights and blocks read the same bbox1000 numbers, so they coincide.
  const titleBlock = facsimile.blocks[0]!.rect;
  for (const [state, block] of [
    ["verified", titleBlock],
    ["review", facsimile.tableBlock],
  ] as const) {
    const highlight = facsimile.highlights.find((item) => item.state === state);
    expect(highlight, `${state} highlight exists`).toBeDefined();
    for (const edge of ["top", "right", "bottom", "left"] as const) {
      expect(
        Math.abs(highlight!.rect[edge] - block[edge]),
        `${state} highlight ${edge} matches its block`,
      ).toBeLessThanOrEqual(1);
    }
  }

  // The exemption is the facsimile only; the readable hero text keeps 12px.
  for (const selector of [
    ".tv-facing-meta span",
    ".tv-facing-caption",
    ".tv-hero-comp-tag",
    ".tv-hero-comp-row td",
  ]) {
    const sizes = await page
      .locator(selector)
      .evaluateAll((elements) =>
        elements.map((element) => Number.parseFloat(getComputedStyle(element).fontSize)),
      );
    expect(sizes.length, `${selector} elements`).toBeGreaterThan(0);
    for (const size of sizes) {
      expect(size, `${selector} keeps the 12px floor`).toBeGreaterThanOrEqual(12);
    }
  }
});

test("integrity status register code exposes every character", async ({
  page,
}, testInfo) => {
  await setLocaleCookie(page.context(), testInfo, "ko");
  const response = await page.goto(integrityPath, { waitUntil: "networkidle" });
  expect(response?.status()).toBeLessThan(400);
  await expect(page.locator("html")).toHaveAttribute("lang", langPattern("ko"));
  await page.evaluate(() => document.fonts.ready);

  const code = page
    .locator(".app-frame .integrity-status-register code")
    .filter({ hasText: /^authority_verified$/ });
  await expect(code).toHaveCount(1);

  const initialViewport = page.viewportSize();
  expect(initialViewport, "project defines a viewport").not.toBeNull();
  const viewportHeight = initialViewport!.height;

  for (const width of [1440, 768, 390, 360]) {
    await page.setViewportSize({ width, height: viewportHeight });
    await page.evaluate(() => document.fonts.ready);

    await expect(code, `code visible at ${width}px`).toBeVisible();
    await expect(code, `full text at ${width}px`).toHaveText(
      "authority_verified",
    );

    const metrics = await code.evaluate((element) => {
      const isClipped = (node: Element) =>
        node.scrollWidth > node.clientWidth + 1 ||
        node.scrollHeight > node.clientHeight + 1;

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

    expect(
      metrics.controlClipped,
      `negative control: 64px nowrap ellipsis span is clipped at ${width}px`,
    ).toBe(true);
    expect(metrics.text, `measured text at ${width}px`).toBe(
      "authority_verified",
    );
    expect(
      metrics.clientWidth,
      `code has layout width at ${width}px`,
    ).toBeGreaterThan(0);
    expect(
      metrics.scrollWidth,
      `no horizontal clipping at ${width}px`,
    ).toBeLessThanOrEqual(metrics.clientWidth + 1);
    expect(
      metrics.scrollHeight,
      `no vertical clipping at ${width}px`,
    ).toBeLessThanOrEqual(metrics.clientHeight + 1);
    expect(metrics.clipped, `code is not clipped at ${width}px`).toBe(false);
  }
});

// The canvas SVG stretches with preserveAspectRatio="none" while the nodes are
// opaque, so an arrowhead that drifts out of its inter-node gap disappears.
test("security architecture diagram keeps every arrowhead visible in its gap", async ({
  page,
}, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
  await setLocaleCookie(page.context(), testInfo, "en");
  const response = await page.goto("/security", { waitUntil: "networkidle" });
  expect(response?.status()).toBeLessThan(400);
  await expect(page.locator("html")).toHaveAttribute("lang", langPattern("en"));

  const canvas = page.locator(".tv-architecture-diagram .tv-diagram-canvas").first();
  const arrowheads = canvas.locator("svg > path.tv-diagram-arrowhead");

  const initialViewport = page.viewportSize();
  expect(initialViewport, "project defines a viewport").not.toBeNull();
  const viewportHeight = initialViewport!.height;

  for (const width of [1440, 1280, 1024]) {
    await page.setViewportSize({ width, height: viewportHeight });
    await page.evaluate(() => document.fonts.ready);
    await expect(canvas, `diagram canvas at ${width}px`).toBeVisible();
    await expect(arrowheads, `three arrowheads at ${width}px`).toHaveCount(3);
    await canvas.evaluate((element) => element.scrollIntoView({ block: "center" }));

    const results = await canvas.evaluate((element) => {
      const nodes = Array.from(element.querySelectorAll(":scope > div")).map((node) =>
        node.getBoundingClientRect(),
      );
      const heads = Array.from(
        element.querySelectorAll<SVGPathElement>("svg > path.tv-diagram-arrowhead"),
      );
      return heads.map((head) => {
        const rect = head.getBoundingClientRect();
        const style = getComputedStyle(head);
        // The head is a right-pointing triangle; its centroid is a third of
        // the way in from the base, so it is painted fill, not empty bbox.
        const probe = { x: rect.left + rect.width / 3, y: rect.top + rect.height / 2 };
        const hit = document.elementFromPoint(probe.x, probe.y);
        const overlapsNode = nodes.some(
          (node) =>
            rect.left < node.right &&
            rect.right > node.left &&
            rect.top < node.bottom &&
            rect.bottom > node.top,
        );
        const gap = nodes.reduce(
          (found, node, index) => {
            const next = nodes[index + 1];
            return next && node.right <= rect.left && rect.right <= next.left ? index + 1 : found;
          },
          0,
        );
        return {
          arrow: head.dataset.arrow,
          width: rect.width,
          height: rect.height,
          visible: style.visibility !== "hidden" && style.display !== "none",
          hitSelf: hit === head,
          overlapsNode,
          gap,
        };
      });
    });

    expect(results.map((result) => result.gap), `arrowheads sit in gaps 1-3 at ${width}px`).toEqual([
      1, 2, 3,
    ]);
    for (const result of results) {
      const label = `arrowhead ${result.arrow} at ${width}px`;
      expect(result.visible, `${label} is rendered`).toBe(true);
      expect(result.width, `${label} has width`).toBeGreaterThan(0);
      expect(result.height, `${label} has height`).toBeGreaterThan(0);
      expect(result.overlapsNode, `${label} does not overlap a node`).toBe(false);
      expect(result.hitSelf, `${label} is the topmost element at its centroid`).toBe(true);
    }
  }
});
