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
const failures = [];

for (const [, relativePath, expected] of matches) {
  const normalizedPath = relativePath.trim();
  try {
    const bytes = await readFile(resolve(root, normalizedPath));
    const actual = createHash("sha256").update(bytes).digest("hex");
    if (expected && actual !== expected) {
      failures.push(`${normalizedPath}: expected ${expected}, received ${actual}`);
    }
    checked += 1;
  } catch (error) {
    failures.push(`${normalizedPath}: ${error.message}`);
  }
}

if (failures.length > 0) {
  throw new Error(`asset hash verification failed:\n- ${failures.join("\n- ")}`);
}

console.log(`TAVONEL asset hashes verified (${checked} derivatives).`);
