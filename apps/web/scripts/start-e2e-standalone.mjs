import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = process.cwd();
const standaloneApp = resolve(root, ".next/standalone/apps/web");
const server = resolve(standaloneApp, "server.js");

if (!existsSync(server)) {
  throw new Error(`Standalone build is missing: ${server}`);
}

const staticAssets = resolve(root, ".next/static");
if (!existsSync(staticAssets)) {
  throw new Error(`Standalone build is missing static assets: ${staticAssets}`);
}

const assets = [[staticAssets, resolve(standaloneApp, ".next/static")]];
const publicAssets = resolve(root, "public");
if (existsSync(publicAssets)) {
  assets.push([publicAssets, resolve(standaloneApp, "public")]);
}

for (const [source, destination] of assets) {
  mkdirSync(dirname(destination), { recursive: true });
  cpSync(source, destination, { recursive: true, force: true });
}

process.env.HOSTNAME ??= "127.0.0.1";
process.env.PORT ??= "3000";
await import(pathToFileURL(server).href);
