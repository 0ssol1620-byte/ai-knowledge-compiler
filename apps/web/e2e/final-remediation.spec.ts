import { expect, test } from "@playwright/test";

test("Home hero matches the autonomous collection promise and exposes the six signature semantics", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Don’t organize your files. Compile the knowledge.",
  );
  await expect(
    page.getByText(
      "Drop everything in. Structara turns it into structured, verified, connected knowledge for people and AI.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Compile your collection" }).first(),
  ).toHaveAttribute("href", "/intake");
  await expect(page.locator('[data-signature-asset="A01"]')).toBeVisible();
  await expect(
    page.locator('[data-signature-asset="A02"]').first(),
  ).toBeVisible();
  await expect(
    page.locator('[data-signature-asset="A03"]').first(),
  ).toBeVisible();
  await expect(page.locator('[data-signature-asset="A04"]')).toBeVisible();
  await expect(page.locator('[data-signature-assets~="A05"]')).toBeVisible();
  await expect(page.locator('[data-signature-asset="A06"]')).toBeVisible();
});

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

test("legacy review links enter the Integrity Console without leaking unsafe context", async ({
  page,
}) => {
  await page.goto(
    "/review?project=project-7&token=secret&redirect_uri=https%3A%2F%2Fevil.example",
  );
  await expect(page).toHaveURL(/\/integrity\?project=project-7$/);
  await expect(
    page.getByRole("heading", { name: /Automatic recovery first/ }),
  ).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Review Studio");
  await expect(page.locator("body")).not.toContainText("secret");
  await expect(page.locator("body")).not.toContainText("evil.example");
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

test("Processing Theater uses the six-stage reference contract without pretending it is live", async ({
  page,
}) => {
  await page.goto("/documents/sample-dart/processing");
  await expect(
    page.getByText(
      "Demo workspace · No documents are processed and no credits are used.",
    ),
  ).toBeVisible();
  await expect(page.locator("[data-reference-snapshot]")).toHaveCount(1);
  const stages = page.locator(".stage-track .stage-item");
  await expect(stages).toHaveCount(6);
  await expect(stages).toHaveText([
    /COLLECT/,
    /UNDERSTAND/,
    /VERIFY/,
    /COMPILE/,
    /ARCHITECT/,
    /PACKAGE/,
  ]);
  await expect(page.locator("body")).not.toContainText(/paddle|mineru/i);
});

test("Collection intake preserves manifest truth and cannot start before signed preflight", async ({
  page,
}) => {
  await page.goto("/intake");
  await expect(
    page.getByRole("heading", {
      name: "Bring a document collection in without losing its structure",
    }),
  ).toBeVisible();

  const folderInput = page.locator("[data-collection-folder-input]");
  await expect(folderInput).toHaveAttribute("webkitdirectory", "");
  await expect(
    page.getByText("Up to 5,000 files · 10 GiB per collection"),
  ).toBeVisible();
  await page.locator("[data-collection-file-input]").setInputFiles([
    {
      name: "research-note.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("source-linked note"),
    },
  ]);

  await expect(page.getByText("research-note.md")).toBeVisible();
  await expect(page.getByText("Sampled P50").locator("..")).toContainText(
    "Not measured",
  );
  await page.getByRole("button", { name: "Pause intake" }).click();
  await expect(
    page.getByRole("button", { name: "Prepare server preflight" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Resume intake" }).click();
  await page.getByRole("button", { name: "Prepare server preflight" }).click();
  await expect(
    page.getByText("Local preflight request is ready"),
  ).toBeVisible();
  await expect(page.getByText(/No API call, upload, job/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start processing" }),
  ).toBeDisabled();
  await expect(page.locator("body")).not.toContainText(/paddle|mineru/i);
});

test("Integrity Console leads with automatic history and keeps override secondary", async ({
  page,
}) => {
  await page.goto("/integrity?reference=1");
  await expect(
    page.getByRole("heading", {
      name: /Automatic recovery first/,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Reference state · no live workspace connected"),
  ).toBeVisible();

  for (const status of [
    "verified",
    "authority_verified",
    "auto_repaired",
    "reprocessing",
    "warning",
    "unresolved",
    "quarantined",
  ]) {
    await expect(page.getByText(status).first()).toBeVisible();
  }

  await page.getByRole("button", { name: /Continued table row/ }).click();
  await expect(page.getByText("Overlap recovery")).toBeVisible();
  const decisionPanel = page.locator(".integrity-override");
  await decisionPanel.getByText("Optional customer decision").click();
  await expect(
    decisionPanel.getByRole("combobox", { name: "Decision" }),
  ).toBeDisabled();
  await expect(
    decisionPanel.getByText(
      "A live open finding and collection write permission are required.",
    ),
  ).toBeVisible();
  await expect(
    decisionPanel.getByRole("option", { name: "Optional override" }),
  ).toHaveCount(0);
  await expect(
    decisionPanel.getByRole("button", { name: "Record audited decision" }),
  ).toBeDisabled();
  await expect(page.locator("body")).not.toContainText(/paddle|mineru/i);
});

test("Public benchmark route mounts the fail-closed evidence lab", async ({
  page,
}) => {
  await page.goto("/benchmarks");
  await expect(
    page.getByRole("heading", { name: "Benchmark Lab" }),
  ).toBeVisible();
  await expect(page.getByText("Public metrics locked")).toBeVisible();
  await expect(
    page.getByText("No performance metrics are ready for publication."),
  ).toBeVisible();
  await expect(
    page.locator('.benchmark-table-frame tbody td:has-text("Not measured")'),
  ).toHaveCount(24);
});
