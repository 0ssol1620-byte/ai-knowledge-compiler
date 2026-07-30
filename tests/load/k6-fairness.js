import http from "k6/http";
import { check, fail, sleep } from "k6";
import { Trend } from "k6/metrics";

import { guardedBaseUrl, jsonHeaders, requireFixture } from "./safety.js";

const baseUrl = guardedBaseUrl();
requireFixture([
  "AKC_SMALL_TENANT_TOKEN",
  "AKC_LARGE_TENANT_TOKEN",
  "AKC_SMALL_DOCUMENT_ID",
  "AKC_LARGE_DOCUMENT_ID",
]);
const smallWait = new Trend("akc_small_job_wait", true);

export const options = {
  scenarios: {
    large_tenant_pressure: {
      executor: "constant-vus",
      exec: "largeTenant",
      vus: 16,
      duration: "15m",
    },
    small_tenant_probe: {
      executor: "constant-vus",
      exec: "smallTenant",
      vus: 4,
      duration: "15m",
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    akc_small_job_wait: ["p(95)<30000"],
  },
};

function enqueue(documentId, token, prefix) {
  const response = http.post(
    `${baseUrl}/v1/documents/${encodeURIComponent(documentId)}/compile`,
    JSON.stringify({ confirmed: true }),
    {
      headers: jsonHeaders(token, {
        "Idempotency-Key": `${prefix}-${__VU}-${__ITER}`,
      }),
      tags: { tenant_size: prefix },
    },
  );
  if (
    !check(response, { "compile admitted": (value) => value.status === 202 })
  ) {
    fail(`compile failed with ${response.status}`);
  }
  return response.json().job_id;
}

function waitForStart(jobId, token) {
  const started = Date.now();
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const response = http.get(
      `${baseUrl}/v1/jobs/${encodeURIComponent(jobId)}`,
      {
        headers: jsonHeaders(token),
        tags: { endpoint: "fairness_job_poll" },
      },
    );
    if (response.status === 200) {
      const state = response.json().status;
      if (!["queued", "pending"].includes(state)) return Date.now() - started;
    }
    sleep(0.25);
  }
  return Date.now() - started;
}

export function largeTenant() {
  enqueue(__ENV.AKC_LARGE_DOCUMENT_ID, __ENV.AKC_LARGE_TENANT_TOKEN, "large");
}

export function smallTenant() {
  const jobId = enqueue(
    __ENV.AKC_SMALL_DOCUMENT_ID,
    __ENV.AKC_SMALL_TENANT_TOKEN,
    "small",
  );
  smallWait.add(waitForStart(jobId, __ENV.AKC_SMALL_TENANT_TOKEN));
}
