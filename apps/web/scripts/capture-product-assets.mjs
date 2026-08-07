import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const repositoryRoot = resolve(import.meta.dirname, "../../..");
const outputRoot = resolve(
  repositoryRoot,
  "assets/product/screenshots/en/1440x900",
);
const mobileOutputRoot = resolve(
  repositoryRoot,
  "assets/product/screenshots/en/390x844",
);
const baseUrl = process.env.TAVONEL_CAPTURE_URL ?? "http://127.0.0.1:3000";
const captures = [
  ["home", "/app/home"],
  ["projects", "/app/projects"],
  ["project-overview", "/app/projects/public-filing/overview"],
  ["project-documents", "/app/projects/public-filing/documents"],
  ["project-knowledge", "/app/projects/public-filing/knowledge"],
  ["project-graph", "/app/projects/public-filing/graph"],
  ["project-exports", "/app/projects/public-filing/exports"],
  ["processing", "/documents/annual-report-2025/processing"],
  ["review", "/documents/annual-report-2025/review"],
  ["markdown", "/documents/annual-report-2025/markdown"],
  ["sources", "/documents/annual-report-2025/sources"],
  ["versions", "/documents/annual-report-2025/versions"],
  ["jobs", "/app/jobs"],
  ["knowledge-bases", "/app/knowledge-bases"],
  ["benchmark-lab", "/app/benchmarks"],
  ["export-center", "/app/exports"],
  ["security-center", "/app/settings/security"],
  ["admin-jobs", "/app/admin/jobs"],
];

await mkdir(outputRoot, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  colorScheme: "light",
  reducedMotion: "reduce",
  deviceScaleFactor: 1,
});
const page = await context.newPage();
const records = [];

for (const [name, route] of captures) {
  await page.goto(`${baseUrl}${route}`, {
    waitUntil: "domcontentloaded",
    timeout: 30_000,
  });
  await page.addStyleTag({
    content:
      "html{scroll-behavior:auto!important}*{caret-color:transparent!important} .nextjs-toast{display:none!important}",
  });
  await page.waitForTimeout(350);
  const fileName = `TAV-PRODUCT-T0-${name.toUpperCase()}-EN-1440x900-v01.webp`;
  const filePath = resolve(outputRoot, fileName);
  await page.screenshot({
    path: filePath,
    type: "webp",
    quality: 82,
    animations: "disabled",
  });
  records.push({ name, route, file: fileName, truthClass: "T0" });
}

await writeFile(
  resolve(outputRoot, "capture-manifest.json"),
  `${JSON.stringify(
    {
      project: "Public Filing Knowledge Demo",
      label: "Synthetic Demo",
      viewport: "1440x900",
      locale: "en-US",
      capturedAt: new Date().toISOString(),
      captures: records,
    },
    null,
    2,
  )}\n`,
);

await context.close();
await mkdir(mobileOutputRoot, { recursive: true });
const mobileContext = await browser.newContext({
  viewport: { width: 390, height: 844 },
  colorScheme: "light",
  reducedMotion: "reduce",
  deviceScaleFactor: 1,
});
const mobilePage = await mobileContext.newPage();
const mobileCaptures = captures.filter(([name]) =>
  ["home", "projects", "processing", "review", "project-graph"].includes(name),
);
const mobileRecords = [];

for (const [name, route] of mobileCaptures) {
  await mobilePage.goto(`${baseUrl}${route}`, {
    waitUntil: "domcontentloaded",
    timeout: 30_000,
  });
  await mobilePage.addStyleTag({
    content:
      "html{scroll-behavior:auto!important}*{caret-color:transparent!important} .nextjs-toast{display:none!important}",
  });
  await mobilePage.waitForTimeout(300);
  const fileName = `TAV-PRODUCT-T0-${name.toUpperCase()}-EN-390x844-v01.webp`;
  await mobilePage.screenshot({
    path: resolve(mobileOutputRoot, fileName),
    type: "webp",
    quality: 82,
    animations: "disabled",
  });
  mobileRecords.push({ name, route, file: fileName, truthClass: "T0" });
}

await writeFile(
  resolve(mobileOutputRoot, "capture-manifest.json"),
  `${JSON.stringify(
    {
      project: "Public Filing Knowledge Demo",
      label: "Synthetic Demo",
      viewport: "390x844",
      locale: "en-US",
      capturedAt: new Date().toISOString(),
      captures: mobileRecords,
    },
    null,
    2,
  )}\n`,
);

for (const directory of [outputRoot, mobileOutputRoot]) {
  const files = (await readdir(directory))
    .filter((file) => file.endsWith(".webp"))
    .sort();
  const hashes = [];
  for (const file of files) {
    const bytes = await readFile(resolve(directory, file));
    hashes.push(`${createHash("sha256").update(bytes).digest("hex")}  ${file}`);
  }
  await writeFile(
    resolve(directory, "hashes.sha256"),
    `${hashes.join("\n")}\n`,
  );
}

await mobileContext.close();
await browser.close();
console.log(
  `Captured ${records.length} desktop and ${mobileRecords.length} mobile product evidence screens.`,
);
