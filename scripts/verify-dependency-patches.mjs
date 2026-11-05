import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const virtualStore = join(root, "node_modules", ".pnpm");
const packageEntry = readdirSync(virtualStore).find((entry) =>
  entry.startsWith("extract-zip@2.0.1_patch_"),
);

if (!packageEntry) {
  throw new Error("The patched extract-zip package is not installed");
}

const extractZip = createRequire(import.meta.url)(
  join(virtualStore, packageEntry, "node_modules", "extract-zip"),
);
const sandbox = mkdtempSync(join(tmpdir(), "akc-extract-zip-patch-"));
const archive = join(sandbox, "malicious-symlink.zip");
const destination = join(sandbox, "output");
const escapedTarget = join(dirname(sandbox), String(Date.now()) + "-escaped-target");
const python = [
  "import stat",
  "import sys",
  "import zipfile",
  "",
  "archive, target = sys.argv[1], sys.argv[2]",
  "entry = zipfile.ZipInfo('escape-link')",
  "entry.create_system = 3",
  "entry.external_attr = (stat.S_IFLNK | 0o777) << 16",
  "with zipfile.ZipFile(archive, 'w') as bundle:",
  "    bundle.writestr(entry, target)",
  "",
].join("\n");

function createMaliciousArchive() {
  const candidates = process.platform === "win32"
    ? [["py", ["-3"]], ["python", []]]
    : [["python3", []], ["python", []]];
  for (const [command, prefix] of candidates) {
    const result = spawnSync(
      command,
      [...prefix, "-c", python, archive, escapedTarget],
      { encoding: "utf8" },
    );
    if (!result.error && result.status === 0) return;
  }
  throw new Error("Python is required to build the dependency security fixture");
}

try {
  createMaliciousArchive();
  let rejection;
  try {
    await extractZip(archive, { dir: destination });
  } catch (error) {
    rejection = error;
  }
  if (!rejection || !String(rejection.message).includes("Out of bound symlink target")) {
    throw new Error("extract-zip accepted an out-of-root symlink target");
  }
  if (existsSync(escapedTarget)) {
    throw new Error("extract-zip materialized the escaped symlink target");
  }
  console.log("Patched dependency security checks passed.");
} finally {
  rmSync(sandbox, { recursive: true, force: true });
}
