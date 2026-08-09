#!/usr/bin/env node
/**
 * Enforce the public claims pack against what the site actually says.
 *
 * The pack ships editorial rules alongside its numbers — `forbidden` phrasings
 * per claim, `must_say` context, and two claims marked `withheld`. Those rules
 * exist because the numbers are easy to misuse in specific, predictable ways: a
 * 99.98% completion rate reads as accuracy, an 80.6% pass rate reads as a grade
 * out of 100, and an average of 99.0%-to-36.9% reads as a promise to whoever is
 * scanning degraded paper.
 *
 * Left to review, those rules hold until someone writes a headline in a hurry.
 * So the mechanical half runs here:
 *
 *   forbidden phrasing   the pack lists exact strings. Grep for them.
 *   withheld figures     a withheld claim's numbers must appear nowhere.
 *   pack integrity       the file is generated; a hand-edit is a defect.
 *
 * The half that cannot be greppd — whether a number appears *with* its
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
for (const claim of pack.claims.filter((c) => c.status === "withheld")) {
  const numbers = claim.numbers ?? {};
  for (const [key, value] of Object.entries(numbers)) {
    if (typeof value !== "number") continue;
    // Both plain and thousands-separated, since either could be typed.
    for (const rendering of [String(value), value.toLocaleString("en-US")]) {
      if (rendering.length < 4) continue;
      scan(
        rendering,
        `withheld claim ${claim.id} exposes ${key}=${rendering} — ` +
          `${claim.why_withheld ?? "not publishable"}`,
      );
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
