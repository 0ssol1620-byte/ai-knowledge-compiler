import { expect, test } from "@playwright/test";

test("SEC proof preserves the actual filing fact through every transformation", async ({
  page,
}) => {
  await page.goto("/demo/sec");
  await expect(
    page.getByRole("heading", { name: /Apple 2025 Form 10-K/ }),
  ).toBeVisible();
  await expect(page.getByText("0000320193-25-000079").first()).toBeVisible();

  const total2025 = page.getByRole("button", { name: "$416,161" });
  await total2025.click();
  await expect(total2025).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("$416,161").last()).toBeVisible();
  await expect(
    page.getByText("Form 10-K page 22", { exact: false }).first(),
  ).toBeVisible();

  await page.getByRole("button", { name: "Markdown" }).click();
  await expect(page.getByText("apple-2025-revenue-evidence.md")).toBeVisible();
  await expect(page.locator("pre")).toContainText("Total net sales");

  await page.getByRole("button", { name: "Vault" }).click();
  await expect(
    page.getByRole("heading", { name: "FY2025 total net sales" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Graph" }).click();
  await expect(
    page.getByRole("table", { name: "Accessible relation list" }),
  ).toBeVisible();
  await expect(page.getByRole("cell", { name: "filed_by" })).toBeVisible();

  await page.getByRole("button", { name: "Proof" }).click();
  await expect(page.getByText("Proof receipt")).toBeVisible();
  await expect(
    page.getByText(/Pending controlled archive-byte retrieval/),
  ).toBeVisible();
});

test("Review Studio performs audited decisions instead of exposing a static mock", async ({
  page,
}) => {
  await page.goto("/review");
  await expect(
    page.getByRole("heading", { name: "Review Studio" }),
  ).toBeVisible();
  await expect(page.getByText("Interactive sample")).toBeVisible();
  const accept = page.getByRole("button", { name: "Accept replacement" });
  await expect(accept).toBeEnabled();
  await accept.click();
  await expect(page.getByText("LATEST AUDIT EVENT")).toBeVisible();
  await expect(page.getByText(/Manual replacement accepted/)).toBeVisible();

  await page.getByRole("button", { name: "Completion summary" }).click();
  await expect(
    page.getByRole("region", { name: "Review completion summary" }),
  ).toBeVisible();
});

test("Knowledge Studio filters, changes perspective, and exposes accessible relations", async ({
  page,
}) => {
  await page.goto("/knowledge-bases");
  await expect(
    page.getByRole("heading", { name: "Knowledge Studio" }),
  ).toBeVisible();
  const search = page.getByRole("textbox", { name: "Search knowledge" });
  await search.fill("revenue");
  await expect(page.getByText(/1 matching notes/)).toBeVisible();

  await page
    .locator(".knowledge-explorer")
    .getByRole("button", { name: "Evidence" })
    .click();
  await expect(page.getByText(/Evidence perspective/)).toBeVisible();

  await page.getByRole("button", { name: "Relations" }).click();
  await expect(
    page.getByRole("table", {
      name: "Relations with adjacent source evidence",
    }),
  ).toBeVisible();
});

test("Projects operates independently with filters, grid view, and bulk actions", async ({
  page,
}) => {
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
  await page
    .getByRole("textbox", { name: "Search projects" })
    .fill("evidence fidelity");
  await expect(page.getByRole("table")).toContainText(
    "RAG evidence fidelity study",
  );

  const rowSelect = page.getByRole("button", {
    name: "Select RAG evidence fidelity study",
  });
  await rowSelect.click();
  await expect(page.getByText("1 selected")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Copy project IDs" }),
  ).toBeEnabled();

  await page.getByRole("button", { name: "Grid" }).click();
  await expect(page.locator(".projects-card-grid article")).toHaveCount(1);
  await page.getByRole("button", { name: "Clear selection" }).click();
  await expect(page.getByText("1 selected")).toHaveCount(0);
});

test("Command Palette supports search, keyboard navigation, escape, and focus return", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name === "mobile",
    "Desktop command surface is tested separately from mobile navigation.",
  );
  await page.goto("/projects");
  const trigger = page.getByRole("button", {
    name: /Search projects, documents, or evidence/,
  });
  await trigger.focus();
  await trigger.click();

  const search = page.getByRole("combobox", {
    name: "Search workspace commands",
  });
  await expect(search).toBeFocused();
  await search.fill("knowledge");
  await expect(
    page.getByRole("option", { name: /Explore knowledge/ }),
  ).toBeVisible();
  await search.press("ArrowDown");
  await search.press("Home");
  await search.press("Escape");
  await expect(
    page.getByRole("dialog", { name: "Workspace command menu" }),
  ).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("Legal routes are independent and never claim unapproved legal effect", async ({
  page,
}) => {
  await page.goto("/legal/privacy");
  await expect(
    page.getByText("Draft · counsel approval required"),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /Terms/ })).toHaveAttribute(
    "href",
    "/legal/terms",
  );
  await expect(
    page.getByRole("link", { name: /Subprocessors/ }),
  ).toHaveAttribute("href", "/legal/subprocessors");
  await expect(
    page.getByRole("link", { name: /Third-party notices/ }),
  ).toHaveAttribute("href", "/legal/third-party-notices");
});

test("Security architecture exposes real trust boundaries and honest evidence status", async ({
  page,
}) => {
  await page.goto("/security");
  await expect(
    page.getByRole("heading", {
      name: /Customer content crosses explicit boundaries/,
    }),
  ).toBeVisible();
  await expect(page.getByText("CPU parser sandbox")).toBeVisible();
  await expect(page.getByText("GPU worker boundary")).toBeVisible();
  await expect(page.getByText("External Precision provider")).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Threat-to-control evidence register" }),
  ).toBeVisible();
  await expect(
    page.getByText("Production evidence required").first(),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Accessible trust-boundary sequence" }),
  ).toBeVisible();
});
