import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { promisify } from "node:util";

const repositoryRoot = resolve(import.meta.dirname, "../../..");
const outputRoot = resolve(repositoryRoot, "assets/product/recordings");
const temporaryRoot = resolve(outputRoot, ".playwright");
const baseUrl = process.env.FOLYNTA_CAPTURE_URL ?? "http://127.0.0.1:3000";
const ffmpeg = process.env.FOLYNTA_FFMPEG ?? "ffmpeg";
const execFileAsync = promisify(execFile);
const loops = [
  ["M01-upload-preflight", "/onboarding"],
  ["M02-page-rail-processing", "/documents/annual-report-2025/processing"],
  ["M03-pdf-hover-to-markdown", "/documents/annual-report-2025/markdown"],
  ["M04-markdown-to-bbox", "/documents/annual-report-2025/sources"],
  ["M05-numeric-review", "/documents/annual-report-2025/review"],
  ["M06-table-diff", "/documents/annual-report-2025/review"],
  ["M07-note-split-to-backlinks", "/app/projects/public-filing/knowledge"],
  ["M08-relation-to-proof", "/app/projects/public-filing/graph"],
  ["M09-export-package", "/app/exports"],
  ["M10-enterprise-policy-impact", "/app/settings/security"],
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
  const stem = `FLY-PRODUCT-T0-${id.toUpperCase()}-EN-1280x720-v01`;
  const file = `${stem}.webm`;
  const mp4 = `${stem}.mp4`;
  await rename(source, resolve(outputRoot, file));
  await execFileAsync(ffmpeg, [
    "-y",
    "-i",
    resolve(outputRoot, file),
    "-an",
    "-c:v",
    "libx264",
    "-preset",
    "slow",
    "-crf",
    "25",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    resolve(outputRoot, mp4),
  ]);
  records.push({
    id,
    route,
    file,
    derivatives: [mp4],
    truthClass: "T0",
    disclosure: "Sequence condensed for demonstration",
  });
}

await browser.close();
const files = records
  .flatMap((record) => [record.file, ...record.derivatives])
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
