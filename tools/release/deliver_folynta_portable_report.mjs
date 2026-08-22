#!/usr/bin/env node

import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

function usage() {
  return [
    "Usage: node deliver_folynta_portable_report.mjs --plugin-root <directory> --input <artifact.json> --output <report.html> [options]",
    "",
    "Options:",
    "  --ready-timeout-ms <milliseconds>",
    "  --action-timeout-ms <milliseconds>",
    "  --timeout-ms <milliseconds>",
    "  --screenshot <failure.png>",
  ].join("\n");
}

const VALUE_OPTIONS = new Set([
  "plugin-root",
  "input",
  "output",
  "ready-timeout-ms",
  "action-timeout-ms",
  "timeout-ms",
  "screenshot",
]);

function parseArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") return { help: true };
    if (!argument.startsWith("--")) throw new Error(`Unexpected argument: ${argument}`);
    const key = argument.slice(2);
    if (!VALUE_OPTIONS.has(key)) throw new Error(`Unknown argument: ${argument}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${argument}`);
    if (options[key] !== undefined) throw new Error(`${argument} may only be specified once.`);
    options[key] = value;
    index += 1;
  }
  for (const required of ["plugin-root", "input", "output"]) {
    if (!options[required]) throw new Error(`--${required} is required.`);
  }
  return options;
}

function positiveNumber(value, label) {
  if (value === undefined) return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) throw new Error(`${label} must be positive.`);
  return parsed;
}

function containDocumentOverflow(html) {
  const marker = "data-folynta-portable-overflow-fix";
  if (html.includes(marker)) return html;
  const style = [
    `<style ${marker}>`,
    "/* Preserve internal table scrolling while preventing the portable full-bleed header",
    "   from widening a long document by the Windows scrollbar gutter. */",
    "html,body{overflow-x:clip!important}",
    "</style>",
  ].join("");
  if (!html.includes("</head>")) throw new Error("Portable report has no closing head element.");
  return html.replace("</head>", `${style}</head>`);
}

async function run(argv = process.argv.slice(2)) {
  try {
    const options = parseArguments(argv);
    if (options.help) {
      process.stdout.write(`${usage()}\n`);
      return;
    }

    const scriptsRoot = resolve(options["plugin-root"], "skills", "build-report", "scripts");
    const deliverModule = await import(pathToFileURL(resolve(scriptsRoot, "deliver_portable_artifact.mjs")).href);
    const buildModule = await import(pathToFileURL(resolve(scriptsRoot, "build_portable_artifact.mjs")).href);
    const result = await deliverModule.deliverPortableArtifact(
      {
        actionTimeoutMs: positiveNumber(options["action-timeout-ms"], "--action-timeout-ms"),
        inputPath: options.input,
        outputPath: options.output,
        readyTimeoutMs: positiveNumber(options["ready-timeout-ms"], "--ready-timeout-ms"),
        screenshotPath: options.screenshot,
        timeoutMs: positiveNumber(options["timeout-ms"], "--timeout-ms"),
      },
      {
        build(input, buildOptions) {
          return containDocumentOverflow(buildModule.buildPortableArtifact(input, buildOptions));
        },
      },
    );
    process.stdout.write(`${JSON.stringify(result)}\n`);
  } catch (error) {
    const result = error?.deliveryResult ?? {
      ok: false,
      stage: "invocation",
      code: error?.code ?? "invalid_invocation",
      error: error?.message ?? String(error),
    };
    process.stderr.write(`${JSON.stringify(result)}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  await run();
}

export { containDocumentOverflow, parseArguments };
