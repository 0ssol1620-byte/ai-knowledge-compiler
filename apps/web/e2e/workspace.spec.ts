import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const publicRoutes = [
  "/",
  "/product",
  "/product/compile",
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
  await expect(
    page.getByRole("heading", {
      name: "From scattered documents to one knowledge system.",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Page → Structure → Evidence → Knowledge → Intelligence"),
  ).toBeVisible();
  await expect(page.locator("main > section[data-scene]")).toHaveCount(7);
  await expect(
    page.getByText(
      "Return every important result to the exact source that supports it.",
    ),
  ).toBeVisible();
  await expect(
    page.getByText("Understand. Verify. Connect. Activate."),
  ).toBeVisible();
  await expect(page.getByLabel("Primary navigation")).toHaveCount(1);
  await expect(page.locator("body")).not.toContainText(
    "working name pending brand clearance",
  );
  await expect(
    page.getByRole("heading", {
      name: "Turn your documents into a system of knowledge.",
    }),
  ).toBeVisible();
});

test("product marketing uses real product evidence and deterministic diagrams", async ({
  page,
}) => {
  await page.goto("/product");
  const evidence = page.locator(".st-page-product-evidence");
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
    page.locator(".st-diagram-equivalent").getByRole("listitem"),
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
    await page.goto("/app/home");
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
    await expect(page.locator("h1")).toHaveCount(1);
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
    await expect(page.locator("h1")).toHaveCount(1);
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
  await page.goto("/quick-convert");
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
  await page.goto("/demo/dart");
  await expect(page.locator(".st-source-cell-selected")).toHaveText(
    "4,902,490,901",
  );
  await expect(page.locator(".st-source-box")).toHaveCount(0);
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
  await page.goto("/home");
  await expect(
    page.locator('[data-shell-action="notifications"]'),
  ).toHaveAttribute("href", "/notices");
  await expect(page.locator('[data-shell-action="account"]')).toHaveAttribute(
    "href",
    "/settings",
  );

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

  const integrityPage = await page.context().newPage();
  await integrityPage.goto("/integrity?reference=1", {
    waitUntil: "domcontentloaded",
  });
  await integrityPage.getByText("Optional customer decision").click();
  await expect(
    integrityPage.getByRole("combobox", { name: "Decision" }),
  ).toBeDisabled();
  await expect(
    integrityPage.getByRole("button", { name: "Record audited decision" }),
  ).toBeDisabled();
  await integrityPage.close();

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
  await page.goto("/documents/sample-dart/processing");
  await expect(page.getByText("Building knowledge structure")).toHaveCount(1);
  await expect(page.getByText("16 of 18 pages available")).toHaveCount(1);
  if (isMobile) {
    await page
      .getByRole("navigation", { name: "Mobile processing views" })
      .getByRole("button", { name: "Integrity" })
      .click();
    await expect(page.getByLabel("Integrity findings")).toContainText(
      "2 reference findings retain their source evidence.",
    );
    await expect(
      page.getByRole("link", { name: "Open Integrity Console" }),
    ).toHaveAttribute("href", "/integrity?reference=1");
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
    await expect(
      page.getByRole("link", { name: "Integrity 2" }),
    ).toHaveAttribute("href", "/integrity?reference=1");
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
    "/intake",
    "/integrity",
    "/benchmarks",
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

test("reduced motion removes travel, WebGL, and nonessential animation", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".st-webgl-layer")).toBeHidden();
  const moving = await page.evaluate(() =>
    Array.from(document.querySelectorAll<HTMLElement>(".st-site *"))
      .map((element) => {
        const style = getComputedStyle(element);
        return {
          animation: style.animationDuration
            .split(",")
            .some((value) => parseFloat(value) > 0.01),
          transition: style.transitionDuration
            .split(",")
            .some((value) => parseFloat(value) > 0.01),
        };
      })
      .filter((value) => value.animation || value.transition),
  );
  expect(moving).toEqual([]);
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
    "/intake",
    "/workspace",
    "/integrity",
    "/knowledge-bases",
    "/demo/dart",
    "/demo/sec",
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
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(
      results.violations,
      `${path}: ${results.violations
        .map((violation) => `${violation.id} (${violation.nodes.length})`)
        .join(", ")}`,
    ).toEqual([]);
  }
});
