import crypto from "k6/crypto";
import http from "k6/http";
import { check, fail } from "k6";
import { Trend } from "k6/metrics";

import { guardedBaseUrl, jsonHeaders, requireFixture } from "./safety.js";

const baseUrl = guardedBaseUrl();
requireFixture([
  "AKC_TEST_EMAIL",
  "AKC_TEST_PASSWORD",
  "AKC_TEST_PROJECT_ID",
  "AKC_SYNTHETIC_10000_PAGE_PDF",
]);
const fixture = open(__ENV.AKC_SYNTHETIC_10000_PAGE_PDF, "b");
const enqueueDuration = new Trend("akc_enqueue_duration", true);

export const options = {
  scenarios: {
    enqueue_10000_pages: {
      executor: "shared-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: "5m",
    },
  },
  thresholds: {
    checks: ["rate==1"],
    akc_enqueue_duration: ["p(95)<2000"],
  },
};

function expectJson(response, status, label) {
  if (
    !check(response, {
      [`${label} status`]: (value) => value.status === status,
      [`${label} JSON`]: (value) =>
        String(value.headers["Content-Type"] || "").includes(
          "application/json",
        ),
    })
  ) {
    fail(`${label} failed with HTTP ${response.status}`);
  }
  return response.json();
}

export default function () {
  const login = expectJson(
    http.post(
      `${baseUrl}/v1/auth/login`,
      JSON.stringify({
        email: __ENV.AKC_TEST_EMAIL,
        password: __ENV.AKC_TEST_PASSWORD,
      }),
      { headers: jsonHeaders() },
    ),
    200,
    "login",
  );
  const token = login.access_token;
  const digest = crypto.sha256(fixture, "hex");
  const initiated = expectJson(
    http.post(
      `${baseUrl}/v1/uploads/initiate`,
      JSON.stringify({
        project_id: __ENV.AKC_TEST_PROJECT_ID,
        filename: "synthetic-10000-pages.pdf",
        size: fixture.byteLength,
        content_type: "application/pdf",
        sha256: digest,
      }),
      {
        headers: jsonHeaders(token, {
          "Idempotency-Key": `load-10k-init-${digest}`,
        }),
      },
    ),
    201,
    "upload initiate",
  );
  const transfer = http.put(initiated.upload_url, fixture, {
    headers: initiated.headers || { "Content-Type": "application/pdf" },
    timeout: "4m",
  });
  if (![200, 204].includes(transfer.status)) fail("fixture transfer failed");
  expectJson(
    http.post(
      `${baseUrl}/v1/uploads/${initiated.upload_id}/complete`,
      JSON.stringify({ sha256: digest }),
      {
        headers: jsonHeaders(token, {
          "Idempotency-Key": `load-10k-complete-${digest}`,
        }),
      },
    ),
    200,
    "upload complete",
  );

  const started = Date.now();
  const analyze = http.post(
    `${baseUrl}/v1/documents/${initiated.document_id}/analyze`,
    null,
    {
      headers: jsonHeaders(token, {
        "Idempotency-Key": `load-10k-analyze-${digest}`,
      }),
    },
  );
  enqueueDuration.add(Date.now() - started);
  expectJson(analyze, 202, "analysis enqueue");
}
