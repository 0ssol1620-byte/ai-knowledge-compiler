#!/usr/bin/env node
/**
 * Blueprint conformance — DESIGN_MASTER_V3 [확정] items that can be checked
 * from source.
 *
 * Written because an audit is a photograph and this needs to be a gate. Three
 * of the [확정] items below were found unmet by reading the tree by hand; every
 * one of them would drift back within a wave or two without something that
 * fails a build.
 *
 * TWO POPULATIONS, TWO RULES. §23.2 removes the legacy stylesheets wave by
 * wave, so holding them to the same standard as new work would mean either a
 * permanently red gate or 400 edits to files scheduled for deletion. So:
 *
 *   src/styles/**      the V3 layer. Zero tolerance. This layer *is* the
 *                      blueprint made real, and a violation here is a
 *                      violation of the thing itself.
 *   everything else    legacy. A ratchet against BASELINE below: counts may
 *                      fall and may not rise. Deleting a legacy sheet lowers
 *                      the number; adding a rule to one cannot raise it.
 *
 * The ratchet numbers are measurements, not targets. Update them downward when
 * work removes violations; never upward to make a build pass. Same rule as
 * lighthouserc.json, and for the same reason.
 *
 * WHAT IS DELIBERATELY NOT CHECKED. Anything needing rendered output —
 * contrast ratios (§18.4), luminance histograms (§25.3), the squint test
 * (§25.4). Those live in the Playwright suites, which have a browser. A
 * source scan that guessed at them would report false confidence.
 */

import { readFileSync } from "node:fs";
import { globSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const ROOT = path.resolve(import.meta.dirname, "..");

/**
 * §7.3 [확정]: "본문·UI 최소 크기 12px."
 * §20 [확정]: "경계를 4개로 정리한다 — 1280 · 1024 · 768."
 */
const MIN_FONT_PX = 12;
const ALLOWED_BREAKPOINTS = new Set([1280, 1024, 768]);

/**
 * Measured 2026-08-08. Lower these when a wave removes violations. Raising one
 * is not a fix — it is a decision to let the blueprint drift, and it needs to
 * be argued in decision.md rather than committed here.
 */
const BASELINE = {
  "font-size-below-12px": 422,
  "non-conformant-breakpoint": 39,
};

/** Comments hold example hex and issue numbers; scanning them reports noise. */
function stripComments(css) {
  // Replaced with equal-length whitespace so reported line numbers stay true.
  return css.replace(/\/\*[\s\S]*?\*\//g, (match) =>
    match.replace(/[^\n]/g, " "),
  );
}

function lineOf(css, index) {
  return css.slice(0, index).split("\n").length;
}

const FINDINGS = [];

function report(rule, file, line, detail) {
  FINDINGS.push({ rule, file, line, detail });
}

/** §7.3 — body and UI text never below 12px. */
function checkFontSize(file, css) {
  const pattern = /font-size:\s*([0-9.]+)(px|rem|em)/g;
  for (const match of css.matchAll(pattern)) {
    const value = Number(match[1]);
    const unit = match[2];
    // rem/em are relative; only an absolute px value can be checked here
    // without resolving the cascade, and the tree uses px throughout.
    if (unit !== "px" || value >= MIN_FONT_PX) continue;
    report(
      "font-size-below-12px",
      file,
      lineOf(css, match.index),
      `${value}px — §7.3 sets ${MIN_FONT_PX}px as the floor`,
    );
  }
}

/**
 * §20 — three viewport boundaries.
 *
 * `@container` is explicitly exempt: §20 asks facing components to move to
 * container queries precisely so they stop depending on viewport width. An
 * earlier hand audit counted a container query as a breakpoint violation and
 * reported a conformant file as broken.
 */
function checkBreakpoints(file, css) {
  const pattern = /@(media|container)([^{]*)\{/g;
  for (const match of css.matchAll(pattern)) {
    if (match[1] === "container") continue;
    const query = match[2];
    for (const width of query.matchAll(/(?:min|max)-width:\s*([0-9.]+)px/g)) {
      const px = Number(width[1]);
      if (ALLOWED_BREAKPOINTS.has(px)) continue;
      report(
        "non-conformant-breakpoint",
        file,
        lineOf(css, match.index),
        `${px}px — §20 allows ${[...ALLOWED_BREAKPOINTS].sort((a, b) => b - a).join(" / ")}`,
      );
    }
  }
}

const CSS_FILES = globSync("src/**/*.css", { cwd: ROOT }).sort();
if (CSS_FILES.length === 0) {
  console.error("verify-blueprint: found no stylesheets — is the glob wrong?");
  process.exit(2);
}

for (const relative of CSS_FILES) {
  const css = stripComments(
    readFileSync(path.join(ROOT, relative), "utf8"),
  );
  const file = relative.replaceAll("\\", "/");
  checkFontSize(file, css);
  checkBreakpoints(file, css);
}

const isV3 = (file) => file.startsWith("src/styles/");
const v3 = FINDINGS.filter((f) => isV3(f.file));
const legacy = FINDINGS.filter((f) => !isV3(f.file));

let failed = false;

console.log("DESIGN_MASTER_V3 conformance\n");

// ── the V3 layer: zero tolerance ─────────────────────────────────────────
if (v3.length === 0) {
  console.log(`  V3 layer (src/styles)   clean across ${CSS_FILES.length} stylesheets`);
} else {
  failed = true;
  console.log(`  V3 layer (src/styles)   ${v3.length} violation(s)\n`);
  for (const f of v3) {
    console.log(`    ${f.file}:${f.line}  [${f.rule}]  ${f.detail}`);
  }
  console.log();
}

// ── legacy: a ratchet ────────────────────────────────────────────────────
const counts = {};
for (const f of legacy) counts[f.rule] = (counts[f.rule] ?? 0) + 1;

console.log("\n  legacy sheets (ratchet — may fall, may not rise)\n");
for (const [rule, baseline] of Object.entries(BASELINE)) {
  const actual = counts[rule] ?? 0;
  const delta = actual - baseline;
  const state =
    delta > 0 ? `ROSE by ${delta}` : delta < 0 ? `fell by ${-delta}` : "held";
  console.log(
    `    ${rule.padEnd(28)} ${String(actual).padStart(4)} / ${String(baseline).padEnd(4)}  ${state}`,
  );
  if (delta > 0) {
    failed = true;
    for (const f of legacy.filter((x) => x.rule === rule).slice(0, 10)) {
      console.log(`        ${f.file}:${f.line}  ${f.detail}`);
    }
  }
  if (delta < 0) {
    console.log(
      `        lower BASELINE.${JSON.stringify(rule)} to ${actual} to keep the gain`,
    );
  }
}

console.log();
if (failed) {
  console.error("verify-blueprint: FAILED\n");
  process.exit(1);
}
console.log("verify-blueprint: passed\n");
