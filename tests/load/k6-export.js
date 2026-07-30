import http from "k6/http";
import { check } from "k6";

import { guardedBaseUrl, jsonHeaders, requireFixture } from "./safety.js";

const baseUrl = guardedBaseUrl();
requireFixture(["AKC_TEST_TOKEN", "AKC_TEST_JOB_ID"]);

export const options = {
  scenarios: {
    export_burst_100: {
      executor: "shared-iterations",
      vus: 100,
      iterations: 100,
      maxDuration: "10m",
    },
  },
  thresholds: {
    checks: ["rate>0.99"],
    http_req_failed: ["rate<0.01"],
  },
};

export default function () {
  const response = http.post(
    `${baseUrl}/v1/jobs/${encodeURIComponent(__ENV.AKC_TEST_JOB_ID)}/exports`,
    JSON.stringify({ format: "portable_markdown" }),
    {
      headers: jsonHeaders(__ENV.AKC_TEST_TOKEN, {
        "Idempotency-Key": `export-burst-${__VU}-${__ITER}`,
      }),
      tags: { endpoint: "export_create" },
    },
  );
  check(response, {
    "export is accepted": (value) => [200, 201, 202].includes(value.status),
  });
}
