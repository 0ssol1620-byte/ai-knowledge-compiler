import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const buildRoot = join(webRoot, ".next");
const standaloneRoot = join(buildRoot, "standalone", "apps", "web");
const serverPath = join(standaloneRoot, "server.js");

if (!existsSync(serverPath)) {
  throw new Error("Standalone server is missing; run `pnpm build` first.");
}

const publicSource = join(webRoot, "public");
if (existsSync(publicSource)) {
  cpSync(publicSource, join(standaloneRoot, "public"), {
    recursive: true,
    force: true,
  });
}

const staticSource = join(buildRoot, "static");
if (!existsSync(staticSource)) {
  throw new Error("Next static assets are missing from the production build.");
}
const staticTarget = join(standaloneRoot, ".next", "static");
mkdirSync(dirname(staticTarget), { recursive: true });
cpSync(staticSource, staticTarget, { recursive: true, force: true });

process.env.HOSTNAME ||= "127.0.0.1";
process.env.PORT ||= "3000";
process.chdir(standaloneRoot);
await import(pathToFileURL(serverPath).href);
