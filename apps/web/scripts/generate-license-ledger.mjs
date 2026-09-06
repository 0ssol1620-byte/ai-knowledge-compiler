/**
 * Regenerates src/content/license-ledger.md from the asset manifest.
 * The ledger is generated, never hand-edited; a unit test fails on drift.
 *
 *   node scripts/generate-license-ledger.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");

// The renderer is TypeScript, so it is compiled on demand rather than
// duplicated here in JavaScript. One implementation, one behaviour.
// Absolute file URL: a relative specifier here resolved against the wrong
// base and reached for the monorepo root instead of apps/web.
const { renderLicenseLedger } = await import(
  pathToFileURL(
    path.join(root, "src/experience/assets/asset-manifest.ts"),
  ).href
);

const manifest = JSON.parse(
  readFileSync(path.join(root, "src/content/asset-manifest.json"), "utf8"),
);
const out = path.join(root, "src/content/license-ledger.md");
writeFileSync(out, `${renderLicenseLedger(manifest).trimEnd()}\n`, "utf8");
process.stdout.write(`wrote ${out}\n`);
