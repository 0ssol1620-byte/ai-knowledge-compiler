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
 *                        headline, must_say, conditions or numbers, in any
 *                        digit-group form — except as a declared denominator
 *                        of an approved claim's rate.
 *   pack integrity       the file is generated; a hand-edit is a defect.
 *
 * "Any digit-group form": 5,116 reads the same written with a space, a no-break,
 * narrow no-break, thin, figure or ideographic space, a tab, a period, an
 * apostrophe or U+2019, an underscore, a middle dot, an Arabic thousands
 * separator (U+066C), or in fullwidth digits. So the text is folded before
 * matching — NFKC, then a thousands-grouped numeral loses its separators — and
 * the match stays a substring test against the plain and the folded spelling.
 * A numeral is thousands-grouped when it is one to three digits, then groups
 * of exactly three, every group joined by the same separator, and it is not
 * the head or tail of a longer chain of that separator: 1 005 116 folds, and
 * 2015.11.6, v5.1.16 and 1.5.116 are left as typed. It still over-matches on
 * purpose: 5116 is found inside 15116 and inside 5,116.0, and a withheld
 * decimal such as 0.723 also matches its bare digits. A false alarm fails the
 * build where someone sees it; a miss publishes the number.
 *
 * The exception exists because two rules meet. Every rate carries its
 * denominator, and benchmark-accuracy's failure-study rate is written over the
 * corpus that blind-quality-detection, a withheld claim, also counts. So the
 * generator emits the count with the claim: `declared_denominators` lists each
 * {numerator, denominator} read from an artifact, with the two fields it read
 * and that artifact's path and sha256. A withheld number is allowed only inside
 * the counted rate "numerator/denominator (" of an approved claim, only when
 * the declaration's hash is the withheld claim's own evidence hash and one the
 * approved claim cites, only when the declaration reads its denominator from
 * the field the withheld claim withholds (its numbers key), and a declaration
 * that no must_say writes any more fails. The declaration is checked against
 * its artifact, not trusted: numerator_field and denominator_field must be two
 * different fields, the counts must be a rate (0 <= numerator <= denominator,
 * denominator > 0), the cited file must hash to the declared sha256, and the
 * two fields must hold the declared counts. So a count edited together with
 * the sentence that writes it fails here, and so does a declaration that reads
 * both counts from corpus_cases ("5,116/5,116 (100.0%)"). There is no
 * allowlist in this script.
 *
 * receipt_sha256 is a hash of the pack's own content, not a signature. The
 * generator's tests recompute it over both shipped copies, which catches a
 * hand-edit that leaves the old receipt in place; an edit that recomputes it
 * passes that test and is caught only by the checks here and the generator's
 * other tests, or not at all.
 *
 * The half that cannot be grepped — whether a number appears *with* its
 * must_say — is enforced structurally instead: lib/claims.ts returns the two
 * together and the components take both. See the note there.
 */

import { createHash } from "node:crypto";
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

/**
 * One spelling for every way a number can be typed: NFKC turns fullwidth
 * digits into ASCII and a no-break, narrow no-break, thin, figure or
 * ideographic space into a space, then a thousands-grouped numeral (see the
 * header) loses its separators. Only separators inside such a numeral go, so a
 * plain 5116 or 5,116 is either left as typed or folded to a string that
 * contains 5116: matching both spellings against the folded text finds
 * everything the plain text matched.
 */
const GROUPED =
  /(?<!\d)\d{1,3}([ \t   .,'’_·٬])\d{3}(?:\1\d{3})*(?!\d|\1\d)/g;
const fold = (text) => {
  const normal = text.normalize("NFKC");
  return normal.replace(GROUPED, (numeral, separator, at) =>
    // The tail of a longer chain: 1.5.116 is not 1 and 5,116.
    normal[at - 1] === separator && /\d/.test(normal[at - 2] ?? "")
      ? numeral
      : numeral.replaceAll(separator, ""),
  );
};

const TEXTS = SOURCES.map((relative) => {
  const raw = readFileSync(path.join(ROOT, relative), "utf8");
  return { relative, raw, folded: fold(raw) };
});

function scan(needle, describe, form = "raw") {
  for (const file of TEXTS) {
    const text = file[form];
    const index = text.indexOf(needle);
    if (index === -1) continue;
    // fold() keeps every newline, so the line number holds in either form.
    const line = text.slice(0, index).split("\n").length;
    failures.push(`${file.relative}:${line}  ${describe}`);
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
/** Plain and thousands-separated, as typed and folded: matched against folded text. */
const renderings = (value) => [
  ...new Set(
    [String(value), enUS(value)]
      .filter((rendering) => rendering.length >= 4)
      .flatMap((rendering) => [rendering, fold(rendering)]),
  ),
];
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
    for (const rendering of renderings(value)) {
      scan(rendering, `${exposes}${rendering} — ${why}`, "folded");
    }
    const exposedIn = (leaf) =>
      typeof leaf === "number"
        ? leaf === value
        : typeof leaf === "string" &&
          renderings(value).some((rendering) => fold(leaf).includes(rendering));

    for (const claim of published) {
      const allowed = (claim.declared_denominators ?? []).filter(
        (declared) =>
          claim.status === "approved" &&
          declared.denominator === value &&
          declared.denominator_field === key &&
          asList(held.evidence_sha256).includes(declared.evidence_sha256) &&
          asList(claim.evidence_sha256).includes(declared.evidence_sha256),
      );
      for (const [field, text] of publishedText(claim)) {
        // Only the exact counted rate the generator writes is allowed; the
        // rest is folded, so a second spelling of the number is still found.
        const rest = fold(
          allowed.reduce((left, declared) => left.replaceAll(counted(declared), ""), text),
        );
        for (const rendering of renderings(value)) {
          if (!rest.includes(rendering)) continue;
          failures.push(
            `public-claims-pack.json ${claim.id}.${field}  ${exposes}${rendering} ` +
              `outside a declared denominator — ${why}`,
          );
        }
      }
      if (renderings(value).length > 0 && leaves(claim.numbers).some(exposedIn)) {
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

// The declaration is the one allowance above, so it is read back from the
// bytes it cites rather than trusted: two different fields, a rate, a file
// that hashes to the declared digest, and fields that still hold the counts.
// Reading one field twice reads back correctly (review of #120 R18), so the
// fields have to differ.
const REPOSITORY = path.resolve(ROOT, "../..");
for (const claim of pack.claims) {
  for (const declared of claim.declared_denominators ?? []) {
    const where = `public-claims-pack.json ${claim.id}.declared_denominators`;
    const { numerator, denominator } = declared;
    if (declared.numerator_field === declared.denominator_field) {
      failures.push(
        `${where}  numerator and denominator are both read from ${declared.denominator_field}`,
      );
    }
    if (!(0 <= numerator && numerator <= denominator && 0 < denominator)) {
      failures.push(`${where}  ${numerator}/${denominator} is not a rate`);
    }
    const file = path.join(REPOSITORY, String(declared.evidence));
    if (typeof declared.evidence !== "string" || !existsSync(file)) {
      failures.push(`${where}  cites ${declared.evidence}, which does not exist in this checkout`);
      continue;
    }
    const bytes = readFileSync(file);
    const digest = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
    if (digest !== declared.evidence_sha256) {
      failures.push(
        `${where}  ${declared.evidence} hashes to ${digest}, not ${declared.evidence_sha256}`,
      );
      continue;
    }
    const artifact = JSON.parse(bytes.toString("utf8").replace(/^﻿/, ""));
    for (const side of ["numerator", "denominator"]) {
      const field = declared[`${side}_field`];
      if (typeof field === "string" && Object.hasOwn(artifact, field)) {
        if (artifact[field] === declared[side]) continue;
      }
      failures.push(
        `${where}  ${side} ${declared[side]} is not what ${declared.evidence} holds ` +
          `in ${field ?? "(no field named)"}`,
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
