import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../../../..");
const manifestPath = resolve(root, "assets/registry/asset-manifest.yml");
const manifest = await readFile(manifestPath, "utf8");
const blocks = manifest.split(/\n(?=  - id: )/).slice(1);
const required = [
  "id",
  "title",
  "truth_class",
  "status",
  "source_type",
  "master_path",
  "generated_with_ai",
  "allowed",
  "prohibited",
  "alt_text_en",
];

if (!blocks.length) throw new Error("asset manifest has no assets");
for (const block of blocks) {
  for (const field of required) {
    if (!new RegExp(`\\n?\\s+${field}:`).test(block)) {
      throw new Error(`asset manifest entry missing ${field}`);
    }
  }
  if (!/truth_class: T[0-4]/.test(block)) {
    throw new Error("asset manifest entry has invalid truth class");
  }
}

console.log(`Structara asset manifest verified (${blocks.length} assets).`);
