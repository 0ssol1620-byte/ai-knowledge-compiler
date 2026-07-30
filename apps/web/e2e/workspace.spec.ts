import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

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
  expect(
    await page.locator("script").evaluateAll((scripts) =>
      scripts.every((script) => {
        const executable =
          Boolean(script.getAttribute("src")) ||
          Boolean(script.textContent?.trim());
        return !executable || Boolean((script as HTMLScriptElement).nonce);
      }),
    ),
  ).toBe(true);
});

test("dashboard exposes evidence-first project workflow", async ({ page }) => {
  await page.goto("/home");
  await expect(
    page.getByRole("heading", { name: "Workspace overview" }),
  ).toBeVisible();
  await expect(page.getByText("Priority queue", { exact: true })).toBeVisible();
  await expect(page.getByText("Processing now", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("table").getByRole("columnheader", { name: "Owner" }),
  ).toBeVisible();
});

test("marketing and dashboard preserve a visible round-trip", async ({
  page,
  isMobile,
}) => {
  await page.goto("/");
  if (isMobile) {
    await page
      .getByRole("banner")
      .getByRole("link", { name: "Start compiling", exact: true })
      .click();
  } else {
    await page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Dashboard", exact: true })
      .click();
  }
  await expect(page).toHaveURL(/\/home$/);
  await page
    .getByRole("link", { name: "Product site", exact: true })
    .first()
    .click();
  await expect(page).toHaveURL(/\/$/);
});

test("marketing page leads with the enterprise knowledge compiler promise", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", {
      name: "Compile the evidence. Keep the source.",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Start with a document" }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Document pages becoming source-grounded knowledge"),
  ).toBeVisible();
  await expect(page.getByLabel("Primary navigation")).toHaveCount(1);
});

test("processing workspace keeps source and result linked", async ({
  page,
  isMobile,
}) => {
  await page.goto("/workspace");
  await expect(
    page.getByRole("heading", { name: "evidence-grounded-rag-evaluation.pdf" }),
  ).toBeVisible();
  await expect(page.getByText("Demo snapshot", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Live", { exact: true })).toHaveCount(0);
  if (isMobile) {
    await page
      .getByRole("navigation", { name: "Mobile processing views" })
      .getByRole("button", { name: "Source" })
      .click();
  }
  await expect(page.getByLabel("Source document")).toBeVisible();
  await page
    .getByRole("button", {
      name: "paragraph block 3, evidence 1 on page 8",
    })
    .click();
  if (isMobile) {
    await expect(page.getByLabel("Markdown output")).toBeVisible();
  }
  await page
    .getByLabel("Markdown output")
    .getByRole("button", { name: "Link paragraph block 3 to source" })
    .click();
  if (isMobile) {
    await page
      .getByRole("navigation", { name: "Mobile processing views" })
      .getByRole("button", { name: "Source" })
      .click();
  }
  await expect(
    page.getByRole("button", {
      name: "paragraph block 3, evidence 1 on page 8",
    }),
  ).toHaveClass(/active/);
});

test("estimate shows a maximum before processing", async ({ page }) => {
  await page.goto("/workspace?estimate=1");
  await expect(
    page.getByRole("heading", {
      name: "Review the estimate before processing",
    }),
  ).toBeVisible();
  await expect(page.getByText("263–318")).toBeVisible();
  await expect(page.getByText("Not used")).toBeVisible();
  await page.getByRole("button", { name: "Start processing" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Review the estimate before processing",
    }),
  ).not.toBeVisible();
});

test("mobile workspace uses tabs without horizontal overflow", async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, "mobile-only assertion");
  await page.goto("/workspace");
  await expect(
    page.getByRole("navigation", { name: "Mobile processing views" }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Mobile processing views" })
    .getByRole("button", { name: "Source" })
    .click();
  await expect(page.getByLabel("Source document")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
});

test("reduced motion removes nonessential transitions and animations", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/workspace");
  const motion = await page.evaluate(() => {
    const elements = Array.from(document.querySelectorAll<HTMLElement>("*"));
    return elements
      .map((element) => {
        const style = getComputedStyle(element);
        return {
          animation: parseFloat(style.animationDuration || "0"),
          transition: style.transitionDuration
            .split(",")
            .some((value) => parseFloat(value) > 0.01),
        };
      })
      .filter((value) => value.animation > 0.01 || value.transition);
  });
  expect(motion).toEqual([]);
});

test("page rail and source viewer support keyboard-first inspection", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "desktop workspace exposes all three inspection panes");
  await page.goto("/workspace");

  const pageSearch = page.getByRole("searchbox", { name: "Search pages" });
  await pageSearch.fill("Page 14");
  await expect(page.getByRole("button", { name: /^Page 14,/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Page 8,/ })).toHaveCount(0);
  await pageSearch.fill("");

  await page.getByRole("button", { name: /^Page filters/ }).click();
  await page
    .getByRole("combobox", { name: "Quality filter" })
    .selectOption("review");
  await expect(page.getByText("2 / 18 pages")).toBeVisible();
  await expect(page.getByRole("button", { name: /^Page 8,/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Page 14,/ })).toBeVisible();
  await page.getByRole("button", { name: "Reset filters" }).click();

  const pageEight = page.getByRole("button", { name: /^Page 8,/ });
  const pageNine = page.getByRole("button", { name: /^Page 9,/ });
  await pageEight.focus();
  await pageEight.press("ArrowDown");
  await expect(pageNine).toBeFocused();
  await pageNine.press("Enter");
  await expect(pageNine).toHaveAttribute("aria-current", "page");

  const rotate = page.getByRole("button", {
    name: "Rotate page, currently 0 degrees",
  });
  await rotate.click();
  await expect(page.locator(".paper-wrap")).toHaveCSS(
    "transform",
    /matrix\(0, 1, -1, 0,/,
  );

  const rawText = page.getByRole("button", { name: "Source text layer" });
  await rawText.click();
  await expect(rawText).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".source-text-layer")).toBeVisible();

  const sourcePanel = page.locator(".source-panel");
  await sourcePanel.evaluate((element) => {
    Object.defineProperty(element, "requestFullscreen", {
      configurable: true,
      value: undefined,
    });
  });
  await page.getByRole("button", { name: "Full screen", exact: true }).click();
  await expect(sourcePanel).toHaveClass(/source-panel-fullscreen/);
  await page.keyboard.press("Escape");
  await expect(sourcePanel).not.toHaveClass(/source-panel-fullscreen/);
});

test("dialogs trap focus, close with Escape, and restore the trigger", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "one browser profile is enough for focus semantics");
  await page.goto("/home");
  const trigger = page
    .getByRole("button", { name: "New project", exact: true })
    .first();
  const dialog = page.getByRole("dialog", { name: "Create project" });
  await expect(async () => {
    await trigger.click();
    await expect(dialog).toBeVisible({ timeout: 1_500 });
  }).toPass();
  const nameInput = dialog.getByRole("textbox", { name: "Project name" });
  await expect(nameInput).toBeFocused();

  const submit = dialog.getByRole("button", {
    name: "Create project",
  });
  const close = dialog.getByRole("button", { name: "Close dialog" });
  await submit.focus();
  await submit.press("Tab");
  await expect(close).toBeFocused();
  await close.press("Shift+Tab");
  await expect(submit).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("product shell exposes keyboard command navigation", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "desktop shell owns the global command palette");
  await page.goto("/home");
  await page.keyboard.press("Control+K");
  const palette = page.getByRole("dialog", { name: "Command menu" });
  await expect(palette).toBeVisible();
  await expect(
    palette.getByRole("searchbox", { name: "Search commands" }),
  ).toBeFocused();
  await expect(
    palette.getByRole("link", { name: /Open Review Studio/ }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(palette).toHaveCount(0);
});

test("masterplan product routes remain honest and overflow-free", async ({
  page,
}) => {
  for (const path of [
    "/home",
    "/quick-convert",
    "/knowledge-bases",
    "/benchmarks",
    "/api-workflows",
    "/review",
    "/usage",
  ]) {
    await page.goto(path);
    await expect(
      page.getByText("Demo workspace", { exact: false }).first(),
    ).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    expect(overflow, `${path} overflows the viewport`).toBe(false);
  }
});

test("primary demo surfaces have no automated WCAG A or AA violations", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "desktop scan covers the complete workspace surface");
  for (const path of [
    "/",
    "/home",
    "/workspace",
    "/review",
    "/knowledge-bases",
  ]) {
    await page.goto(path);
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

test("dark product mode preserves contrast and calm workspace surfaces", async ({
  page,
  isMobile,
}) => {
  test.skip(
    isMobile,
    "desktop scan covers the complete dark workspace surface",
  );
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/home");
  await expect(
    page.getByRole("heading", { name: "Workspace overview" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => window.matchMedia("(prefers-color-scheme: dark)").matches,
    ),
  ).toBe(true);
  await expect(page.locator(".operations-board")).toHaveCSS(
    "background-color",
    "rgb(20, 25, 32)",
  );
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations,
    results.violations
      .map((violation) => `${violation.id} (${violation.nodes.length})`)
      .join(", "),
  ).toEqual([]);
});
