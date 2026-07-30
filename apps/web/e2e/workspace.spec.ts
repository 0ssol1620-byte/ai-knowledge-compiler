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

test("HTML uses a per-request script nonce and hardened response headers", async ({
  page,
}) => {
  const response = await page.goto("/");
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
  await page.goto("/");
  await expect(
    page.getByRole("heading", {
      name: "Your AI is only as good as the knowledge it receives.",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Page → Structure → Evidence → Knowledge → Intelligence"),
  ).toBeVisible();
  await expect(
    page.getByText("Every output returns to its source."),
  ).toBeVisible();
  await expect(
    page.getByText(
      "AI does not need more information. It needs better knowledge.",
    ),
  ).toBeVisible();
  await expect(page.getByLabel("Primary navigation")).toHaveCount(1);
  await expect(
    page.getByText("Structara is a working name pending brand clearance."),
  ).toBeVisible();
});

test("marketing and product retain a clear round trip", async ({
  page,
  isMobile,
}) => {
  await page.goto("/");
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
  await page.goto("/");
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
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      `${path} overflows the viewport`,
    ).toBe(true);
  }
});

test("processing workspace exposes real stage counts and source-linked output", async ({
  page,
  isMobile,
}) => {
  await page.goto("/documents/sample-dart/processing");
  await expect(page.getByText("Building knowledge structure")).toHaveCount(1);
  await expect(page.getByText("16 of 18 pages available")).toHaveCount(1);
  await expect(page.getByText("Review queue")).toHaveCount(1);
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
    await page.goto(path);
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
  await page.goto("/");
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
