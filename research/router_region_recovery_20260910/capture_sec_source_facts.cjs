"use strict";

// Render bounded, preselected SEC table-row fragments. The runtime manifest
// never contains the source fact value or semantic XBRL attributes.

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const sharp = require("sharp");

const VIEWPORT = { width: 1440, height: 1200 };
const DEVICE_SCALE_FACTOR = 2;
const MAX_CROP = { width: 1400, height: 512 };
const PADDING = 24;

function sha(data) {
  return `sha256:${crypto.createHash("sha256").update(data).digest("hex")}`;
}

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || !value) throw new Error("INVALID_ARGUMENTS");
    values[key.slice(2)] = value;
  }
  if (!values.input || !values.output || !values.expectedManifest) {
    throw new Error("INPUT_OUTPUT_AND_EXPECTED_MANIFEST_REQUIRED");
  }
  return values;
}

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}

function cropFor(row, fact, documentSize) {
  const width = Math.min(MAX_CROP.width, row.width + PADDING * 2, documentSize.width);
  const height = Math.min(MAX_CROP.height, row.height + PADDING * 2, documentSize.height);
  const x =
    row.width + PADDING * 2 <= width
      ? row.x - PADDING
      : fact.x + fact.width / 2 - width / 2;
  const y =
    row.height + PADDING * 2 <= height
      ? row.y - PADDING
      : fact.y + fact.height / 2 - height / 2;
  return {
    x: clamp(x, 0, Math.max(0, documentSize.width - width)),
    y: clamp(y, 0, Math.max(0, documentSize.height - height)),
    width,
    height,
  };
}

function bbox1000(rect, clip) {
  return [
    Math.floor(((rect.x - clip.x) / clip.width) * 1000),
    Math.floor(((rect.y - clip.y) / clip.height) * 1000),
    Math.ceil(((rect.x + rect.width - clip.x) / clip.width) * 1000),
    Math.ceil(((rect.y + rect.height - clip.y) / clip.height) * 1000),
  ].map((value) => clamp(value, 0, 1000));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const input = path.resolve(args.input);
  const output = path.resolve(args.output);
  if (fs.existsSync(output)) throw new Error("SEC_FACT_CAPTURE_OUTPUT_MUST_BE_NEW");
  const manifestPath = path.join(input, "FRAGMENT_MANIFEST.jsonl");
  const manifestBytes = fs.readFileSync(manifestPath);
  if (sha(manifestBytes) !== args.expectedManifest) {
    throw new Error("SEC_FACT_FRAGMENT_MANIFEST_MISMATCH");
  }
  const fragments = manifestBytes
    .toString("utf8")
    .trim()
    .split(/\r?\n/u)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
  fs.mkdirSync(path.join(output, "crops"), { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const browserVersion = browser.version();
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: DEVICE_SCALE_FACTOR,
    colorScheme: "light",
    javaScriptEnabled: false,
  });
  const rows = [];
  const refusals = [];
  try {
    for (const fragment of fragments) {
      const fragmentPath = path.resolve(input, fragment.fragment_relative_path);
      if (!fragmentPath.startsWith(input + path.sep)) throw new Error("SEC_FRAGMENT_PATH_ESCAPE");
      const fragmentBytes = fs.readFileSync(fragmentPath);
      if (sha(fragmentBytes) !== fragment.fragment_sha256) {
        throw new Error("SEC_FRAGMENT_HASH_MISMATCH");
      }
      const page = await context.newPage();
      await page.setContent(fragmentBytes.toString("utf8"), {
        waitUntil: "domcontentloaded",
        timeout: 30000,
      });
      const target = page.locator(fragment.target_selector);
      if ((await target.count()) !== 1) throw new Error("SEC_FRAGMENT_TARGET_NOT_UNIQUE");
      const fact = await target.boundingBox();
      const row = await target.locator("xpath=ancestor::tr[1]").boundingBox();
      const visible = await target.isVisible();
      if (!visible || !fact || !row || fact.width < 4 || fact.height < 4) {
        refusals.push({ region_id: fragment.region_id, reason: "TARGET_NOT_RENDERABLY_VISIBLE" });
        await page.close();
        continue;
      }
      const documentSize = await page.evaluate(() => ({
        width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0),
        height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0),
      }));
      const clip = cropFor(row, fact, documentSize);
      if (clip.width < 4 || clip.height < 4) throw new Error("SEC_FRAGMENT_CROP_INVALID");
      const relative = `crops/${fragment.region_id}.png`;
      const pngPath = path.join(output, relative);
      await page.screenshot({ path: pngPath, type: "png", clip, animations: "disabled" });
      const pngBytes = fs.readFileSync(pngPath);
      const metadata = await sharp(pngBytes).metadata();
      rows.push({
        region_id: fragment.region_id,
        ticker: fragment.ticker,
        cik: fragment.cik,
        accession: fragment.accession,
        filing_url: fragment.filing_url,
        filing_html_sha256: fragment.filing_html_sha256,
        input_relative_path: relative,
        input_png_sha256: sha(pngBytes),
        input_width_px: metadata.width,
        input_height_px: metadata.height,
        target_bbox1000: bbox1000(fact, clip),
        fragment_sha256: fragment.fragment_sha256,
      });
      await page.close();
    }
  } finally {
    await context.close();
    await browser.close();
  }
  rows.sort((left, right) => left.region_id.localeCompare(right.region_id));
  refusals.sort((left, right) => left.region_id.localeCompare(right.region_id));
  const runtimeBytes = Buffer.from(rows.map((row) => JSON.stringify(row)).join("\n") + "\n", "utf8");
  fs.writeFileSync(path.join(output, "RUNTIME_MANIFEST.jsonl"), runtimeBytes, { flag: "wx" });
  const result = {
    benchmark_id: "TAVONEL-SEC-SOURCE-FACT-HOLDOUT-20260910-V1",
    selected_fragments: fragments.length,
    captured_regions: rows.length,
    refusals,
    browser_version: browserVersion,
    browser_executable: chromium.executablePath(),
    viewport_css: [VIEWPORT.width, VIEWPORT.height],
    device_scale_factor: DEVICE_SCALE_FACTOR,
    fragment_manifest_sha256: args.expectedManifest,
    runtime_manifest_sha256: sha(runtimeBytes),
    model_output_opened: false,
    gpu_cost_usd: 0,
  };
  fs.writeFileSync(path.join(output, "CAPTURE_RESULT.json"), JSON.stringify(result, null, 2) + "\n", {
    flag: "wx",
  });
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
