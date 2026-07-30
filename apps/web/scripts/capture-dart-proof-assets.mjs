import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const repositoryRoot = resolve(import.meta.dirname, "../../..");
const outputRoot = resolve(repositoryRoot, "assets/public-proof/dart");
const baseUrl = process.env.STRUCTARA_CAPTURE_URL ?? "http://127.0.0.1:3000";
const receiptNumber = "20260730000413";
const sourceSha256 =
  "312d03bcd23951c21948021dc2ea115e2f5be58b7c5a1eb23d9dc9da1f98e6a3";

await mkdir(outputRoot, { recursive: true });
const browser = await chromium.launch({ headless: true });
const records = [];

async function prepare(viewport, reducedMotion = "reduce") {
  const context = await browser.newContext({
    viewport,
    colorScheme: "light",
    reducedMotion,
    locale: "en-US",
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  await page.goto(`${baseUrl}/demo/dart`, {
    waitUntil: "networkidle",
    timeout: 30_000,
  });
  await page.addStyleTag({
    content:
      "html{scroll-behavior:auto!important}*{caret-color:transparent!important}.nextjs-toast,.st-header,.skip-link,nextjs-portal{display:none!important}",
  });
  return { context, page };
}

async function captureTabs() {
  const { context, page } = await prepare({ width: 1440, height: 900 });
  const proof = page.locator(".st-route-proof");
  await proof.scrollIntoViewIfNeeded();
  for (const tab of ["Original", "Markdown", "Vault", "Graph", "Proof"]) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(100);
    const file = `STR-PROOF-T0-DART-EN-${tab.toUpperCase()}-1440x900-v01.webp`;
    await proof.screenshot({
      path: resolve(outputRoot, file),
      type: "webp",
      quality: 84,
      animations: "disabled",
    });
    records.push({ state: tab, viewport: "1440x900", file });
  }
  for (const [state, selector] of [
    ["SOURCE-CELL", ".st-proof-source"],
    ["EVIDENCE-RECEIPT", ".st-proof-evidence"],
  ]) {
    const file = `STR-PROOF-T0-DART-EN-${state}-1440x900-v01.webp`;
    await page.locator(selector).screenshot({
      path: resolve(outputRoot, file),
      type: "webp",
      quality: 88,
      animations: "disabled",
    });
    records.push({ state, viewport: "1440x900", file });
  }
  await context.close();
}

async function captureViewport(name, viewport) {
  const { context, page } = await prepare(viewport);
  const proof = page.locator(".st-route-proof");
  await proof.scrollIntoViewIfNeeded();
  await page.getByRole("tab", { name: "Proof" }).click();
  const file = `STR-PROOF-T0-DART-EN-${name}-${viewport.width}x${viewport.height}-v01.webp`;
  await proof.screenshot({
    path: resolve(outputRoot, file),
    type: "webp",
    quality: 84,
    animations: "disabled",
  });
  records.push({
    state: name,
    viewport: `${viewport.width}x${viewport.height}`,
    file,
  });
  await context.close();
}

async function captureRoute() {
  const viewport = { width: 1920, height: 1080 };
  const { context, page } = await prepare(viewport);
  const file = "STR-PROOF-T0-DART-EN-ROUTE-1920x1080-v01.webp";
  await page.screenshot({
    path: resolve(outputRoot, file),
    type: "webp",
    quality: 82,
    animations: "disabled",
  });
  records.push({ state: "ROUTE", viewport: "1920x1080", file });
  await context.close();
}

await captureTabs();
await captureViewport("TABLET", { width: 1024, height: 768 });
await captureViewport("MOBILE", { width: 390, height: 844 });
await captureRoute();
await browser.close();

const files = (await readdir(outputRoot))
  .filter((file) => file.endsWith(".webp"))
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
      schemaVersion: "1.0",
      truthClass: "T0",
      source: "OpenDART public filing",
      receiptNumber,
      sourceSha256,
      qualityClaimEligible: false,
      disclosure:
        "Public-source product fixture. No benchmark labels or quality claim.",
      capturedAt: new Date().toISOString(),
      captures: records,
    },
    null,
    2,
  )}\n`,
);

console.log(`Captured ${records.length} OpenDART proof assets.`);
