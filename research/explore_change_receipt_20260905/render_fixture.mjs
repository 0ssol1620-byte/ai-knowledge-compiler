/**
 * Writes every input this receipt was produced from, deterministically.
 *
 * Three jobs, in this order, because each one only means something if the one
 * before it held:
 *
 * 1. **Prove the renderer is the site's renderer.** The layout code below is
 *    copied from `nextjs/scripts/build-explore-sample.mjs` on the site's
 *    `origin/main` (9a7a93d). Before it emits anything new it re-renders
 *    `fp-200-maintenance-manual-revC.pdf` and compares the bytes against the
 *    file the site has committed. If they differ the script stops: a revision-B
 *    manual produced by a renderer that does not reproduce revision C is a
 *    document nobody can check.
 *
 * 2. **Emit the revision-B manual** the site does not have yet, in the site's
 *    own form. `CL_LANE_CONTRACT_2026-09-05.md` §4.3 specifies it as revision C
 *    with the interval text reading 1,500 hours and without the sentence that
 *    says the interval replaces revision B. Its title paragraph names revision
 *    B, which is a reading the contract does not pin -- see README.md, "What a
 *    founder still has to decide".
 *
 * 3. **Emit a clause-form restatement** of all four documents. The core's
 *    source resolver cannot canonicalise the FP-200 corpus as written; the
 *    restatement is the same sentences carried under printed clause numbers,
 *    which is the shape `akc_core_v3.sources` declares. It exists to locate the
 *    gap, not to stand in for the fixture, and every artifact derived from it is
 *    labelled that way.
 *
 * The three documents the site already publishes are copied in and their
 * sha256 checked against the digests the site committed, so `inputs/` is the
 * whole input set rather than a pointer to another repository.
 *
 *   OUT=inputs \
 *   SITE_PDFS=/d/CodexProjects/tavonel-saas-foundation/nextjs/public/explore-sample \
 *   SITE_INPUTS=/d/CodexProjects/tavonel-saas-foundation/nextjs/lib/explore-sample.inputs.json \
 *   PDFJS=/d/CodexProjects/tavonel-saas-foundation/nextjs/node_modules/pdfjs-dist/legacy/build/pdf.mjs \
 *   node render_fixture.mjs
 *
 * No creation date, no document id, no timestamp reaches the emitted PDF, so
 * re-running writes byte-identical files.
 */

import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const OUT = required("OUT");
const SITE_PDFS = required("SITE_PDFS");
const SITE_INPUTS = required("SITE_INPUTS");
const PDFJS = required("PDFJS");

function required(name) {
  const value = process.env[name];
  if (!value) {
    console.error(`${name} is not set; see the header of this file`);
    process.exit(2);
  }
  return value;
}

/* -------------------------------------------------------------------------
   the site's layout constants, copied verbatim
   ------------------------------------------------------------------------- */

const PAGE_WIDTH = 595;
const PAGE_HEIGHT = 842;
const MARGIN_LEFT = 66;
const TOP_BASELINE = 762;
const TITLE_SIZE = 13;
const BODY_SIZE = 10.5;
const LINE_HEIGHT = 15;
const PARAGRAPH_GAP = 26;
const WRAP_COLUMNS = 78;

/* -------------------------------------------------------------------------
   the corpus
   ------------------------------------------------------------------------- */

/** Revision C, as the site publishes it. Used only to check the renderer. */
const SITE_REV_C = {
  documentId: "fp200-maintenance-manual-rev-c",
  filename: "fp-200-maintenance-manual-revC.pdf",
  authority: "official",
  paragraphs: [
    "Scheduled maintenance for feedwater pump FP-200, revision C.",
    "Perform the full service procedure every 2,000 operating hours. This interval replaces the 1,500 hour interval published in revision B.",
    "Before replacing the mechanical seal, isolate the unit and fully depressurise the casing. Confirm zero pressure at gauge PG-11 before removing any fastener.",
    "The pump is rated for continuous duty at 2.4 MPa discharge pressure, and inspection points are listed in table 12.1.",
  ],
};

/** Revision B, in the site's form. The document the site does not have yet. */
const SITE_REV_B = {
  documentId: "fp200-maintenance-manual-rev-b",
  filename: "fp-200-maintenance-manual-revB.pdf",
  authority: "official",
  paragraphs: [
    "Scheduled maintenance for feedwater pump FP-200, revision B.",
    "Perform the full service procedure every 1,500 operating hours.",
    "Before replacing the mechanical seal, isolate the unit and fully depressurise the casing. Confirm zero pressure at gauge PG-11 before removing any fastener.",
    "The pump is rated for continuous duty at 2.4 MPa discharge pressure, and inspection points are listed in table 12.1.",
  ],
};

/*
  The clause-form restatement.

  Same sentences, given the printed anchors `akc_core_v3.sources` requires: a
  numbered heading opens a section, a numbered clause under it becomes a unit,
  and the clause number is the anchor identity travels on. Nothing is added and
  nothing is dropped -- every sentence of the four documents above appears here
  once, under a number.

  These are fixtures for the core, not documents the product serves. They are
  named `-clause-` so no build step can pick one up as an explore sample.
*/
const CLAUSE_REV_B = {
  documentId: "fp200-maintenance-manual-clause-rev-b",
  filename: "fp-200-maintenance-manual-clause-revB.pdf",
  authority: "official",
  paragraphs: [
    "1. Document",
    "1.1 Scheduled maintenance for feedwater pump FP-200, revision B.",
    "2. Service interval",
    "2.1 Perform the full service procedure every 1,500 operating hours.",
    "3. Seal replacement",
    "3.1 Before replacing the mechanical seal, isolate the unit and fully depressurise the casing. Confirm zero pressure at gauge PG-11 before removing any fastener.",
    "4. Duty rating",
    "4.1 The pump is rated for continuous duty at 2.4 MPa discharge pressure, and inspection points are listed in table 12.1.",
  ],
};

const CLAUSE_REV_C = {
  documentId: "fp200-maintenance-manual-clause-rev-c",
  filename: "fp-200-maintenance-manual-clause-revC.pdf",
  authority: "official",
  paragraphs: [
    "1. Document",
    "1.1 Scheduled maintenance for feedwater pump FP-200, revision C.",
    "2. Service interval",
    "2.1 Perform the full service procedure every 2,000 operating hours. This interval replaces the 1,500 hour interval published in revision B.",
    "3. Seal replacement",
    "3.1 Before replacing the mechanical seal, isolate the unit and fully depressurise the casing. Confirm zero pressure at gauge PG-11 before removing any fastener.",
    "4. Duty rating",
    "4.1 The pump is rated for continuous duty at 2.4 MPa discharge pressure, and inspection points are listed in table 12.1.",
  ],
};

const CLAUSE_NOTICE = {
  documentId: "fp200-change-notice-clause-cn-2026-03",
  filename: "fp-200-change-notice-clause-CN-2026-03.pdf",
  authority: "official",
  paragraphs: [
    "1. Document",
    "1.1 Change notice CN-2026-03 for feedwater pump FP-200, revision C.",
    "2. Interval change",
    "2.1 The service interval moves from 1,500 operating hours to 2,000 operating hours with effect from revision C.",
    "3. Superseded revision",
    "3.1 Revision B is superseded and must not be used to schedule work on this pump.",
  ],
};

const CLAUSE_LOG = {
  documentId: "fp200-service-log-clause-2026",
  filename: "fp-200-service-log-clause-2026.pdf",
  authority: "informal",
  paragraphs: [
    "1. Document",
    "1.1 Service log for feedwater pump FP-200, January to March 2026.",
    "2. Seal replacement",
    "2.1 The mechanical seal on FP-200 was replaced on 14 February 2026 after the unit was depressurised.",
    "3. Next service",
    "3.1 The next full service falls due at 2,000 operating hours from the February visit.",
  ],
};

/** The files the site already publishes, copied in and digest-checked. */
const SITE_PUBLISHED = [
  "fp-200-maintenance-manual-revC.pdf",
  "fp-200-change-notice-CN-2026-03.pdf",
  "fp-200-service-log-2026.pdf",
];

/* -------------------------------------------------------------------------
   the site's renderer and geometry reader, copied verbatim
   ------------------------------------------------------------------------- */

/** PDF literal strings escape exactly three characters. */
function escapeText(value) {
  return value.replace(/([\\()])/g, "\\$1");
}

/** Character-count wrapping. Crude, deterministic, and the geometry is read back anyway. */
function wrap(text, columns) {
  const lines = [];
  let line = "";
  for (const word of text.split(" ")) {
    if (line.length === 0) line = word;
    else if (line.length + 1 + word.length <= columns) line += ` ${word}`;
    else {
      lines.push(line);
      line = word;
    }
  }
  if (line.length > 0) lines.push(line);
  return lines;
}

function renderPdf(document) {
  const commands = [];
  let baseline = TOP_BASELINE;
  document.paragraphs.forEach((paragraph, index) => {
    const size = index === 0 ? TITLE_SIZE : BODY_SIZE;
    for (const line of wrap(paragraph, index === 0 ? 54 : WRAP_COLUMNS)) {
      commands.push(`BT /F1 ${size} Tf ${MARGIN_LEFT} ${baseline} Td (${escapeText(line)}) Tj ET`);
      baseline -= LINE_HEIGHT;
    }
    baseline -= PARAGRAPH_GAP - LINE_HEIGHT;
  });
  const content = `${commands.join("\n")}\n`;

  const objects = [
    "<</Type /Catalog /Pages 2 0 R>>",
    "<</Type /Pages /Kids [3 0 R] /Count 1>>",
    `<</Type /Page /Parent 2 0 R /MediaBox [0 0 ${PAGE_WIDTH} ${PAGE_HEIGHT}] /Resources <</Font <</F1 4 0 R>>>> /Contents 5 0 R>>`,
    "<</Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding>>",
    `<</Length ${Buffer.byteLength(content, "latin1")}>>\nstream\n${content}endstream`,
  ];

  let body = "%PDF-1.4\n";
  const offsets = [];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(body, "latin1"));
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const startxref = Buffer.byteLength(body, "latin1");
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets) body += `${String(offset).padStart(10, "0")} 00000 n \n`;
  body += `trailer\n<</Size ${objects.length + 1} /Root 1 0 R>>\nstartxref\n${startxref}\n%%EOF\n`;
  return Buffer.from(body, "latin1");
}

/**
 * Reads the geometry back out of the file that was just written.
 *
 * Deriving the boxes from the layout constants would be faster and would prove
 * nothing: it would report where the script intended to put the text.
 */
async function extractRegions(bytes, documentId) {
  if (typeof Promise.withResolvers !== "function") {
    Promise.withResolvers = function withResolvers() {
      let resolve;
      let reject;
      const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
      return { promise, resolve, reject };
    };
  }
  const pdfjs = await import(pathToFileURL(PDFJS).href);
  const task = pdfjs.getDocument({ data: new Uint8Array(bytes), useSystemFonts: false });
  const pdf = await task.promise;
  const regions = [];
  let order = 0;
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const viewport = page.getViewport({ scale: 1 });
    const content = await page.getTextContent();
    const lines = content.items
      .filter((item) => typeof item.str === "string" && item.str.trim().length > 0)
      .map((item) => ({
        text: item.str,
        left: item.transform[4],
        right: item.transform[4] + item.width,
        baseline: item.transform[5],
        height: item.height,
      }))
      .sort((left, right) => right.baseline - left.baseline);

    let group = [];
    const flush = () => {
      if (group.length === 0) return;
      const left = Math.min(...group.map((line) => line.left));
      const right = Math.max(...group.map((line) => line.right));
      const top = Math.max(...group.map((line) => line.baseline + line.height));
      const bottom = Math.min(...group.map((line) => line.baseline));
      const scale = (value, extent) => Math.max(0, Math.min(1000, Math.round((value / extent) * 1000)));
      regions.push({
        regionId: `${documentId}-p${pageNumber}-r${order}`,
        pageIndex0: pageNumber - 1,
        pageNumber1: pageNumber,
        order,
        blockType: "paragraph",
        text: group.map((line) => line.text).join(" "),
        // PDF measures up from the bottom of the page; a bounding box measures down from the top.
        bbox1000: [
          scale(left, viewport.width),
          scale(viewport.height - top, viewport.height),
          scale(right, viewport.width),
          scale(viewport.height - bottom, viewport.height),
        ],
        /*
          Not a recognition score. This text was read from the file's own text
          layer rather than recognised from pixels, so there is no estimate to
          report and reporting one below 1 would invent uncertainty that does
          not exist.
        */
        confidence: 1,
        authority: null,
      });
      order += 1;
      group = [];
    };

    for (const line of lines) {
      const previous = group[group.length - 1];
      if (previous && previous.baseline - line.baseline > LINE_HEIGHT + 4) flush();
      group.push(line);
    }
    flush();
    page.cleanup();
  }
  await task.destroy();
  return regions;
}

/* -------------------------------------------------------------------------
   emit
   ------------------------------------------------------------------------- */

async function record(document, bytes) {
  const digest = createHash("sha256").update(bytes).digest("hex");
  const regions = (await extractRegions(bytes, document.documentId)).map((region) => ({
    ...region,
    authority: document.authority,
  }));
  const key = `research/explore_change_receipt_20260905/inputs/${document.filename}`;
  return {
    documentId: document.documentId,
    versionKey: digest,
    sanitizedKey: key,
    ocrJsonKey: `${key}#text-layer`,
    pageCount: 1,
    text: regions.map((region) => region.text).join("\n").trim(),
    inputSha256: `sha256:${digest}`,
    sourceImmutableKey: key,
    regions,
  };
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  mkdirSync(join(OUT, "clause-form"), { recursive: true });

  // 1. The renderer must reproduce a file the site has already committed.
  const rebuilt = renderPdf(SITE_REV_C);
  const committed = readFileSync(join(SITE_PDFS, SITE_REV_C.filename));
  if (Buffer.compare(rebuilt, committed) !== 0) {
    console.error(
      "this renderer does not reproduce the committed revision-C PDF byte for byte; " +
        "the site's generator has changed and nothing below can be trusted",
    );
    process.exit(1);
  }
  console.log(`renderer check: ${SITE_REV_C.filename} reproduced byte for byte`);

  // 2. The three published documents, copied in and checked against the digests
  //    the site committed beside them.
  const siteInputs = JSON.parse(readFileSync(SITE_INPUTS, "utf8"));
  const siteByFilename = new Map(
    siteInputs.map((entry) => [entry.sanitizedKey.split("/").pop(), entry]),
  );
  for (const filename of SITE_PUBLISHED) {
    const source = join(SITE_PDFS, filename);
    const bytes = readFileSync(source);
    const digest = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
    const declared = siteByFilename.get(filename);
    if (!declared) {
      console.error(`${filename} is not in the site's committed inputs`);
      process.exit(1);
    }
    if (declared.inputSha256 !== digest) {
      console.error(`${filename}: bytes ${digest} do not match committed ${declared.inputSha256}`);
      process.exit(1);
    }
    copyFileSync(source, join(OUT, filename));
    console.log(`copied ${filename}  ${bytes.length} bytes  ${digest}`);
  }

  // 3. The revision-B manual in the site's form.
  const revBBytes = renderPdf(SITE_REV_B);
  writeFileSync(join(OUT, SITE_REV_B.filename), revBBytes);
  const revB = await record(SITE_REV_B, revBBytes);
  console.log(`wrote ${SITE_REV_B.filename}  ${revBBytes.length} bytes  ${revB.inputSha256}`);

  // The site fixture set, as the core would be asked to compile it: the
  // revision-B manual this script produced, plus the three published documents
  // with the regions the site committed for them.
  const siteFixture = [revB];
  for (const filename of SITE_PUBLISHED) {
    const declared = siteByFilename.get(filename);
    siteFixture.push({
      ...declared,
      sanitizedKey: `research/explore_change_receipt_20260905/inputs/${filename}`,
      sourceImmutableKey: `research/explore_change_receipt_20260905/inputs/${filename}`,
      ocrJsonKey: `research/explore_change_receipt_20260905/inputs/${filename}#text-layer`,
    });
  }
  writeFileSync(
    join(OUT, "site-fixture.inputs.json"),
    `${JSON.stringify(siteFixture, null, 2)}\n`,
  );

  // 4. The clause-form restatement.
  const clauseForm = [];
  for (const document of [CLAUSE_REV_B, CLAUSE_REV_C, CLAUSE_NOTICE, CLAUSE_LOG]) {
    const bytes = renderPdf(document);
    writeFileSync(join(OUT, "clause-form", document.filename), bytes);
    const entry = await record(document, bytes);
    entry.sanitizedKey = `research/explore_change_receipt_20260905/inputs/clause-form/${document.filename}`;
    entry.sourceImmutableKey = entry.sanitizedKey;
    entry.ocrJsonKey = `${entry.sanitizedKey}#text-layer`;
    clauseForm.push(entry);
    console.log(
      `wrote clause-form/${document.filename}  ${bytes.length} bytes  ${entry.inputSha256}  ${entry.regions.length} regions`,
    );
  }
  writeFileSync(
    join(OUT, "clause-form.inputs.json"),
    `${JSON.stringify(clauseForm, null, 2)}\n`,
  );

  console.log(`wrote ${OUT}/site-fixture.inputs.json and ${OUT}/clause-form.inputs.json`);
}

await main();
