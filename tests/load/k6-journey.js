import crypto from "k6/crypto";
import exec from "k6/execution";
import http from "k6/http";
import { check, fail, sleep } from "k6";
import { Trend } from "k6/metrics";

const journeyDuration = new Trend("akc_journey_duration", true);

function boundedInteger(name, fallback, minimum, maximum) {
  const value = Number.parseInt(__ENV[name] || String(fallback), 10);
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return value;
}

const baseUrl = (__ENV.AKC_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const parsed = new URL(baseUrl);
const localHosts = new Set(["localhost", "127.0.0.1", "::1"]);
if (!localHosts.has(parsed.hostname)) {
  const allowedRemoteOrigins = new Set(
    (__ENV.AKC_ALLOWED_REMOTE_ORIGINS || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
  );
  if (
    parsed.protocol !== "https:" ||
    __ENV.AKC_ALLOW_REMOTE_SYNTHETIC !== "true" ||
    __ENV.AKC_SYNTHETIC_CONFIRM !== "NONPRODUCTION_SYNTHETIC_ONLY" ||
    !allowedRemoteOrigins.has(baseUrl)
  ) {
    throw new Error(
      "remote mutation requires HTTPS, AKC_ALLOW_REMOTE_SYNTHETIC=true, " +
        "AKC_SYNTHETIC_CONFIRM=NONPRODUCTION_SYNTHETIC_ONLY, and an exact " +
        "AKC_ALLOWED_REMOTE_ORIGINS match",
    );
  }
}

for (const name of ["AKC_TEST_EMAIL", "AKC_TEST_PASSWORD", "AKC_TEST_PROJECT_ID"]) {
  if (!__ENV[name]) throw new Error(`${name} is required`);
}

export const options = {
  scenarios: {
    synthetic_journey: {
      executor: "shared-iterations",
      vus: boundedInteger("AKC_VUS", 1, 1, 10),
      iterations: boundedInteger("AKC_ITERATIONS", 1, 1, 100),
      maxDuration: "15m",
      gracefulStop: "30s",
    },
  },
  thresholds: {
    checks: ["rate>0.995"],
    http_req_failed: ["rate<0.01"],
    akc_journey_duration: ["p(95)<90000"],
  },
};

function jsonHeaders(extra = {}) {
  return { "Content-Type": "application/json", Accept: "application/json", ...extra };
}

function assertJson(response, expectedStatus, label) {
  const passed = check(response, {
    [`${label} status ${expectedStatus}`]: (value) => value.status === expectedStatus,
    [`${label} is JSON`]: (value) =>
      String(value.headers["Content-Type"] || "").includes("application/json"),
  });
  if (!passed) fail(`${label} failed with HTTP ${response.status}`);
  return response.json();
}

function relativeOrAbsolute(value) {
  return value.startsWith("/") ? `${baseUrl}${value}` : value;
}

export default function () {
  const started = Date.now();
  let documentId = null;

  const login = http.post(
    `${baseUrl}/v1/auth/login`,
    JSON.stringify({
      email: __ENV.AKC_TEST_EMAIL,
      password: __ENV.AKC_TEST_PASSWORD,
    }),
    { headers: jsonHeaders(), tags: { endpoint: "login" } },
  );
  assertJson(login, 200, "login");

  const source =
    `AKC synthetic load fixture\n` +
    `vu=${exec.vu.idInTest} iteration=${exec.scenario.iterationInTest}\n` +
    `This content is synthetic and contains no customer data.\n`.repeat(20);
  const digest = crypto.sha256(source, "hex");

  try {
    const initiate = http.post(
      `${baseUrl}/v1/uploads/initiate`,
      JSON.stringify({
        project_id: __ENV.AKC_TEST_PROJECT_ID,
        filename: `synthetic-${exec.vu.idInTest}-${exec.scenario.iterationInTest}.txt`,
        size: source.length,
        content_type: "text/plain",
        sha256: digest,
      }),
      {
        headers: jsonHeaders({ "Idempotency-Key": crypto.sha256(source, "hex") }),
        tags: { endpoint: "upload_initiate" },
      },
    );
    const initiated = assertJson(initiate, 201, "upload initiate");
    documentId = initiated.document_id;

    const upload = http.put(relativeOrAbsolute(initiated.upload_url), source, {
      headers: initiated.headers || { "Content-Type": "text/plain" },
      timeout: "30s",
      tags: { endpoint: "upload_transfer" },
    });
    check(upload, {
      "upload transfer succeeds": (response) => [200, 204].includes(response.status),
    });
    if (![200, 204].includes(upload.status)) {
      fail(`upload transfer failed with HTTP ${upload.status}`);
    }

    const complete = http.post(
      `${baseUrl}/v1/uploads/${initiated.upload_id}/complete`,
      JSON.stringify({ sha256: digest }),
      {
        headers: jsonHeaders({ "Idempotency-Key": `complete-${digest}` }),
        tags: { endpoint: "upload_complete" },
      },
    );
    assertJson(complete, 200, "upload complete");

    const analyze = http.post(`${baseUrl}/v1/documents/${documentId}/analyze`, null, {
      headers: jsonHeaders({ "Idempotency-Key": `analyze-${digest}` }),
      timeout: "60s",
      tags: { endpoint: "analyze" },
    });
    assertJson(analyze, 202, "analyze");

    let analysis = null;
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const response = http.get(`${baseUrl}/v1/documents/${documentId}/analysis`, {
        tags: { endpoint: "analysis_poll" },
      });
      analysis = assertJson(response, 200, "analysis poll");
      if (["completed", "failed", "dead_letter"].includes(analysis.status)) break;
      sleep(0.5);
    }
    if (!analysis || analysis.status !== "completed") {
      fail(`analysis did not complete: ${analysis ? analysis.status : "unknown"}`);
    }

    const estimate = http.get(`${baseUrl}/v1/documents/${documentId}/estimate`, {
      tags: { endpoint: "estimate" },
    });
    const estimated = assertJson(estimate, 200, "estimate");
    check(estimated, {
      "estimate is bounded": (value) =>
        Number(value.expected) >= 0 && Number(value.upper_bound) >= Number(value.expected),
    });

    const compile = http.post(
      `${baseUrl}/v1/documents/${documentId}/compile`,
      JSON.stringify({
        route_profile: "parse_balanced_v1",
        external_processing_consent: false,
        output_profiles: ["portable_markdown_v1"],
      }),
      {
        headers: jsonHeaders({ "Idempotency-Key": `compile-${digest}` }),
        timeout: "30s",
        tags: { endpoint: "compile" },
      },
    );
    const job = assertJson(compile, 202, "compile");

    const events = http.get(`${baseUrl}/v1/jobs/${job.id}/events`, {
      headers: { Accept: "text/event-stream" },
      responseType: "text",
      timeout: "90s",
      tags: { endpoint: "sse" },
    });
    check(events, {
      "SSE responds successfully": (response) => response.status === 200,
      "SSE contains a terminal event": (response) =>
        String(response.body).includes("job.completed.v1") ||
        String(response.body).includes("job.failed.v1"),
    });

    let terminal = null;
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const response = http.get(`${baseUrl}/v1/jobs/${job.id}`, {
        tags: { endpoint: "job_poll" },
      });
      terminal = assertJson(response, 200, "job poll");
      if (["completed", "failed", "cancelled"].includes(terminal.status)) break;
      sleep(0.5);
    }
    if (!terminal || terminal.status !== "completed") {
      fail(`job did not complete: ${terminal ? terminal.status : "unknown"}`);
    }

    const exportResponse = http.post(
      `${baseUrl}/v1/projects/${__ENV.AKC_TEST_PROJECT_ID}/exports`,
      JSON.stringify({ document_id: documentId, export_type: "portable", options: {} }),
      {
        headers: jsonHeaders(),
        timeout: "60s",
        tags: { endpoint: "export" },
      },
    );
    const exported = assertJson(exportResponse, 201, "export");
    check(exported, {
      "export has checksum": (value) =>
        value.status === "completed" && /^[0-9a-f]{64}$/.test(value.sha256 || ""),
    });
  } finally {
    if (documentId) {
      const removal = http.del(`${baseUrl}/v1/documents/${documentId}`, null, {
        headers: {
          Accept: "application/json",
          "Idempotency-Key": `delete-${crypto.sha256(documentId, "hex")}`,
        },
        timeout: "60s",
        tags: { endpoint: "delete" },
      });
      const deletion = assertJson(removal, 202, "delete");
      let deletionState = deletion;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        if (["purged", "dead_letter"].includes(deletionState.state)) break;
        const response = http.get(relativeOrAbsolute(deletionState.status_url), {
          tags: { endpoint: "deletion_poll" },
        });
        deletionState = assertJson(response, 200, "deletion poll");
        sleep(0.5);
      }
      check(deletionState, {
        "synthetic document purge succeeds": (value) =>
          value.state === "purged" &&
          value.receipt !== null &&
          value.receipt.deleted_count === value.object_count,
      });
    }
    journeyDuration.add(Date.now() - started);
  }
}
