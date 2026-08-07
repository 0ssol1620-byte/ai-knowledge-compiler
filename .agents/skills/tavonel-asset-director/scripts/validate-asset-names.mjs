import { readdir } from "node:fs/promises";
import { extname, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "../../../..");
const roots = [
  resolve(root, "assets/3d"),
  resolve(root, "assets/brand"),
  resolve(root, "assets/product"),
  resolve(root, "assets/public-proof"),
  resolve(root, "apps/web/public/hero"),
  resolve(root, "apps/web/public/product"),
];
const allowedExtensions = new Set([
  ".avif",
  ".blend",
  ".glb",
  ".json",
  ".md",
  ".mp4",
  ".png",
  ".sha256",
  ".svg",
  ".webm",
  ".webp",
  ".yml",
]);
const canonical =
  /^TAV-[A-Z0-9-]+-T[0-4]-[A-Z0-9-]+-(?:EN|KO|MULTI)-[A-Z0-9-]*\d+x\d+-v\d{2}\.(?:avif|mp4|png|webm|webp)$/;
const failures = [];
let checked = 0;

async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) {
      await walk(path);
      continue;
    }
    if (!allowedExtensions.has(extname(entry.name).toLowerCase())) continue;
    checked += 1;
    if (entry.name.startsWith("TAV-") && !canonical.test(entry.name)) {
      failures.push(relative(root, path).replaceAll("\\", "/"));
    }
  }
}

for (const directory of roots) await walk(directory);
if (failures.length) {
  throw new Error(`Non-canonical asset names:\n${failures.join("\n")}`);
}
console.log(`TAVONEL asset names verified (${checked} files).`);
