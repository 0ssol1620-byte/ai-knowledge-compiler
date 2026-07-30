import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const repositoryRoot = resolve(import.meta.dirname, "../../..");
const outputRoot = resolve(repositoryRoot, "assets/product/recordings");
const temporaryRoot = resolve(outputRoot, ".playwright");
const baseUrl = process.env.STRUCTARA_CAPTURE_URL ?? "http://127.0.0.1:3000";
const loops = [
  ["M01-upload-preflight", "/onboarding"],
  ["M02-semantic-block-detection", "/documents/annual-report-2025/processing"],
  ["M03-table-reconstruction", "/documents/annual-report-2025/review"],
  ["M04-markdown-source-proof", "/documents/annual-report-2025/markdown"],
  ["M05-numeric-review", "/documents/annual-report-2025/review"],
  ["M06-notes-local-graph", "/app/projects/public-filing/knowledge"],
  ["M07-relation-evidence", "/app/projects/public-filing/graph"],
  ["M08-export-package", "/app/exports"],
];

await mkdir(temporaryRoot, { recursive: true });
const browser = await chromium.launch({ headless: true });
const records = [];

for (const [id, route] of loops) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    colorScheme: "light",
    recordVideo: {
      dir: temporaryRoot,
      size: { width: 1280, height: 720 },
    },
  });
  const page = await context.newPage();
  const video = page.video();
  await page.goto(`${baseUrl}${route}`, {
    waitUntil: "domcontentloaded",
    timeout: 30_000,
  });
  await page.addStyleTag({
    content:
      "*{caret-color:transparent!important} .nextjs-toast{display:none!important}",
  });
  await page.waitForTimeout(900);
  await page.mouse.move(860, 340, { steps: 18 });
  await page.mouse.wheel(0, 360);
  await page.waitForTimeout(900);
  await page.mouse.wheel(0, -180);
  await page.waitForTimeout(650);
  await context.close();

  const source = await video.path();
  const file = `STR-PRODUCT-T0-${id.toUpperCase()}-EN-1280x720-v01.webm`;
  await rename(source, resolve(outputRoot, file));
  records.push({
    id,
    route,
    file,
    truthClass: "T0",
    disclosure: "Sequence condensed for demonstration",
  });
}

await browser.close();
const files = (await readdir(outputRoot))
  .filter((file) => file.endsWith(".webm"))
  .sort();
const hashes = [];
for (const file of files) {
  const bytes = await readFile(resolve(outputRoot, file));
  hashes.push(`${createHash("sha256").update(bytes).digest("hex")}  ${file}`);
}
await writeFile(resolve(outputRoot, "hashes.sha256"), `${hashes.join("\n")}\n`);
await writeFile(
  resolve(outputRoot, "capture-manifest.json"),
  `${JSON.stringify(
    {
      project: "Public Filing Knowledge Demo",
      label: "Synthetic Demo",
      viewport: "1280x720",
      disclosure: "Sequence condensed for demonstration",
      loops: records,
    },
    null,
    2,
  )}\n`,
);

console.log(`Captured ${records.length} truthful product loops.`);
