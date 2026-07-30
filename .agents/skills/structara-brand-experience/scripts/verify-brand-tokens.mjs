import fs from "node:fs";

const css = fs.readFileSync(
  new URL("../../../../apps/web/src/app/structara.css", import.meta.url),
  "utf8",
);
const required = [
  "--st-canvas",
  "--st-paper",
  "--st-ink",
  "--st-brand",
  "--st-evidence",
];
const missing = required.filter((token) => !css.includes(token));
if (missing.length) {
  console.error(`Missing Structara tokens: ${missing.join(", ")}`);
  process.exit(1);
}
console.log("Structara brand tokens verified.");
