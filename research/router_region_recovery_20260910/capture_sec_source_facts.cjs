"use strict";

// Capture deterministic table-row crops and keep SEC fact truth outside the
// runtime manifest. This script runs only after the holdout protocol is frozen.

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const sharp = require("sharp");

const EXPECTED_FILINGS =
  "sha256:e66c483ff52b1259218f8984a24579694812c5a42204a61ae4e0c8fe085a0682";
const MAX_FACTS_PER_FILING = 4;
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
  if (!values.input || !values.output) throw new Error("INPUT_AND_OUTPUT_REQUIRED");
  return values;
}

function normalizeVisible(value) {
  return value.replace(/\s+/gu, " ").trim();
}

function selectionHash(filing, fact) {
  const parts = [
    filing.cik,
    filing.accession,
    fact.name,
    fact.contextRef,
    fact.unitRef,
    normalizeVisible(fact.visibleText),
  ];
  return sha(Buffer.from(parts.join("\x1f"), "utf8"));
}

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}

function cropFor(row, fact, documentSize) {
  const width = Math.min(MAX_CROP.width, row.width + PADDING * 2, documentSize.width);
  const height = Math.min(MAX_CROP.height, row.height + PADDING * 2, documentSize.height);
  const desiredX = row.width + PADDING * 2 <= width ? row.x - PADDING : fact.x + fact.width / 2 - width / 2;
  const desiredY = row.height + PADDING * 2 <= height ? row.y - PADDING : fact.y + fact.height / 2 - height / 2;
  return {
    x: clamp(desiredX, 0, Math.max(0, documentSize.width - width)),
    y: clamp(desiredY, 0, Math.max(0, documentSize.height - height)),
    width,
    height,
  };
}

function bbox1000(rect, clip) {
  const values = [
    Math.floor(((rect.x - clip.x) / clip.width) * 1000),
    Math.floor(((rect.y - clip.y) / clip.height) * 1000),
    Math.ceil(((rect.x + rect.width - clip.x) / clip.width) * 1000),
    Math.ceil(((rect.y + rect.height - clip.y) / clip.height) * 1000),
  ];
  return values.map((value) => clamp(value, 0, 1000));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const input = path.resolve(args.input);
  const output = path.resolve(args.output);
  if (fs.existsSync(output)) throw new Error("SEC_FACT_OUTPUT_MUST_BE_NEW");
  const filingsPath = path.join(input, "FILINGS.jsonl");
  const filingsBytes = fs.readFileSync(filingsPath);
  if (sha(filingsBytes) !== EXPECTED_FILINGS) throw new Error("SEC_FILINGS_MANIFEST_MISMATCH");
  const filings = filingsBytes
    .toString("utf8")
    .trim()
    .split(/\r?\n/u)
    .map((line) => JSON.parse(line))
    .filter((row) => row.status === "acquired");
  fs.mkdirSync(path.join(output, "crops"), { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const browserVersion = browser.version();
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: DEVICE_SCALE_FACTOR,
    colorScheme: "light",
    javaScriptEnabled: false,
  });
  const runtimeRows = [];
  const truthRows = [];
  const issuerCounts = {};
  try {
    for (const filing of filings) {
      const htmlPath = path.resolve(input, filing.artifact_relative_path);
      if (!htmlPath.startsWith(input + path.sep)) throw new Error("SEC_HTML_PATH_ESCAPE");
      const htmlBytes = fs.readFileSync(htmlPath);
      if (sha(htmlBytes) !== filing.filing_html_sha256) throw new Error("SEC_HTML_HASH_MISMATCH");
      const page = await context.newPage();
      await page.setContent(htmlBytes.toString("utf8"), {
        waitUntil: "domcontentloaded",
        timeout: 60000,
      });
      await page.addStyleTag({
        content:
          "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}",
      });
      const facts = await page.evaluate(() => {
        const elements = Array.from(document.getElementsByTagName("ix:nonfraction"));
        return elements.map((element, domIndex) => {
          const rect = element.getBoundingClientRect();
          const cell = element.closest("td,th");
          const row = element.closest("tr") || cell || element;
          const rowRect = row.getBoundingClientRect();
          const style = window.getComputedStyle(element);
          return {
            domIndex,
            name: element.getAttribute("name") || "",
            contextRef: element.getAttribute("contextref") || "",
            unitRef: element.getAttribute("unitref") || "",
            decimals: element.getAttribute("decimals"),
            scale: element.getAttribute("scale"),
            sign: element.getAttribute("sign"),
            nil: element.getAttribute("xsi:nil") === "true",
            visibleText: element.textContent || "",
            insideTableCell: Boolean(cell),
            visible:
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              Number(style.opacity || "1") > 0 &&
              rect.width >= 4 &&
              rect.height >= 4,
            rect: { x: rect.x + scrollX, y: rect.y + scrollY, width: rect.width, height: rect.height },
            rowRect: {
              x: rowRect.x + scrollX,
              y: rowRect.y + scrollY,
              width: rowRect.width,
              height: rowRect.height,
            },
          };
        });
      });
      const eligible = facts.filter(
        (fact) =>
          fact.visible &&
          fact.insideTableCell &&
          !fact.nil &&
          /\d/u.test(fact.visibleText) &&
          fact.name &&
          fact.contextRef &&
          fact.unitRef,
      );
      const tupleCounts = new Map();
      for (const fact of eligible) {
        const tuple = [
          fact.name,
          fact.contextRef,
          fact.unitRef,
          normalizeVisible(fact.visibleText),
        ].join("\x1f");
        tupleCounts.set(tuple, (tupleCounts.get(tuple) || 0) + 1);
      }
      const selected = eligible
        .filter((fact) => {
          const tuple = [
            fact.name,
            fact.contextRef,
            fact.unitRef,
            normalizeVisible(fact.visibleText),
          ].join("\x1f");
          return tupleCounts.get(tuple) === 1;
        })
        .map((fact) => ({ ...fact, selectionSha256: selectionHash(filing, fact) }))
        .sort((left, right) => left.selectionSha256.localeCompare(right.selectionSha256))
        .slice(0, MAX_FACTS_PER_FILING);
      issuerCounts[filing.ticker] = {
        facts: facts.length,
        eligible: eligible.length,
        selected: selected.length,
      };
      const documentSize = await page.evaluate(() => ({
        width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0),
        height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0),
      }));
      for (const fact of selected) {
        const regionId = `sec-fact-${fact.selectionSha256.slice(-24)}`;
        const clip = cropFor(fact.rowRect, fact.rect, documentSize);
        const pngPath = path.join(output, "crops", `${regionId}.png`);
        await page.screenshot({ path: pngPath, type: "png", clip, animations: "disabled" });
        const pngBytes = fs.readFileSync(pngPath);
        const metadata = await sharp(pngBytes).metadata();
        const runtime = {
          region_id: regionId,
          ticker: filing.ticker,
          cik: filing.cik,
          accession: filing.accession,
          filing_url: filing.filing_url,
          filing_html_sha256: filing.filing_html_sha256,
          input_relative_path: `crops/${regionId}.png`,
          input_png_sha256: sha(pngBytes),
          input_width_px: metadata.width,
          input_height_px: metadata.height,
          target_bbox1000: bbox1000(fact.rect, clip),
        };
        runtimeRows.push(runtime);
        truthRows.push({
          ...runtime,
          fact_name: fact.name,
          context_ref: fact.contextRef,
          unit_ref: fact.unitRef,
          decimals: fact.decimals,
          scale: fact.scale,
          sign: fact.sign,
          normalized_visible_value: normalizeVisible(fact.visibleText),
          source_fact_sha256: sha(
            Buffer.from(
              [fact.name, fact.contextRef, fact.unitRef, normalizeVisible(fact.visibleText)].join(
                "\x1f",
              ),
              "utf8",
            ),
          ),
          selection_sha256: fact.selectionSha256,
          dom_index: fact.domIndex,
          clip_css: clip,
          fact_css: fact.rect,
          row_css: fact.rowRect,
        });
      }
      await page.close();
    }
  } finally {
    await context.close();
    await browser.close();
  }

  runtimeRows.sort((left, right) => left.region_id.localeCompare(right.region_id));
  truthRows.sort((left, right) => left.region_id.localeCompare(right.region_id));
  const runtimeBytes = Buffer.from(
    runtimeRows.map((row) => JSON.stringify(row)).join("\n") + "\n",
    "utf8",
  );
  const truthBytes = Buffer.from(
    truthRows.map((row) => JSON.stringify(row)).join("\n") + "\n",
    "utf8",
  );
  fs.writeFileSync(path.join(output, "RUNTIME_MANIFEST.jsonl"), runtimeBytes, { flag: "wx" });
  fs.writeFileSync(path.join(output, "SEALED_TRUTH.jsonl"), truthBytes, { flag: "wx" });
  const result = {
    benchmark_id: "TAVONEL-SEC-SOURCE-FACT-HOLDOUT-20260910-V1",
    filings: filings.length,
    regions: runtimeRows.length,
    issuer_counts: issuerCounts,
    browser_version: browserVersion,
    browser_executable: chromium.executablePath(),
    viewport_css: [VIEWPORT.width, VIEWPORT.height],
    device_scale_factor: DEVICE_SCALE_FACTOR,
    runtime_manifest_sha256: sha(runtimeBytes),
    sealed_truth_sha256: sha(truthBytes),
    filing_manifest_sha256: EXPECTED_FILINGS,
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
