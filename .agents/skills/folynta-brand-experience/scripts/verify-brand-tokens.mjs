import fs from "node:fs";

const css = fs.readFileSync(
  new URL("../../../../apps/web/src/app/folynta.css", import.meta.url),
  "utf8",
);
const required = [
  "--fl-canvas",
  "--fl-paper",
  "--fl-ink",
  "--fl-brand",
  "--fl-evidence",
];
const missing = required.filter((token) => !css.includes(token));
if (missing.length) {
  console.error(`Missing FOLYNTA tokens: ${missing.join(", ")}`);
  process.exit(1);
}
console.log("FOLYNTA brand tokens verified.");
