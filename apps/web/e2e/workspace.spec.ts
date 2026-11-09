import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const publicRoutes = [
  "/",
  "/product",
  "/product/convert",
  "/product/verify",
  "/product/knowledge",
  "/product/graph",
  "/product/connect",
  "/solutions/individuals",
  "/solutions/research",
  "/solutions/teams",
  "/solutions/developers",
  "/solutions/enterprise",
  "/demo",
  "/demo/dart",
  "/demo/sec",
  "/demo/research-paper",
  "/demo/course-material",
  "/benchmarks",
  "/research",
  "/security",
  "/pricing",
  "/customers",
  "/developers",
  "/developers/docs",
  "/developers/api",
  "/developers/sdk",
  "/developers/changelog",
  "/company/about",
  "/company/principles",
  "/company/careers",
  "/company/contact",
  "/legal/privacy",
  "/legal/terms",
  "/legal/subprocessors",
  "/legal/third-party-notices",
] as const;

const appRoutes = [
  "/app/home",
  "/app/projects",
  "/app/projects/sample/overview",
  "/app/projects/sample/documents",
  "/app/projects/sample/knowledge",
  "/app/projects/sample/graph",
  "/app/projects/sample/exports",
  "/documents/sample-dart/processing",
  "/documents/sample-dart/review",
  "/documents/sample-dart/markdown",
  "/documents/sample-dart/sources",
  "/documents/sample-dart/versions",
  "/app/jobs",
  "/app/knowledge-bases",
  "/app/benchmarks",
  "/app/recipes",
  "/app/exports",
  "/app/api",
  "/app/usage",
  "/app/billing",
  "/app/settings/members",
  "/app/settings/security",
  "/app/settings/retention",
  "/app/settings/integrations",
  "/app/settings/notifications",
  "/app/admin/jobs",
  "/app/admin/workers",
  "/app/admin/tenants",
  "/app/admin/costs",
  "/app/admin/incidents",
  "/app/admin/audit",
] as const;

// This spec verifies the English surface contracts. Locale switching and the
// Korean product path are covered independently in locale.spec.ts.
test.beforeEach(async ({ context }) => {
  await context.addCookies([
    {
      name: "akc_locale",
      value: "en",
      url: "http://127.0.0.1:3000",
      sameSite: "Lax",
    },
  ]);
});

test("HTML uses a per-request script nonce and hardened response headers", async ({
  page,
}) => {
  const response = await page.goto("/", { waitUntil: "domcontentloaded" });
  expect(response).not.toBeNull();
  const headers = response!.headers();
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["x-frame-options"]).toBe("DENY");
  const policy = headers["content-security-policy"] ?? "";
  const scriptDirective =
    policy
      .split(";")
      .map((value) => value.trim())
      .find((value) => value.startsWith("script-src")) ?? "";
  expect(scriptDirective).toContain("'nonce-");
  expect(scriptDirective).not.toContain("'unsafe-inline'");
});

test("brand homepage expresses the full source-to-intelligence thesis", async ({
  page,
}) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  // The W2 facing-pages homepage replaced the earlier long-copy landing: the
  // round-trip promise moved into the h1, the four chapters carry
  // structure → evidence → knowledge → portability, and the provenance
  // disclaimers stay on the surface. Each chapter renders twice (desktop and
  // compact variants), so visibility is asserted on the first match.
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Every output returns",
  );
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "to its source.",
  );
  await expect(page.getByText("It sees more than text.").first()).toBeVisible();
  await expect(
    page.getByText("Documents become a knowledge system.").first(),
  ).toBeVisible();
  await expect(
    page.getByText("Compile once. Use it everywhere.").first(),
  ).toBeVisible();
  await expect(page.getByLabel("Primary navigation")).toHaveCount(1);
  await expect(
    page.getByText("TAVONEL is a working name pending brand clearance."),
  ).toBeVisible();
});

test("product marketing uses real product evidence and deterministic diagrams", async ({
  page,
}) => {
  await page.goto("/product", { waitUntil: "domcontentloaded" });
  const evidence = page.locator(".tv-page-product-evidence");
  await expect(evidence).toBeVisible();
  await expect(evidence.getByText("Actual product")).toBeVisible();
  await expect(evidence.locator("img")).toHaveJSProperty("complete", true);
  expect(
    await evidence.locator("img").evaluate((image: HTMLImageElement) => {
      return image.naturalWidth;
    }),
  ).toBeGreaterThan(0);
  await expect(
    page.getByRole("heading", { name: "Source-to-Knowledge Compiler" }),
  ).toBeVisible();
  await expect(
    page.locator(".tv-diagram-equivalent").getByRole("listitem"),
  ).toHaveCount(4);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("marketing and product retain a clear round trip", async ({
  page,
  isMobile,
}) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  if (isMobile) {
    await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("link", { name: "Workspace", exact: true }).click();
  } else {
    await expect(
      page.getByRole("link", { name: "Sign in", exact: true }),
    ).toHaveAttribute("href", "/login");
    await page.goto("/app/home", { waitUntil: "domcontentloaded" });
  }
  await expect(
    page.getByRole("heading", { name: "Today in your workspace" }),
  ).toBeVisible();
  await expect(page.locator(".product-back-link")).toHaveAttribute("href", "/");
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/$/);
});

test("every public route renders its own page without overflow", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "the full manifest is covered once on desktop");
  test.setTimeout(180_000);
  const titles = new Set<string>();
  for (const path of publicRoutes) {
    const response = await page.goto(path, { waitUntil: "domcontentloaded" });
    expect(response?.ok(), `${path} did not return a successful response`).toBe(
      true,
    );
    await expect(page.locator("main")).toBeVisible();
    await expect(page.locator("main h1")).toHaveCount(1);
    titles.add(await page.title());
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      `${path} overflows the viewport`,
    ).toBe(true);
  }
  expect(titles.size).toBe(publicRoutes.length);
});

test("every application route renders the masterplan information architecture", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "the full manifest is covered once on desktop");
  test.setTimeout(180_000);
  for (const path of appRoutes) {
    const response = await page.goto(path, { waitUntil: "domcontentloaded" });
    expect(response?.ok(), `${path} did not return a successful response`).toBe(
      true,
    );
    await expect(page.locator("main")).toBeVisible();
    // Scoped to main so the count is of the page's own DOM. An unscoped
    // locator('h1') reported 2 on a cold dev server twice, held for the full
    // retry window; the same 31 routes were then scanned warm, twice, and
    // every one had exactly one h1, with none outside main and no shadow root
    // present. The extra node was never captured, so the cause is unconfirmed
    // — but what this test means is "the page renders one h1", and that is
    // what it now asks.
    await expect(page.locator("main h1")).toHaveCount(1);
    if (path.startsWith("/app/")) {
      const headerAction = page.locator("[data-app-header-action]");
      await expect(headerAction).toHaveCount(1);
      const actionHref = await headerAction.getAttribute("href");
      expect(actionHref, `${path} header action has no destination`).toMatch(
        /^\//,
      );
      expect(
        actionHref,
        `${path} header action loops to the same page`,
      ).not.toBe(path);
      const staticControls = page.locator("[data-sample-static-control]");
      const staticControlCount = await staticControls.count();
      for (let index = 0; index < staticControlCount; index += 1) {
        await expect(staticControls.nth(index)).toBeDisabled();
      }
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      `${path} overflows the viewport`,
    ).toBe(true);
  }
});

test("quick convert exposes one bounded and consent-aware upload contract", async ({
  page,
}) => {
  // The merged locale system renders Korean until a locale cookie exists
  // (DEFAULT_STRUCTARA_LOCALE is "ko"); this contract's copy is asserted in
  // English, so pin the cookie instead of depending on the product default.
  // locale.spec covers cookie-driven switching itself.
  await page.context().addCookies([
    {
      name: "akc_locale",
      value: "en",
      url: "http://127.0.0.1:3000",
      sameSite: "Lax",
    },
  ]);
  await page.goto("/quick-convert", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Private route first")).toBeVisible();
  await expect(
    page.getByText("External providers require explicit workspace consent"),
  ).toBeVisible();
  await expect(page.getByText(/up to 50 MB each/i)).toBeVisible();
  await expect(page.getByText(/folder here/i)).toHaveCount(0);
});

test("DART proof marks the exact revenue cell without a detached overlay", async ({
  page,
}) => {
  await page.goto("/demo/dart", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".tv-source-cell-selected")).toHaveText(
    "4,902,490,901",
  );
  await expect(page.locator(".tv-source-box")).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Verify receipt 20260730000413" }),
  ).toBeVisible();
});

test("demo administration and settings never expose writable-looking controls", async ({
  page,
}) => {
  for (const path of ["/admin", "/settings"] as const) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    const demoControls = page.locator("[data-demo-static-control]");
    expect(
      await demoControls.count(),
      `${path} has no explicit demo controls`,
    ).toBeGreaterThan(0);
    const count = await demoControls.count();
    for (let index = 0; index < count; index += 1) {
      await expect(demoControls.nth(index)).toBeDisabled();
    }
  }
});

test("shell actions and fixed studios expose only operable or explicit gated controls", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.goto("/home", { waitUntil: "domcontentloaded" });
  await expect(
    page.locator('[data-shell-action="notifications"]'),
  ).toHaveAttribute("href", "/notices");
  // G0 §2.2 replaced the static account link with the AccountMenu: the
  // trigger is a button that opens a menu whose entries point at /account,
  // /billing, and sign out — the /settings shortcut no longer exists.
  const accountTrigger = page.locator('[data-shell-action="account"]');
  await expect(accountTrigger).toBeVisible();
  await accountTrigger.click();
  await expect(
    page.getByRole("menuitem", { name: /account/i }),
  ).toHaveAttribute("href", "/account");
  await expect(
    page.getByRole("menuitem", { name: /billing/i }),
  ).toHaveAttribute("href", "/billing");

  for (const path of [
    "/knowledge-bases",
    "/api-workflows",
    "/workspace",
  ] as const) {
    const studioPage = await page.context().newPage();
    await studioPage.goto(path, { waitUntil: "domcontentloaded" });
    const fixedControls = studioPage.locator("[data-sample-static-control]");
    expect(
      await fixedControls.count(),
      `${path} has no explicit fixed controls`,
    ).toBeGreaterThan(0);
    const count = await fixedControls.count();
    for (let index = 0; index < count; index += 1) {
      await expect(fixedControls.nth(index)).toBeDisabled();
    }
    await studioPage.close();
  }

  for (const path of ["/forgot-password", "/sso"] as const) {
    const authPage = await page.context().newPage();
    await authPage.goto(path, { waitUntil: "domcontentloaded" });
    await expect(authPage.locator("[data-auth-external-gate]")).toBeDisabled();
    await authPage.close();
  }
});

test("processing workspace exposes real stage counts and source-linked output", async ({
  page,
  isMobile,
}) => {
  await page.goto("/documents/sample-dart/processing", {
    waitUntil: "domcontentloaded",
  });
  await expect(page.getByText("Building knowledge structure")).toHaveCount(1);
  // Both figures are derived from demoPages and the stage list, not typed in.
  // The old copy said "16 of 18", which matched nothing in the fixture, and the
  // ring beside it showed a hardcoded 68% that §25.7 rejects outright.
  await expect(page.getByText("15 of 18 pages available")).toHaveCount(1);
  await expect(page.getByText("3 of 8 stages finished")).toHaveCount(1);
  await expect(page.locator("body")).not.toContainText("68%");
  // d7a6b30 renamed the drawer's title from "Review queue" to
  // "Integrity findings" when the review surface became the Integrity
  // Console; the drawer is still the queue this test means to pin.
  await expect(page.getByText("Integrity findings")).toHaveCount(1);
  if (isMobile) {
    await page
      .getByRole("navigation", { name: "Mobile processing views" })
      .getByRole("button", { name: "Source" })
      .click();
    await expect(page.getByLabel("Source document")).toBeVisible();
    await page
      .getByRole("navigation", { name: "Mobile processing views" })
      .getByRole("button", { name: "Result" })
      .click();
    await expect(page.getByLabel("Markdown output")).toBeVisible();
  } else {
    await expect(page.getByLabel("Source document")).toBeVisible();
    await expect(page.getByLabel("Markdown output")).toBeVisible();
  }
});

test("auth, onboarding, product, and document surfaces remain usable on mobile", async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, "mobile-only breakpoint coverage");
  for (const path of [
    "/",
    "/product",
    "/signup",
    "/onboarding",
    "/app/home",
    "/app/usage",
    "/documents/sample-dart/processing",
    "/documents/sample-dart/markdown",
  ]) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    await expect(page.locator("main")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      `${path} overflows the mobile viewport`,
    ).toBe(true);
  }
});

test("reduced motion removes travel and nonessential animation", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  // decision.md G-C dropped TIER 1 3D outright, so the layer must not exist at
  // all rather than merely be hidden under reduced motion.
  await expect(page.locator(".tv-webgl-layer")).toHaveCount(0);
  await expect(page.locator("canvas")).toHaveCount(0);
  // §10.4 (pinned by motion.spec) settles reduced motion as attenuation, not
  // removal: durations clamp to a visible 0.09s and loops collapse to one
  // iteration, so "no animated element at all" is the wrong contract. What
  // reduced motion owes the visitor is that nothing travels — no duration may
  // exceed the clamp.
  const maxDuration = await page.evaluate(() =>
    Math.max(
      ...Array.from(document.querySelectorAll<HTMLElement>(".tv-site *")).map(
        (element) => {
          const style = getComputedStyle(element);
          const durations = [
            ...style.animationDuration.split(","),
            ...style.transitionDuration.split(","),
          ]
            .map((value) => Number.parseFloat(value))
            .filter(Number.isFinite);
          return Math.max(0, ...durations);
        },
      ),
      0,
    ),
  );
  expect(
    maxDuration,
    `reduced-motion durations must stay at the §10.4 clamp (0.09s); got ${maxDuration}s`,
  ).toBeLessThanOrEqual(0.09 + 1e-9);
});

test("representative routes have no automated WCAG A or AA violations", async ({
  page,
  isMobile,
}) => {
  test.skip(
    isMobile,
    "desktop scan covers the complete representative surfaces",
  );
  test.setTimeout(180_000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const path of [
    "/",
    "/product/verify",
    "/pricing",
    "/signup",
    "/onboarding",
    "/app/home",
    "/app/benchmarks",
    "/app/settings/security",
    "/documents/sample-dart/processing",
    "/documents/sample-dart/review",
    "/documents/sample-dart/markdown",
  ]) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    await expect(page.locator("main")).toBeVisible();
    // Axe must lay out every below-the-fold section; otherwise Chromium can
    // resolve an offscreen node against a neighbouring intrinsic placeholder.
    await page.addStyleTag({
      content: ".tv-home > section { content-visibility: visible !important; }",
    });
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(
      results.violations,
      `${path}: ${results.violations
        .map((violation) => `${violation.id} (${violation.nodes.length})`)
        .join(", ")}`,
    ).toEqual([]);
  }
});
