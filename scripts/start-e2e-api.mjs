#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const workRoot = join(repoRoot, "work");
const runDirectory = join(
  workRoot,
  `e2e-live-${process.pid}-${randomUUID().slice(0, 8)}`,
);
const dataDirectory = join(runDirectory, "data");
const databasePath = join(runDirectory, "akc.db").replaceAll("\\", "/");
const testSupportKey = "live-e2e-verification-support-key-2026";
const pythonCandidates =
  process.platform === "win32"
    ? [join(repoRoot, ".venv", "Scripts", "python.exe")]
    : [
        join(repoRoot, ".venv", "bin", "python"),
        join(repoRoot, ".venv", "bin", "python3"),
      ];
const python = pythonCandidates.find(existsSync);

if (!python) {
  process.stderr.write(
    `The repository virtual environment is missing. Expected one of: ${pythonCandidates.join(", ")}\n`,
  );
  process.exit(1);
}

mkdirSync(dataDirectory, { recursive: true });

const child = spawn(
  python,
  [
    "-m",
    "uvicorn",
    "akc_api.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8100",
    "--log-level",
    "warning",
  ],
  {
    cwd: repoRoot,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      AKC_ENV: "test",
      AKC_LOG_LEVEL: "WARNING",
      AKC_DATABASE_URL: `sqlite+aiosqlite:///${databasePath}`,
      AKC_DATA_DIR: dataDirectory,
      AKC_WEB_ORIGINS: "http://127.0.0.1:3100",
      AKC_JWT_SECRET:
        "e2e-only-isolated-secret-with-more-than-thirty-two-characters",
      AKC_COOKIE_SECURE: "false",
      AKC_COOKIE_SAMESITE: "lax",
      AKC_OBJECT_STORE_DRIVER: "local",
      AKC_PARSER_PROVIDER: "mock",
      AKC_KNOWLEDGE_PROVIDER: "deterministic",
      AKC_EXTERNAL_OCR_ENABLED: "false",
      AKC_PRIVATE_MODE: "true",
      AKC_LOCAL_BACKGROUND_TASKS: "true",
      AKC_ALLOW_PUBLIC_REGISTRATION: "true",
      AKC_URL_INGESTION_ENABLED: "false",
      AKC_CLAMAV_ENABLED: "false",
      AKC_ALLOW_DEVELOPMENT_ANTIVIRUS_BYPASS: "true",
      AKC_METRICS_ENABLED: "false",
      AKC_OTEL_ENABLED: "false",
      AKC_REDIS_URL: "",
      AKC_TEST_SUPPORT_KEY: testSupportKey,
      AKC_WEBHOOK_DELIVERY_ENABLED: "false",
      AKC_LOCAL_ANALYSIS_WORKER_ENABLED: "true",
    },
    stdio: "inherit",
  },
);

let shuttingDown = false;
let forceTimer;

function removeRunDirectory() {
  const resolvedRunDirectory = resolve(runDirectory);
  const resolvedWorkRoot = resolve(workRoot);
  if (
    dirname(resolvedRunDirectory) !== resolvedWorkRoot ||
    !basename(resolvedRunDirectory).startsWith(`e2e-live-${process.pid}-`)
  ) {
    process.stderr.write(
      `Refusing to remove unexpected E2E path: ${resolvedRunDirectory}\n`,
    );
    return;
  }
  rmSync(resolvedRunDirectory, { recursive: true, force: true });
}

function beginShutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  if (child.exitCode === null && child.signalCode === null) {
    child.kill(signal === "SIGINT" ? "SIGINT" : "SIGTERM");
    forceTimer = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) {
        child.kill("SIGKILL");
      }
    }, 5_000);
    forceTimer.unref();
  }
}

for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.once(signal, () => beginShutdown(signal));
}

child.once("error", (error) => {
  process.stderr.write(`Failed to start the E2E API: ${error.message}\n`);
  removeRunDirectory();
  process.exitCode = 1;
});

child.once("exit", (code, signal) => {
  if (forceTimer) clearTimeout(forceTimer);
  removeRunDirectory();
  if (!shuttingDown && code !== 0) {
    process.stderr.write(
      `The E2E API exited unexpectedly (${signal ?? `code ${code ?? 1}`}).\n`,
    );
  }
  process.exitCode = shuttingDown ? 0 : (code ?? 1);
});
