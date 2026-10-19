#!/usr/bin/env node
/**
 * Enforce the public claims pack against what the site actually says.
 *
 * The pack ships editorial rules alongside its numbers — `forbidden` phrasings
 * per claim, `must_say` context, and two claims marked `withheld`. Those rules
 * exist because the numbers are easy to misuse in specific, predictable ways: a
 * 99.98% completion rate reads as accuracy, 80.6 (the unweighted mean of the 8
 * per-type pass rates, not the 7,137/8,413 (84.8%) check pass rate) reads as a
 * grade out of 100, and an average of 99.0%-to-36.9% reads as a promise to
 * whoever is scanning degraded paper.
 *
 * Left to review, those rules hold until someone writes a headline in a hurry.
 * So the mechanical half runs here:
 *
 *   forbidden phrasing   the pack lists exact strings. Grep for them.
 *   withheld figures     a withheld claim's numbers appear nowhere — not in the
 *                        site's sources and not in a published claim's
 *                        headline, must_say, conditions or numbers — except
 *                        as a declared denominator of an approved claim's rate.
 *   pack integrity       the file is generated; a hand-edit is a defect.
 *
 * The exception exists because two rules meet. Every rate carries its
 * denominator, and benchmark-accuracy's failure-study rate is written over the
 * corpus that blind-quality-detection, a withheld claim, also counts. So the
 * generator emits the count with the claim: `declared_denominators` lists each
 * {numerator, denominator} read from an artifact, with that artifact's path and
 * sha256. A withheld number is allowed only inside the counted rate
 * "numerator/denominator (" of an approved claim, only when the declaration's
 * hash is the withheld claim's own evidence hash and one the approved claim
 * cites, and a declaration that no must_say writes any more fails. There is no
 * allowlist in this script; the only way to allow a number is to regenerate
 * the pack with a declaration bound to its receipt.
 *
 * The half that cannot be grepped — whether a number appears *with* its
 * must_say — is enforced structurally instead: lib/claims.ts returns the two
 * together and the components take both. See the note there.
 */

import { existsSync, readFileSync } from "node:fs";
import { globSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const ROOT = path.resolve(import.meta.dirname, "..");
const PACK = path.join(ROOT, "src/data/claims/public-claims-pack.json");

const pack = JSON.parse(readFileSync(PACK, "utf8"));

/** Everything a visitor could read: components, pages, content modules. */
const SOURCES = globSync("src/**/*.{ts,tsx,md,mdx,json}", { cwd: ROOT })
  // globSync returns platform separators, so compare against a normalised
  // path. Filtering on "data/claims/" alone silently matched nothing on
  // Windows and the scanner reported the pack as violating itself.
  .map((file) => file.replaceAll("\\", "/"))
  // The pack states the forbidden phrasings, so of course it contains them.
  // What it publishes is scanned field by field in section 2 instead.
  .filter((file) => !file.startsWith("src/data/claims/"))
  .filter((file) => !file.endsWith(".test.ts") && !file.endsWith(".test.tsx"));

const failures = [];

function scan(needle, describe) {
  for (const relative of SOURCES) {
    const text = readFileSync(path.join(ROOT, relative), "utf8");
    const index = text.indexOf(needle);
    if (index === -1) continue;
    const line = text.slice(0, index).split("\n").length;
    failures.push(`${relative}:${line}  ${describe}`);
  }
}

/* ── 1. forbidden phrasing ───────────────────────────────────────────────── */
for (const claim of pack.claims) {
  for (const phrase of claim.forbidden ?? []) {
    // Several entries are descriptions of a bad construction rather than a
    // literal string ("80.6%를 단독 헤드라인으로 제시하고..."). Those cannot be
    // grepped and are review items; only short literal phrases are scanned.
    if (phrase.length > 40 || phrase.includes("모든 표현")) continue;
    scan(phrase, `forbidden phrasing for ${claim.id}: "${phrase}"`);
  }
}

/* ── 2. withheld figures ─────────────────────────────────────────────────── */
const asList = (value) => (value === undefined ? [] : [value].flat());
const enUS = (value) => value.toLocaleString("en-US");
/** Both plain and thousands-separated, since either could be typed. */
const renderings = (value) =>
  [String(value), enUS(value)].filter((rendering) => rendering.length >= 4);
const counted = (declared) => `${enUS(declared.numerator)}/${enUS(declared.denominator)} (`;
const leaves = (node) =>
  node !== null && typeof node === "object" ? Object.values(node).flatMap(leaves) : [node];

const published = pack.claims.filter((claim) => claim.status !== "withheld");
// What a published claim puts in front of a visitor, field by field.
const publishedText = (claim) => [
  ...["headline_ko", "headline_en", "must_say", "must_say_en"].map((field) => [
    field,
    claim[field] ?? "",
  ]),
  ...(claim.conditions ?? []).map((text, index) => [`conditions[${index}]`, text]),
];

for (const held of pack.claims.filter((c) => c.status === "withheld")) {
  for (const [key, value] of Object.entries(held.numbers ?? {})) {
    if (typeof value !== "number") continue;
    const exposes = `withheld claim ${held.id} exposes ${key}=`;
    const why = held.why_withheld ?? "not publishable";
    for (const rendering of renderings(value)) scan(rendering, `${exposes}${rendering} — ${why}`);

    for (const claim of published) {
      const allowed = (claim.declared_denominators ?? []).filter(
        (declared) =>
          claim.status === "approved" &&
          declared.denominator === value &&
          asList(held.evidence_sha256).includes(declared.evidence_sha256) &&
          asList(claim.evidence_sha256).includes(declared.evidence_sha256),
      );
      for (const [field, text] of publishedText(claim)) {
        const rest = allowed.reduce(
          (left, declared) => left.replaceAll(counted(declared), ""),
          text,
        );
        for (const rendering of renderings(value)) {
          if (!rest.includes(rendering)) continue;
          failures.push(
            `public-claims-pack.json ${claim.id}.${field}  ${exposes}${rendering} ` +
              `outside a declared denominator — ${why}`,
          );
        }
      }
      if (renderings(value).length > 0 && leaves(claim.numbers).includes(value)) {
        failures.push(`public-claims-pack.json ${claim.id}.numbers  ${exposes}${value} — ${why}`);
      }
    }
  }
}

// A declaration no sentence uses is an allowance nobody needs; it goes.
for (const claim of published) {
  for (const declared of claim.declared_denominators ?? []) {
    for (const field of ["must_say", "must_say_en"]) {
      if (claim[field] && !claim[field].includes(counted(declared))) {
        failures.push(
          `public-claims-pack.json ${claim.id}.${field}  denominator ` +
            `${enUS(declared.denominator)} is declared but not written as ${counted(declared)}`,
        );
      }
    }
  }
}

/* ── 3. English context is available for what the site publishes ─────────── */
// Not a failure: a report. Five approved claims ship a Korean must_say with no
// must_say_en, so the page renders the Korean. That is better than dropping a
// required sentence and worse than an English one, and the next regeneration
// can close it.
const missingEnglish = pack.claims
  .filter((claim) => claim.status !== "withheld")
  .filter((claim) => claim.must_say && !claim.must_say_en)
  .map((claim) => claim.id);

/* ── 4. the render copy matches the handed-over pack ─────────────────────── */
// The backend session delivers to docs/evidence/. The web build cannot import
// from outside src/, so a copy lives under src/data/claims/. Two copies of a
// generated file is a drift risk, so the relationship is checked rather than
// trusted: compared as parsed JSON, because the two are formatted differently
// and only the content is the contract.
const DELIVERED = path.resolve(ROOT, "../../docs/evidence/folynta-public-claims-pack.json");
if (existsSync(DELIVERED)) {
  const delivered = JSON.parse(readFileSync(DELIVERED, "utf8"));
  if (JSON.stringify(delivered) !== JSON.stringify(pack)) {
    failures.push(
      "src/data/claims/public-claims-pack.json differs from the delivered " +
        "docs/evidence/folynta-public-claims-pack.json. Copy the delivered " +
        "file over the render copy; do not reconcile them by hand.",
    );
  } else {
    console.log("  delivered pack matches the render copy");
  }
} else {
  console.log("  (no docs/evidence copy present to compare against)");
}

/* ── 5. the pack is generated output ─────────────────────────────────────── */
const expected = {
  schema: "folynta.public-claims-pack.v1",
  claim_count: pack.claims.length,
};
if (pack.schema !== expected.schema) {
  failures.push(
    `public-claims-pack.json: schema is "${pack.schema}", expected "${expected.schema}"`,
  );
}
if (pack.claim_count !== expected.claim_count) {
  failures.push(
    `public-claims-pack.json: claim_count says ${pack.claim_count} but the ` +
      `claims array has ${expected.claim_count} — the file was edited by hand. ` +
      `Regenerate the receipt upstream instead.`,
  );
}
const tally = pack.claims.reduce((counts, claim) => {
  counts[claim.status] = (counts[claim.status] ?? 0) + 1;
  return counts;
}, {});
for (const [status, declared] of Object.entries(pack.counts_by_status)) {
  if ((tally[status] ?? 0) !== declared) {
    failures.push(
      `public-claims-pack.json: counts_by_status.${status} says ${declared}, ` +
        `array has ${tally[status] ?? 0}`,
    );
  }
}

/* ── report ──────────────────────────────────────────────────────────────── */
console.log("public claims pack\n");
console.log(`  receipt   ${pack.receipt_sha256}`);
console.log(
  `  claims    ${pack.claim_count}  ` +
    Object.entries(pack.counts_by_status)
      .map(([status, count]) => `${status}=${count}`)
      .join("  "),
);
console.log(`  scanned   ${SOURCES.length} source files\n`);

if (missingEnglish.length > 0) {
  console.log(
    `  note: ${missingEnglish.length} published claim(s) carry a Korean ` +
      `must_say with no must_say_en, so the page renders the Korean:`,
  );
  for (const id of missingEnglish) console.log(`        ${id}`);
  console.log();
}

if (failures.length === 0) {
  console.log("verify-claims: passed\n");
  process.exit(0);
}

for (const failure of failures) console.log(`  ${failure}`);
console.error(`\nverify-claims: FAILED with ${failures.length} finding(s)\n`);
process.exit(1);
