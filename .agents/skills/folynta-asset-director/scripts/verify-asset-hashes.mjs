import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../../../..");
const manifest = await readFile(
  resolve(root, "assets/registry/asset-manifest.yml"),
  "utf8",
);
const matches = [...manifest.matchAll(/path: ([^\n]+)\n\s+sha256: "([^"]*)"/g)];
let checked = 0;

for (const [, relativePath, expected] of matches) {
  const bytes = await readFile(resolve(root, relativePath.trim()));
  const actual = createHash("sha256").update(bytes).digest("hex");
  if (expected && actual !== expected) {
    throw new Error(`hash mismatch: ${relativePath}`);
  }
  checked += 1;
}

console.log(`FOLYNTA asset hashes verified (${checked} derivatives).`);
