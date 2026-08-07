import fs from "node:fs";

const css = fs.readFileSync(
  new URL("../../../../apps/web/src/app/tavonel.css", import.meta.url),
  "utf8",
);
const required = [
  "--tv-canvas",
  "--tv-paper",
  "--tv-ink",
  "--tv-brand",
  "--tv-evidence",
];
const missing = required.filter((token) => !css.includes(token));
if (missing.length) {
  console.error(`Missing TAVONEL tokens: ${missing.join(", ")}`);
  process.exit(1);
}
console.log("TAVONEL brand tokens verified.");
