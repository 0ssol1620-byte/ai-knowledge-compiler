import { expect, test, type Page } from "@playwright/test";

import benchmarkSnapshot from "../src/data/benchmark-public-snapshot.json";

async function expectAppHydrated(page: Page) {
  await expect(page.locator(".app-frame")).toHaveAttribute(
    "data-app-hydrated",
    "true",
    { timeout: 15_000 },
  );
}

async function expectSiteHydrated(page: Page) {
  await expect(page.locator("html")).toHaveAttribute("data-hydrated", "true", {
    timeout: 15_000,
  });
}

// Every assertion in this file targets English product copy. The merged app
// renders Korean until a locale cookie exists (DEFAULT_STRUCTARA_LOCALE is
// "ko"), so pin English for the whole spec — the subject matter here is the
// surfaces' contracts, not locale switching, which locale.spec covers.
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

test("FOLYNTA home matches the compiler promise and the live landing contract", async ({
  page,
}) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  // The hero headline carries manual line breaks (§7.4): two spans joined by
  // <br />, so textContent has no whitespace between the lines.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    /Every output returns\s*to its source\./,
  );
  await expect(page.locator(".tv-hero-comp-lead")).toHaveText(
    "Documents become structured, verified knowledge that people and AI can reuse — with every value traceable to the page it came from.",
  );
  await expect(
    page.locator('.tv-hero-comp-actions a[data-kind="primary"]'),
  ).toHaveAttribute("href", "/signup");

  // The four compiler chapters render with real fixture data, not drawings,
  // and the public filing demo is embedded on the page.
  await expect(page.locator(".tv-chapters article")).toHaveCount(4);
  await expect(
    page.getByRole("heading", { name: "It sees more than text." }),
  ).toBeVisible();
  await expect(page.locator(".tv-output-rail")).toContainText(
    "Portable Markdown",
  );
  await expect(
    page.getByRole("tablist", { name: "DART demo view" }),
  ).toBeVisible();
});

test("Reduced-motion home keeps the proof demo fully operable", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expectSiteHydrated(page);

  // The paper hero does its work without animation machinery: no canvas may
  // appear when the visitor prefers reduced motion.
  const hero = page.locator(".tv-hero-comp[data-live]");
  await expect(hero).toBeVisible();
  await expect(hero.locator("canvas")).toHaveCount(0);

  // The source-evidence compare stays fully operable: the selected cell keeps
  // its provenance label and the view tabs still switch.
  const demo = page.locator(".tv-proof-demo");
  await expect(demo.locator(".tv-source-cell-selected")).toHaveAttribute(
    "aria-label",
    "Revenue 4,902,490,901 JPY, selected source evidence",
  );

  await demo.getByRole("tab", { name: "Original" }).click();
  await expect(demo.locator(".tv-proof-result code")).toHaveText(
    "ifrs-full_Revenue · line 3669",
  );
  await demo.getByRole("tab", { name: "Markdown" }).click();
  await expect(demo.locator(".tv-proof-result")).toContainText(
    "4,902,490,901 JPY for 2026 Q1",
  );
  await demo.getByRole("tab", { name: "Proof" }).click();
  await expect(demo.locator(".tv-proof-result code")).toHaveText(
    "archive sha256 3b7876350a203296…",
  );
});

test("Public filing demo preserves one receipt through every transformation", async ({
  page,
}) => {
  await page.goto("/demo/dart", { waitUntil: "domcontentloaded" });
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Korea DART Knowledge System.",
    }),
  ).toBeVisible();

  // The acquired OpenDART receipt is shown with the source and stays
  // verifiable at the original archive.
  const demo = page.locator(".tv-proof-demo");
  await expect(demo).toContainText("OPENDART RECEIPT 20260730000413");
  await expect(
    demo.getByRole("link", { name: /Verify receipt/ }),
  ).toHaveAttribute(
    "href",
    "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260730000413",
  );
  await expect(demo.locator(".tv-source-cell-selected")).toHaveAttribute(
    "aria-label",
    "Revenue 4,902,490,901 JPY, selected source evidence",
  );

  // The same revenue fact survives Original → Markdown → Vault → Graph
  // without losing its origin.
  const result = demo.locator(".tv-proof-result");

  await demo.getByRole("tab", { name: "Original" }).click();
  await expect(result).toContainText("ifrs-full_Revenue · line 3669");

  await demo.getByRole("tab", { name: "Markdown" }).click();
  await expect(result).toContainText("4,902,490,901 JPY for 2026 Q1");
  await expect(result).toContainText(
    "| Revenue | 4,902,490,901 | 10,048,464,180 |",
  );

  await demo.getByRole("tab", { name: "Vault" }).click();
  await expect(result).toContainText("JTC — 2026 Q1 revenue");
  await expect(result).toContainText("source_receipt: 20260730000413");

  await demo.getByRole("tab", { name: "Graph" }).click();
  await expect(demo.getByLabel("JTC reported revenue")).toBeVisible();
  await expect(result).toContainText("JTC → reported → Revenue");
});

test("legacy review links enter the Integrity Console without leaking unsafe context", async ({
  page,
}) => {
  // First hit of /integrity in a run can trigger a cold dev compile
  // (measured 100s+ on this disk); keep a deterministic local budget.
  test.setTimeout(90_000);
  await page.goto(
    "/review?project=project-7&token=secret&redirect_uri=https%3A%2F%2Fevil.example",
    { waitUntil: "domcontentloaded" },
  );
  // The legacy route redirects client-side after the shell hydrates; on a
  // cold dev compile that hand-off can outlive the default assertion window.
  await expect(page).toHaveURL(/\/integrity\?project=project-7$/, {
    timeout: 30_000,
  });
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
  await page.goto("/knowledge-bases", { waitUntil: "domcontentloaded" });
  await expectAppHydrated(page);
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
  await page.goto("/projects", { waitUntil: "domcontentloaded" });
  await expectAppHydrated(page);
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

test("Command menu filters quick navigation and closes on Escape", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name === "mobile",
    "Desktop command surface is tested separately from mobile navigation.",
  );
  await page.goto("/projects", { waitUntil: "domcontentloaded" });
  await expectAppHydrated(page);
  const trigger = page.getByRole("button", {
    name: /Search projects, documents, or evidence/,
  });
  // The shell loads as a deferred chunk and hydrates after first paint; a
  // click that lands before hydration is dropped, so retry until the dialog
  // responds instead of racing a single click.
  await expect(async () => {
    await trigger.click();
    await expect(
      page.getByRole("dialog", { name: "Command menu" }),
    ).toBeVisible();
  }).toPass({ timeout: 15_000 });

  // type="search" exposes the ARIA role "searchbox", not "textbox".
  const search = page.getByRole("searchbox", { name: "Filter commands" });
  await expect(search).toBeFocused();
  await expect(search).toHaveAttribute(
    "placeholder",
    "Filter quick navigation",
  );

  await search.fill("projects");
  await expect(page.getByRole("link", { name: /Open projects/ })).toBeVisible();

  // Filtering is honest: a query with no match says so instead of pretending.
  await search.fill("knowledge");
  await expect(
    page.locator("#command-results").getByText(/No command matches/),
  ).toBeVisible();
  await expect(page.locator("#command-results a")).toHaveCount(0);

  await search.press("Escape");
  await expect(page.getByRole("dialog", { name: "Command menu" })).toHaveCount(
    0,
  );
});

test("Legal routes are independent and never claim unapproved legal effect", async ({
  page,
}) => {
  await page.goto("/legal/privacy", { waitUntil: "domcontentloaded" });
  await expect(
    page.getByRole("heading", { level: 1, name: "Privacy principles." }),
  ).toBeVisible();
  // Honest publication control: the page states its unapproved status instead
  // of presenting draft text as counsel-reviewed policy.
  await expect(
    page.getByText(/final public policy text requires legal approval/),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Collect less. Explain purpose. Retain by policy. Delete completely.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Data categories" }),
  ).toBeVisible();

  // The four legal routes stay reachable and independent via the shared
  // marketing footer.
  for (const [name, href] of [
    ["privacy", "/legal/privacy"],
    ["terms", "/legal/terms"],
    ["subprocessors", "/legal/subprocessors"],
    ["third party notices", "/legal/third-party-notices"],
  ] as const) {
    // exact: true — "Contact privacy" on the page must not match the footer
    // link that merely reads "privacy".
    await expect(page.getByRole("link", { name, exact: true })).toHaveAttribute(
      "href",
      href,
    );
  }

  await page.goto("/legal/terms", { waitUntil: "domcontentloaded" });
  await expect(
    page.getByRole("heading", { level: 1, name: "Terms of service." }),
  ).toBeVisible();
});

test("Security architecture exposes real trust boundaries and honest evidence status", async ({
  page,
}) => {
  await page.goto("/security", { waitUntil: "domcontentloaded" });
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Your knowledge stays yours.",
    }),
  ).toBeVisible();
  // The promise is bounded: no unearned certifications are displayed.
  await expect(
    page.getByText(
      /Private by default, controlled by policy, and traceable by design/,
    ),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Browser → Signed Upload → Private Storage → Controlled Worker → Derived Knowledge → Scheduled Purge",
    ),
  ).toBeVisible();

  // The control ledger separates current controls from roadmap promises.
  const ledger = page.locator('[aria-label="Security control ledger"]');
  await expect(ledger).toBeVisible();
  await expect(ledger.getByText("External transfer")).toBeVisible();
  await expect(ledger.getByText("Blocked", { exact: true })).toBeVisible();
  await expect(ledger.getByText("Retention")).toBeVisible();
  await expect(
    ledger.getByText("No hidden policy · no unregistered claim"),
  ).toBeVisible();

  for (const section of [
    "Encryption and isolation",
    "Retention and deletion",
    "External processing",
    "Available and roadmap",
  ]) {
    await expect(page.getByRole("heading", { name: section })).toBeVisible();
  }

  await expect(
    page.getByRole("link", { name: "Read data principles" }),
  ).toHaveAttribute("href", "/legal/privacy");
});

test("Processing workspace presents a demo snapshot without pretending it is live", async ({
  page,
  isMobile,
}) => {
  await page.goto("/documents/sample-dart/processing", {
    waitUntil: "domcontentloaded",
  });
  await expectAppHydrated(page);
  await expect(
    page.getByText(
      "Demo workspace · No documents are processed and no credits are used.",
    ),
  ).toBeVisible();

  // The sample is a preflight snapshot: it reports facts and never invents
  // live progress before the user approves processing.
  const badge = page.getByLabel(/demo snapshot, not a live connection/i);
  if (isMobile) {
    await expect(badge).toBeHidden();
  } else {
    await expect(badge).toBeVisible();
  }
  await expect(badge).toContainText("Demo snapshot");
  await expect(page.locator(".pipeline-summary")).toContainText("Paused demo");

  const stages = page.locator(".stage-track .stage-item");
  const stageLabels = [
    "Upload",
    "Security",
    "Preflight",
    "Extract",
    "Structure",
    "Knowledge",
    "Validate",
    "Package",
  ];
  await expect(stages).toHaveCount(stageLabels.length);
  // span:nth-child(2) is the label; the first child holds the check/number.
  await expect(
    page.locator(".stage-track .stage-item > span:nth-child(2)"),
  ).toHaveText(stageLabels);

  await expect(page.locator("body")).not.toContainText(/paddle|mineru/i);
});

test("Collection intake preserves manifest truth and cannot start before signed preflight", async ({
  page,
}) => {
  await page.goto("/intake", { waitUntil: "domcontentloaded" });
  await expectAppHydrated(page);
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
  await page.goto("/integrity?reference=1", {
    waitUntil: "domcontentloaded",
  });
  await expectAppHydrated(page);
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

test("Public benchmark route commits to demonstrated accuracy, not declared numbers", async ({
  page,
}) => {
  await page.goto("/benchmarks", { waitUntil: "domcontentloaded" });
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "We benchmark what matters inside the document.",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Accuracy should be demonstrated, not declared."),
  ).toBeVisible();

  for (const section of [
    "Ground truth",
    "Deterministic metrics",
    "Page comparator",
    "What this does not prove",
  ]) {
    // exact: true — the route diagram's "DART Ground Truth" heading must not
    // match the "Ground truth" section.
    await expect(
      page.getByRole("heading", { name: section, exact: true }),
    ).toBeVisible();
  }
  // The honesty clause stays on the page: no benchmark overclaims coverage.
  await expect(
    page.getByText(
      /No benchmark represents every customer document, language, or semantic use case\./,
    ),
  ).toBeVisible();

  await expect(
    page.getByRole("link", { name: "View the latest report" }),
  ).toHaveAttribute("href", "/app/benchmarks");
  await expect(
    page.getByRole("link", { name: "Read the methodology" }),
  ).toHaveAttribute("href", "/research");
});

test("Evidence film exposes the signed model portfolio with real controls", async ({
  page,
}) => {
  await page.goto("/film?scene=4&static=1", {
    waitUntil: "domcontentloaded",
  });
  await expect(
    page.getByRole("heading", {
      name: "Different strengths become one routing advantage.",
    }),
  ).toBeVisible();
  const formalCaseCount = benchmarkSnapshot.datasets
    .filter((candidate) => candidate.status === "available")
    .reduce(
      (total, candidate) => total + (candidate.evidence?.case_count ?? 0),
      0,
    );
  await expect(
    page.getByText(
      `${formalCaseCount} / ${formalCaseCount} formal inference cases completed`,
    ),
  ).toBeVisible();
  for (const candidate of benchmarkSnapshot.datasets.filter(
    (candidate) => candidate.status === "available",
  )) {
    const expected = candidate.label
      .replace("MinerU 3.4.4 · Pipeline", "MinerU pipe")
      .replace("PaddleOCR-VL 1.6 · FastDeploy c8", "Paddle VL")
      .replace("MinerU 3.4.4 · VLM c1", "MinerU VLM")
      .replace("DeepSeek-OCR-2 · Transformers", "DeepSeek 2")
      .replace("OvisOCR2 0.9B · vLLM cu129", "Ovis 0.9B");
    await expect(page.getByText(expected)).toBeVisible();
  }
  await page.getByRole("button", { name: "Next scene" }).click();
  await expect(
    page.getByRole("heading", { name: "Documents become inspectable notes." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Previous scene" }).click();
  await expect(
    page.getByRole("heading", { name: /Different strengths/ }),
  ).toBeVisible();
});

test("Signup keeps the Google-centered entry contract while the retired compile route stays gone", async ({
  page,
}) => {
  // G0 retired the standalone compile product page. The catch-all must keep
  // returning 404 instead of reviving orphaned marketing copy.
  expect(
    (
      await page.goto("/product/compile", {
        waitUntil: "domcontentloaded",
      })
    )?.status(),
  ).toBe(404);

  await page.goto("/signup", { waitUntil: "domcontentloaded" });
  await expect(
    page.getByRole("button", { name: "Continue with Google" }),
  ).toBeVisible();
  await expect(page.getByText("or continue with email")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create workspace" }),
  ).toBeEnabled();
});
