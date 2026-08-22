import crypto from "k6/crypto";
import http from "k6/http";
import { check, fail } from "k6";
import { Trend } from "k6/metrics";

import { guardedBaseUrl, jsonHeaders, requireFixture } from "./safety.js";

const baseUrl = guardedBaseUrl();
requireFixture(["AKC_TEST_TOKEN", "AKC_TEST_PROJECT_ID", "AKC_RUN_ID"]);
const manifestPlanDuration = new Trend("akc_manifest_plan_duration", true);
const manifestFilesObserved = new Trend("akc_manifest_files_observed");

export const options = {
  scenarios: {
    collection_manifest_5000: {
      executor: "shared-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: "5m",
    },
  },
  thresholds: {
    checks: ["rate==1"],
    http_req_failed: ["rate<0.01"],
    akc_manifest_plan_duration: ["p(95)<30000"],
    akc_manifest_files_observed: ["min==5000", "max==5000"],
  },
};

function requestHeaders(idempotencyKey) {
  return jsonHeaders(__ENV.AKC_TEST_TOKEN, {
    "Idempotency-Key": idempotencyKey,
  });
}

function expectJson(response, status, label) {
  const accepted = check(response, {
    [`${label} status ${status}`]: (value) => value.status === status,
    [`${label} JSON`]: (value) =>
      String(value.headers["Content-Type"] || "").includes("application/json"),
  });
  if (!accepted) fail(`${label} failed with HTTP ${response.status}`);
  return response.json();
}

function syntheticFiles() {
  const files = [];
  for (let index = 0; index < 5000; index += 1) {
    const suffix = String(index).padStart(4, "0");
    const filename = `synthetic-${suffix}.txt`;
    files.push({
      relative_path: `scale/${filename}`,
      display_name: filename,
      size_bytes: 1024,
      last_modified_ms: index,
      expected_mime: "text/plain",
      sha256: crypto.sha256(`${__ENV.AKC_RUN_ID}:${index}`, "hex"),
      quick_fingerprint: `scale_${__ENV.AKC_RUN_ID}_${suffix}`,
    });
  }
  return files;
}

export default function () {
  let collectionId = null;
  try {
    const collection = expectJson(
      http.post(
        `${baseUrl}/v1/collections`,
        JSON.stringify({
          project_id: __ENV.AKC_TEST_PROJECT_ID,
          name: `Synthetic 5k manifest ${__ENV.AKC_RUN_ID}`,
          description: "Synthetic nonproduction scale fixture; no customer data.",
          profile: { readiness_profile: "collection_manifest_5000" },
        }),
        {
          headers: requestHeaders(`scale-5k-create-${__ENV.AKC_RUN_ID}`),
          tags: { endpoint: "collection_create" },
        },
      ),
      201,
      "collection create",
    );
    collectionId = collection.id;
    const source = expectJson(
      http.post(
        `${baseUrl}/v1/collections/${encodeURIComponent(collectionId)}/sources/local`,
        JSON.stringify({
          display_name: "synthetic-5k-manifest",
          source_fingerprint: crypto.sha256(
            `source:${__ENV.AKC_RUN_ID}`,
            "hex",
          ),
        }),
        {
          headers: requestHeaders(`scale-5k-source-${__ENV.AKC_RUN_ID}`),
          tags: { endpoint: "collection_source" },
        },
      ),
      201,
      "source create",
    );

    const started = Date.now();
    const planned = expectJson(
      http.post(
        `${baseUrl}/v1/collections/${encodeURIComponent(collectionId)}/files/plan`,
        JSON.stringify({
          source_root_id: source.id,
          files: syntheticFiles(),
        }),
        {
          headers: requestHeaders(`scale-5k-plan-${__ENV.AKC_RUN_ID}`),
          timeout: "2m",
          tags: { endpoint: "collection_plan_5000" },
        },
      ),
      201,
      "manifest plan",
    );
    manifestPlanDuration.add(Date.now() - started);
    manifestFilesObserved.add(Number(planned.upload.total_files));
    if (
      !check(planned, {
        "exactly 5,000 files are returned": (value) =>
          value.files.length === 5000 && value.upload.total_files === 5000,
        "manifest remains upload-only": (value) =>
          value.collection.status === "UPLOADING" &&
          value.upload.completed_files === 0,
      })
    ) {
      fail("5,000-file manifest response did not preserve exact dimensions");
    }
  } finally {
    if (collectionId) {
      const cleanup = http.del(
        `${baseUrl}/v1/collections/${encodeURIComponent(collectionId)}`,
        null,
        {
          headers: requestHeaders(`scale-5k-delete-${__ENV.AKC_RUN_ID}`),
          tags: { endpoint: "collection_cleanup" },
        },
      );
      check(cleanup, {
        "disposable collection cleanup succeeds": (value) =>
          [200, 202, 204].includes(value.status),
      });
    }
  }
}
