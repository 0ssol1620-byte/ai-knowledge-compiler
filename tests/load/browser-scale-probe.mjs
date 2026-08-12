import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const NONPRODUCTION_CONFIRMATION = "NONPRODUCTION_LOAD_ONLY";
const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");
const requireFromWeb = createRequire(join(ROOT, "apps/web/package.json"));
const { chromium } = requireFromWeb("@playwright/test");

const PROFILE_EXPECTATIONS = {
  processing_ui_1000_pages: { key: "pages", value: 1000 },
  workspace_10000_blocks: { key: "blocks", value: 10000 },
  graph_5000_nodes: { key: "graph_nodes", value: 5000 },
};

function fail(message) {
  throw new Error(message);
}

function requireEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) fail(`${name} is required`);
  return value;
}

function sha256Bytes(value) {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function parseProfile() {
  const index = process.argv.indexOf("--profile");
  const value = index >= 0 ? process.argv[index + 1] : null;
  if (!value || !Object.hasOwn(PROFILE_EXPECTATIONS, value)) {
    fail(`--profile must be one of ${Object.keys(PROFILE_EXPECTATIONS).join(", ")}`);
  }
  return value;
}

function guardedOrigin() {
  if (process.env.AKC_LOAD_CONFIRM !== NONPRODUCTION_CONFIRMATION) {
    fail(`AKC_LOAD_CONFIRM=${NONPRODUCTION_CONFIRMATION} is required`);
  }
  const origin = requireEnv("AKC_BASE_URL").replace(/\/$/, "");
  const parsed = new URL(origin);
  const localHosts = new Set(["localhost", "127.0.0.1", "::1"]);
  const allowed = new Set(
    (process.env.AKC_ALLOWED_REMOTE_ORIGINS || "")
      .split(",")
      .map((item) => item.trim().replace(/\/$/, ""))
      .filter(Boolean),
  );
  if (
    !localHosts.has(parsed.hostname) &&
    (parsed.protocol !== "https:" ||
      process.env.AKC_ALLOW_REMOTE_SYNTHETIC !== "true" ||
      !allowed.has(origin))
  ) {
    fail(
      "remote browser scale requires HTTPS, AKC_ALLOW_REMOTE_SYNTHETIC=true, " +
        "and an exact AKC_ALLOWED_REMOTE_ORIGINS match",
    );
  }
  if (parsed.pathname !== "/" || parsed.search || parsed.hash) {
    fail("AKC_BASE_URL must be an origin without a path, query, or fragment");
  }
  return origin;
}

function loadAttestation(profile, origin) {
  const path = resolve(requireEnv("AKC_BROWSER_FIXTURE_ATTESTATION"));
  const raw = readFileSync(path);
  const value = JSON.parse(raw.toString("utf8"));
  const expectation = PROFILE_EXPECTATIONS[profile];
  if (
    value.schema_version !== "1.0.0" ||
    value.profile !== profile ||
    value.synthetic !== true ||
    value.customer_data !== false ||
    value.production !== false ||
    !["development", "staging", "performance"].includes(value.environment) ||
    value.target_origin !== origin ||
    typeof value.route_path !== "string" ||
    !value.route_path.startsWith("/") ||
    value.route_path.startsWith("//") ||
    !/^[0-9a-f]{40}$/.test(value.target_revision || "") ||
    !/^sha256:[0-9a-f]{64}$/.test(value.deployment_revision_evidence_sha256 || "") ||
    !/^sha256:[0-9a-f]{64}$/.test(value.fixture_sha256 || "") ||
    value.dataset?.[expectation.key] !== expectation.value
  ) {
    fail("browser fixture attestation is incomplete or does not bind the exact profile");
  }
  return { path, value, sha256: sha256Bytes(raw) };
}

function percentile(values, quantile) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * quantile) - 1)];
}

const profile = parseProfile();
const origin = guardedOrigin();
const attestation = loadAttestation(profile, origin);
const storageState = resolve(requireEnv("AKC_BROWSER_STORAGE_STATE"));
const observationPath = resolve(requireEnv("AKC_BROWSER_OBSERVATION_PATH"));
if (!existsSync(storageState)) fail("AKC_BROWSER_STORAGE_STATE does not exist");
if (
  !existsSync(dirname(observationPath)) ||
  !statSync(dirname(observationPath)).isDirectory()
) {
  fail("AKC_BROWSER_OBSERVATION_PATH directory does not exist");
}

const browser = await chromium.launch({ headless: true });
let context;
try {
  context = await browser.newContext({ storageState });
  const page = await context.newPage();
  await page.addInitScript(() => {
    globalThis.__akcObservedLongTasks = [];
    if (typeof PerformanceObserver !== "undefined") {
      try {
        const observer = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            globalThis.__akcObservedLongTasks.push(entry.duration);
          }
        });
        observer.observe({ type: "longtask", buffered: true });
      } catch {
        // The raw observation records zero when the browser lacks Long Tasks support.
      }
    }
  });

  const started = Date.now();
  await page.goto(`${origin}${attestation.value.route_path}`, {
    waitUntil: "domcontentloaded",
    timeout: 120_000,
  });
  await page.waitForFunction(
    ({ expectedProfile, expectedRevision, expectedFixture }) => {
      const evidence = globalThis.__AKC_SCALE_EVIDENCE__;
      return (
        evidence?.ready === true &&
        evidence.profile === expectedProfile &&
        evidence.target_revision === expectedRevision &&
        evidence.fixture_sha256 === expectedFixture
      );
    },
    {
      expectedProfile: profile,
      expectedRevision: attestation.value.target_revision,
      expectedFixture: attestation.value.fixture_sha256,
    },
    { timeout: 120_000 },
  );
  const readyMs = Date.now() - started;
  const appEvidence = await page.evaluate(() => globalThis.__AKC_SCALE_EVIDENCE__);
  const expectation = PROFILE_EXPECTATIONS[profile];
  if (appEvidence?.dataset?.[expectation.key] !== expectation.value) {
    fail(`UI did not observe exact ${expectation.key}=${expectation.value}`);
  }

  const cdp = await context.newCDPSession(page);
  const domCounters = await cdp.send("Memory.getDOMCounters");
  await cdp.send("Performance.enable");
  const performance = await cdp.send("Performance.getMetrics");
  const heapMetric = performance.metrics.find(
    (metric) => metric.name === "JSHeapUsedSize",
  );
  const longTasks = await page.evaluate(() => globalThis.__akcObservedLongTasks || []);
  const observation = {
    schema_version: "1.0.0",
    profile,
    nonproduction_only: true,
    production_slo_proven: false,
    target_origin: origin,
    target_revision: attestation.value.target_revision,
    deployment_revision_evidence_sha256:
      attestation.value.deployment_revision_evidence_sha256,
    fixture_sha256: attestation.value.fixture_sha256,
    fixture_attestation_sha256: attestation.sha256,
    dataset: appEvidence.dataset,
    virtualization: appEvidence.virtualization,
    metrics: {
      ready_ms: readyMs,
      heap_peak_bytes: Number(heapMetric?.value || 0),
      dom_nodes_peak: Number(domCounters.nodes),
      long_task_p95_ms: percentile(longTasks.map(Number), 0.95),
    },
    thresholds: {
      ready_ms: 10_000,
      heap_peak_bytes: 536_870_912,
      dom_nodes_peak: 5_000,
      long_task_p95_ms: 200,
    },
  };
  const passed =
    observation.metrics.ready_ms <= observation.thresholds.ready_ms &&
    observation.metrics.heap_peak_bytes <= observation.thresholds.heap_peak_bytes &&
    observation.metrics.dom_nodes_peak <= observation.thresholds.dom_nodes_peak &&
    observation.metrics.long_task_p95_ms <= observation.thresholds.long_task_p95_ms;
  writeFileSync(
    observationPath,
    `${JSON.stringify({ ...observation, passed }, null, 2)}\n`,
    { encoding: "utf8", mode: 0o600 },
  );
  if (!passed) fail("browser scale thresholds failed; inspect the raw observation");
} finally {
  if (context) await context.close();
  await browser.close();
}
