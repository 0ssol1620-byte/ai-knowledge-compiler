import { expect, test } from "@playwright/test";

test.beforeEach(async ({ context }) => {
  await context.addCookies([
    { name: "akc_locale", value: "en", url: "http://127.0.0.1:3000" },
  ]);
});

test("TAVONEL home presents the complete twelve-scene compiler story", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Turn documents and connected systems",
  );
  await expect(page.locator("main [data-scene]")).toHaveCount(12);
  for (const scene of [
    "01-hero", "02-read", "03-structure", "04-provenance", "05-use",
    "06-product-proof", "07-emits", "08-compile-first", "09-solutions",
    "10-integrations", "11-security", "12-pricing",
  ]) {
    await expect(page.locator(`[data-scene="${scene}"]`)).toBeAttached();
  }
  await expect(page.getByRole("link", { name: /Compile your own files/ }).first()).toHaveAttribute("href", "/signup");
});

test("reduced motion keeps the public proof controls operable", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const proof = page.locator('[data-scene="06-product-proof"]');
  await proof.scrollIntoViewIfNeeded();
  await proof.getByRole("tab", { name: "Original" }).click();
  await expect(proof.getByRole("tab", { name: "Original" })).toHaveAttribute("aria-selected", "true");
});

test("Review is a first-class route and strips unrelated query context", async ({ page }) => {
  await page.goto("/review?document=unselected&token=secret&redirect_uri=https%3A%2F%2Fevil.example");
  await expect(page).toHaveURL(/\/review\?/);
  await expect(page.getByRole("heading", { name: "Review" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("secret");
  await expect(page.locator("body")).not.toContainText("evil.example");
});

test("World exposes the six canonical lenses", async ({ page }) => {
  await page.goto("/knowledge-bases");
  await expect(page.getByRole("heading", { name: "Knowledge Studio" })).toBeVisible();
  const views = page.getByRole("navigation", { name: /views/i });
  for (const lens of ["Graph", "Directory", "Ontology", "Evidence", "Versions", "Files"]) {
    await expect(views.getByRole("button", { name: lens })).toBeVisible();
  }
});

test("Sources preserves manifest truth and cannot start without signed preflight", async ({ page }) => {
  await page.goto("/intake");
  await expect(page.getByRole("heading", { name: "Bring a document collection in without losing its structure" })).toBeVisible();
  await expect
    .poll(async () => {
      await page.locator("[data-collection-file-input]").setInputFiles({
        name: "research-note.md",
        mimeType: "text/markdown",
        buffer: Buffer.from("source-linked note"),
      });
      return page.getByText("research-note.md").count();
    })
    .toBeGreaterThan(0);
  await expect(page.getByText("research-note.md")).toBeVisible();
  await expect(page.getByText("Sampled P50").locator("..")).toContainText("Not measured");
  await page.getByRole("button", { name: "Prepare server preflight" }).click();
  await expect(page.getByText("Local preflight request is ready")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start processing" })).toBeDisabled();
});

test("Processing uses the eight-stage document contract without pretending it is live", async ({ page }) => {
  await page.goto("/documents/sample-dart/processing");
  await expect(page.getByText("Demo workspace · No documents are processed and no credits are used.")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Processing progress" }).locator(".stage-item"),
  ).toHaveCount(8);
  await expect(page.locator("body")).not.toContainText(/paddle|mineru/i);
});

test("Security and legal surfaces keep honest evidence boundaries", async ({ page }) => {
  await page.goto("/security");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator("main")).not.toContainText(/SOC 2 certified/i);
  await page.goto("/legal/privacy");
  await expect(page.getByText(/final public policy text requires legal approval/i)).toBeVisible();
  await expect(page.getByRole("link", { name: /terms/i })).toHaveAttribute("href", "/legal/terms");
});

test("unapproved customer, benchmark, and research proof stays unpublished", async ({ page }) => {
  for (const route of ["/customers", "/benchmarks", "/research/experiments"]) {
    const response = await page.goto(route, { waitUntil: "domcontentloaded" });
    expect(response?.status(), route).toBe(404);
  }
});

test("signup keeps the secure email and Google entry contract", async ({ page }) => {
  await page.goto("/signup");
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
  await expect(page.getByText("or continue with email")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create workspace" })).toBeEnabled();
});
